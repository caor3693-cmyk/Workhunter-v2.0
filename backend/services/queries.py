"""Read projections share a single database snapshot and never contact sources."""

from dataclasses import dataclass, asdict
from datetime import date, time, timedelta
import json
import sqlite3

from backend.storage.database import DatabaseUnavailable
from backend.domain.candidates import CORE_FIELDS, STATES, MAX_INTEGER, safe_url, validate_evidence, locator_identifies_identity


@dataclass(frozen=True)
class Filters:
    school_key: str | None = None
    campus_id: int | None = None
    campus_unknown: bool = False
    kind: str | None = None
    keyword: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    view: str = "recent"
    scope: str = "electrical"
    offset: int = 0
    limit: int = 20
    dataset_id: str | None = None
    as_of: str | None = None


def identity(metadata: dict[str, str]) -> dict:
    return {"dataset_id": metadata["dataset_id"], "data_mode": metadata["data_mode"]}


def source_projection(row: sqlite3.Row) -> dict:
    from backend.domain.source_policy import school_policy
    registered = any(item['source_key'] == row['source_key'] for item in school_policy(row['school_key']).get('sources', []))
    try:
        safe_url(row['official_entry_url'])
    except ValueError as error:
        raise DatabaseUnavailable('数据库中的来源入口链接无效。') from error
    return {
        "source_key": row["source_key"], "school_key": row["school_key"],
        "school_name": row["school_name"], "name": row["name"],
        "official_entry_url": row["official_entry_url"],
        "verification_state": row["verification_state"], "status": row["status"],
        "last_attempt_at": row["last_attempt_at"], "last_success_at": row["last_success_at"],
        "message": row["public_message"],
        "channel_key": row['channel_key'], "scope": _decode(row['scope_json'], dict),
        "maintenance_material_supported": registered,
    }


def sources(connection: sqlite3.Connection) -> list[dict]:
    return [source_projection(row) for row in connection.execute(
        "SELECT s.*, school.name AS school_name FROM sources s JOIN schools school USING(school_key) ORDER BY school.rowid,s.source_key"
    )]


def catalog(connection: sqlite3.Connection, metadata: dict[str, str]) -> dict:
    all_sources = sources(connection)
    schools = []
    for school in connection.execute("SELECT * FROM schools ORDER BY rowid"):
        school_sources = [source for source in all_sources if source["school_key"] == school["school_key"]]
        count = connection.execute("SELECT COUNT(*) FROM opportunities o WHERE school_key=? AND "+VISIBLE_SQL, (school["school_key"],)).fetchone()[0]
        campuses = [dict(row) for row in connection.execute(
            "SELECT id,campus_key,name,evidence_url FROM campuses WHERE school_key=? ORDER BY id", (school["school_key"],),
        )]
        try:
            for campus in campuses:
                safe_url(campus['evidence_url'],school['school_key'])
        except ValueError as error:
            raise DatabaseUnavailable('数据库中的校区依据链接无效。') from error
        states = {source['status'] for source in school_sources}
        successful = states & {'success', 'partial'}
        if successful:
            availability = 'partial' if school['verification_state'] == 'partial' or states & {'partial','failed','restricted','checking'} else 'available'
            message = '已取得部分公开材料，非全校完整覆盖' if availability == 'partial' else '已检查登记栏目范围，覆盖以来源说明为准'
        elif 'restricted' in states:
            availability, message = 'restricted', '已检查入口受限，保留此前收录'
        elif 'failed' in states:
            availability, message = 'failed', '检查失败，保留此前收录'
        elif 'checking' in states:
            availability, message = 'checking', '正在检查，保留此前收录'
        else:
            availability, message = 'pending', '待核验 · 尚未检查'
        schools.append({
            "school_key": school["school_key"], "name": school["name"],
            "campuses": campuses, "verification_state": school["verification_state"],
            "availability": availability, "availability_message": message,
            "scope_note": school['scope_note'], 'verified_at': school['verified_at'],
            "opportunity_count": count, "sources": school_sources,
        })
    return {**identity(metadata), "schools": schools}


def _decode(value: str, expected_type):
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise DatabaseUnavailable("数据库中的公告字段不可读，请检查数据完整性。") from exc
    if not isinstance(decoded, expected_type):
        raise DatabaseUnavailable("数据库中的公告字段结构无效，请检查数据完整性。")
    return decoded


def _stored_evidence(items, row, connection):
    evidence = validate_evidence(items,row['school_key'])
    for item in evidence:
        if type(item.get('material_id')) is not int or item.get('material_ref') or item.get('source_identity')!=row['source_identity'] or type(item.get('association_id')) is not int:
            raise ValueError('读取证据缺少已核实材料公告关联。')
        material = connection.execute('SELECT * FROM source_materials WHERE id=?',(item['material_id'],)).fetchone()
        relation = connection.execute('SELECT * FROM opportunity_materials WHERE id=?',(item['association_id'],)).fetchone()
        if material is None or material['source_key']!=row['source_key'] or material['source_url']!=item['source_url'] or material['acquisition_status']!='success' or material['opportunity_id'] not in (None,row['id']):
            raise ValueError('材料缺失、归属或链接错配。')
        _decode(material['scope_json'],dict)
        if material['official_record_id'] is not None and material['official_record_id']!=row['source_identity']:
            raise ValueError('材料属于另一公告。')
        if relation is None or relation['opportunity_id']!=row['id'] or relation['material_id']!=material['id'] or relation['source_identity']!=row['source_identity'] or relation['school_key']!=row['school_key'] or relation['source_key']!=row['source_key'] or relation['locator']!=item['locator'] or _decode(relation['scope_json'],(dict,str))!=item['scope']:
            raise ValueError('材料公告关联与证据不一致。')
        basis=_decode(relation['basis_json'],dict)
        if any(basis.get(key)!=item[key] for key in ('source_identity','source_url','locator')) or basis.get('material_hash')!=material['material_hash'] or not isinstance(basis.get('excerpt'),str) or not basis['excerpt'] or relation['relation_kind'] not in {'list','body','attachment_link'}:
            raise ValueError('材料关系核验依据不完整或错配。')
        if material['official_record_id'] is None and (_decode(material['scope_json'],dict).get('type')!='source_list' or not locator_identifies_identity(item['locator'],row['source_identity'])):
            raise ValueError('共享列表缺少本条身份定位。')
    return evidence


def _attachment_chain(fragment, row, connection):
    chain = fragment.get('link_chain')
    if not isinstance(chain,dict) or chain.get('target_url')!=fragment.get('url') or chain.get('source_identity')!=row['source_identity'] or type(chain.get('association_id')) is not int:
        raise ValueError('附件缺少本条公告链接链。')
    proof = {**chain,'excerpt':'附件链接','observed_at':chain.get('observed_at'),'parser_version':chain.get('parser_version')}
    _stored_evidence([proof],row,connection)
    relation = connection.execute('SELECT link_chain_json FROM opportunity_materials WHERE id=?',(chain['association_id'],)).fetchone()
    saved = _decode(relation[0],dict)
    if saved.get('target_url')!=fragment['url'] or saved.get('source_url')!=chain['source_url'] or saved.get('locator')!=chain['locator']:
        raise ValueError('附件目标不匹配已核实链。')


def _observations(row, connection):
    observations = _decode(row['field_observations_json'], dict)
    try:
        if set(observations) - (set(CORE_FIELDS) | {'relevance'}):
            raise ValueError('未知字段观察')
        for field in CORE_FIELDS:
            observations.setdefault(field, {'state':'not_collected','value':None,'evidence':[]})
        for field, observation in observations.items():
            if not isinstance(observation, dict) or not isinstance(observation.get('state'), str) or observation['state'] not in STATES:
                raise ValueError('字段状态无效')
            evidence = _stored_evidence(observation.get('evidence', []), row, connection)
            value = _decode(row['work_locations_json'],list) if field=='work_locations' else row[field]
            if observation['state'] == 'known':
                if not evidence or observation.get('value') in (None, '', []):
                    raise ValueError('已知字段缺少证据')
                if observation['value'] != value:
                    raise ValueError('已知证据值与业务字段冲突')
            elif observation.get('value') is not None:
                raise ValueError('未知字段出现伪值')
            if field in CORE_FIELDS and observation['state'] not in {'known', 'conflict'} and value not in (None, []):
                raise ValueError('没有已知观察的业务字段不得展示为事实')
            if observation['state'] in {'not_disclosed','not_applicable'} and not evidence:
                raise ValueError('已检查状态缺少材料依据')
            if observation['state'] == 'conflict' and len(evidence) < 2:
                raise ValueError('冲突材料缺失')
        relevance = observations.get('relevance', {})
        if row['relevance'] != 'unknown' and (relevance.get('state') != 'known' or relevance.get('value') != row['relevance']):
            raise ValueError('明确相关性缺少本条材料观察')
        return observations
    except (ValueError, TypeError, KeyError) as error:
        raise DatabaseUnavailable('数据库中的字段证据不可读，请核对已归档材料。') from error


def card(row: sqlite3.Row, connection: sqlite3.Connection) -> dict:
    fields = (
        "id", "school_key", "school_name", "campus_id", "campus_name", "title", "kind",
        "original_kind", "date_basis", "source_url", "published_date", "event_date",
        "start_time", "end_time", "deadline", "event_venue", "work_locations_scope",
        "relevance", "event_status", "recruitment_status",
    )
    locations = _decode(row['work_locations_json'], list)
    if len(locations) > 50 or any(not isinstance(value, str) or not value or len(value)>300 for value in locations):
        raise DatabaseUnavailable('数据库中的工作地点结构不可读。')
    try:
        safe_url(row['source_url'], row['school_key'])
        for field in ('published_date','event_date','deadline'):
            if row[field] and date.fromisoformat(row[field]).isoformat() != row[field]:
                raise ValueError('无效日期')
        for field in ('start_time','end_time'):
            if row[field] and (len(row[field])!=5 or time.fromisoformat(row[field]).strftime('%H:%M')!=row[field]):
                raise ValueError('无效时段')
    except ValueError as error:
        raise DatabaseUnavailable('数据库中的来源链接或日期无效。') from error
    return {
        **{field: row[field] for field in fields},
        "work_locations": locations,
        "field_observations": _observations(row, connection),
        "detail_url": f"/opportunities/{row['id']}",
    }


PROJECTION_SQL = """SELECT o.*, s.name AS school_name, c.name AS campus_name
FROM opportunities o JOIN schools s USING(school_key)
LEFT JOIN campuses c ON o.campus_id=c.id"""

VISIBLE_SQL = "NOT EXISTS (SELECT 1 FROM field_decisions visibility WHERE visibility.opportunity_id=o.id AND visibility.field_name='__visibility__' AND visibility.value_json='false')"


def opportunities(connection: sqlite3.Connection, metadata: dict[str, str], filters: Filters, today: date, recent_days: int) -> dict:
    today = date.fromisoformat(filters.as_of) if filters.as_of else today
    start = today - timedelta(days=recent_days - 1)
    end = today + timedelta(days=recent_days)
    clauses, values = [VISIBLE_SQL], []
    for field in ("school_key", "campus_id", "kind"):
        value = getattr(filters, field)
        if value is not None:
            clauses.append(f"o.{field}=?")
            values.append(value)
    if filters.campus_unknown:
        clauses.append("o.campus_id IS NULL")
    if filters.scope == "electrical":
        clauses.append("o.relevance IN ('related','unknown')")
    if filters.keyword:
        clauses.append("o.title LIKE ? ESCAPE '\\'")
        literal = filters.keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.append("%" + literal + "%")
    # Conflict keeps the previous scalar for history, not for a confirmed date match.
    published_date = "CASE WHEN json_extract(o.field_observations_json,'$.published_date.state')='conflict' THEN NULL ELSE o.published_date END"
    event_date = "CASE WHEN json_extract(o.field_observations_json,'$.event_date.state')='conflict' THEN NULL ELSE o.event_date END"
    business_date = f"CASE WHEN o.date_basis='event' THEN ({event_date}) ELSE ({published_date}) END"
    if filters.view == "recent":
        clauses.append(f"(({published_date}) BETWEEN ? AND ? OR ({event_date}) BETWEEN ? AND ?)")
        values.extend([start.isoformat(), today.isoformat(), today.isoformat(), end.isoformat()])
    elif filters.view == "upcoming":
        clauses.append(f"o.date_basis='event' AND ({event_date})>=? AND o.event_status!='cancelled'")
        values.append(today.isoformat())
    elif filters.view == "history":
        clauses.append(f"((o.date_basis='event' AND ({event_date})<?) OR (o.date_basis='publication' AND ({published_date})<?))")
        values.extend([today.isoformat(), start.isoformat()])
    else:
        clauses.append(f"({business_date}) IS NULL")
    for field, operator in (("date_from", ">="), ("date_to", "<=")):
        value = getattr(filters, field)
        if value:
            clauses.append(f"({business_date}){operator}?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = connection.execute("SELECT COUNT(*) FROM opportunities o" + where, values).fetchone()[0]
    order = f"({event_date}) ASC, COALESCE(o.start_time,'') ASC, o.id ASC" if filters.view == "upcoming" else f"COALESCE(({published_date}),o.first_seen_at) DESC,o.id DESC"
    items = [card(row, connection) for row in connection.execute(
        PROJECTION_SQL + where + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*values, filters.limit, filters.offset],
    )]
    applied = asdict(filters)
    for key in ("offset", "limit", "dataset_id"):
        applied.pop(key)
    applied["recent_window"] = {
        "days": recent_days, "published_from": start.isoformat(), "published_to": today.isoformat(),
        "events_from": today.isoformat(), "events_to": end.isoformat(),
    }
    applied['as_of'] = today.isoformat()
    empty_reason = None
    if total == 0:
        if connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0:
            empty_reason = "empty_database"
        elif filters.school_key and connection.execute("SELECT COUNT(*) FROM opportunities WHERE school_key=?", (filters.school_key,)).fetchone()[0] == 0:
            empty_reason = "school_not_collected"
        elif filters.view == "undated":
            empty_reason = "no_undated_matches"
        else:
            empty_reason = "no_matches"
    return {
        **identity(metadata), "as_of": today.isoformat(), "items": items, "total": total, "offset": filters.offset,
        "limit": filters.limit, "has_more": filters.offset + len(items) < total,
        "applied_filters": applied, "empty_reason": empty_reason,
    }


def detail(connection: sqlite3.Connection, opportunity_id: int, *, include_hidden=False) -> dict | None:
    row = connection.execute(PROJECTION_SQL+' WHERE o.id=?'+('' if include_hidden else ' AND '+VISIBLE_SQL),(opportunity_id,)).fetchone()
    if row is None: return None
    result = {**card(row,connection),'first_seen_at':row['first_seen_at'],'content_changed_at':row['content_changed_at'],
              'source_updated_at':row['source_updated_at'],'version':row['version'],
              'official_sources':[{'source_key':row['source_key'],'url':row['source_url']}], 'supplemental_status':'verified'}
    omitted = int(connection.execute("SELECT 1 FROM processing_tasks WHERE opportunity_id=? AND task_kind='maintenance' AND task_identity LIKE 'quarantine:%' AND status NOT IN ('resolved','complete','superseded') LIMIT 1",(opportunity_id,)).fetchone() is not None)
    for field in ('roster_fragments','job_fragments','attachments'):
        result[field] = []
        try:
            fragments = _decode(row[field+'_json'],list)
            if len(fragments)>8: raise ValueError('片段超过限量')
        except (DatabaseUnavailable,ValueError):
            omitted += 1
            continue
        for fragment in fragments:
            try:
                if not isinstance(fragment,dict) or not fragment.get('scope') or not fragment.get('evidence'):
                    raise ValueError('片段缺少适用范围或证据')
                _stored_evidence(fragment['evidence'],row,connection)
                if field=='attachments':
                    safe_url(fragment.get('url'),row['school_key'])
                    if not isinstance(fragment.get('label'),str) or not fragment['label'] or len(fragment['label'])>500:
                        raise ValueError('附件标题无效')
                    _attachment_chain(fragment,row,connection)
                elif fragment['scope'] not in ('partial','complete_for_material','unknown') or not isinstance(fragment.get('text'),str) or not fragment['text'] or len(fragment['text'])>2000:
                    raise ValueError('片段范围或内容无效')
                result[field].append(fragment)
            except (DatabaseUnavailable,ValueError,TypeError,KeyError):
                omitted += 1
    if omitted:
        result['supplemental_status']='pending_verification'
        result['supplemental_message']='部分附加材料待核实，已保留可靠公告字段。'
    ids = set()
    def collect(value):
        if isinstance(value,dict):
            if 'material_id' in value: ids.add(value['material_id'])
            for nested in value.values(): collect(nested)
        elif isinstance(value,list):
            for nested in value: collect(nested)
    collect(result)
    materials=[]
    for material_id in sorted(ids):
        material=connection.execute('SELECT * FROM source_materials WHERE id=? AND source_key=?',(material_id,row['source_key'])).fetchone()
        materials.append({key:material[key] for key in ('id','source_key','source_url','material_hash','fetched_at','acquisition_status','parsing_status','parser_version')} | {'scope':_decode(material['scope_json'],dict)})
    result['materials']=materials
    source=connection.execute('SELECT scope_json FROM sources WHERE source_key=?',(row['source_key'],)).fetchone()
    result['coverage']=_decode(source[0],dict)
    return result


def summary(connection, metadata, today, *, recent_days=30):
    from backend.services.updates import build_summary
    return build_summary(connection,metadata,today,recent_days=recent_days)
