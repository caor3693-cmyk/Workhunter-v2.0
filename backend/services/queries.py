"""Read projections share a single database snapshot and never contact sources."""

from dataclasses import dataclass, asdict
from datetime import date, time, timedelta
import json
import sqlite3

from backend.storage.database import DatabaseUnavailable
from backend.domain.candidates import CORE_FIELDS, STATES, MAX_INTEGER, safe_url, validate_evidence


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
        count = connection.execute("SELECT COUNT(*) FROM opportunities WHERE school_key=?", (school["school_key"],)).fetchone()[0]
        campuses = [dict(row) for row in connection.execute(
            "SELECT id,campus_key,name,evidence_url FROM campuses WHERE school_key=? ORDER BY id", (school["school_key"],),
        )]
        try:
            for campus in campuses:
                safe_url(campus['evidence_url'], school['school_key'] if school['school_key'] in ('scut','gdut') else None)
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
    evidence = validate_evidence(items, row['school_key'])
    for item in evidence:
        if type(item.get('material_id')) is not int or not 0 < item['material_id'] <= MAX_INTEGER or item.get('material_ref'):
            raise ValueError('读取证据未绑定已归档材料ID')
        material = connection.execute('SELECT * FROM source_materials WHERE id=?', (item['material_id'],)).fetchone()
        if material is None or material['source_key'] != row['source_key'] or material['source_url'] != item['source_url'] or material['acquisition_status'] != 'success' or material['opportunity_id'] not in (None, row['id']):
            raise ValueError('材料缺失、归属或链接错配')
    return evidence


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


def opportunities(connection: sqlite3.Connection, metadata: dict[str, str], filters: Filters, today: date, recent_days: int) -> dict:
    today = date.fromisoformat(filters.as_of) if filters.as_of else today
    start = today - timedelta(days=recent_days - 1)
    end = today + timedelta(days=recent_days)
    clauses, values = [], []
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
    business_date = "CASE WHEN o.date_basis='event' THEN o.event_date ELSE o.published_date END"
    if filters.view == "recent":
        clauses.append("(o.published_date BETWEEN ? AND ? OR o.event_date BETWEEN ? AND ?)")
        values.extend([start.isoformat(), today.isoformat(), today.isoformat(), end.isoformat()])
    elif filters.view == "upcoming":
        clauses.append("o.date_basis='event' AND o.event_date>=? AND o.event_status!='cancelled'")
        values.append(today.isoformat())
    elif filters.view == "history":
        clauses.append("((o.date_basis='event' AND o.event_date<?) OR (o.date_basis='publication' AND o.published_date<?))")
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
    order = "o.event_date ASC, COALESCE(o.start_time,'') ASC, o.id ASC" if filters.view == "upcoming" else "COALESCE(o.published_date,o.first_seen_at) DESC,o.id DESC"
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


def detail(connection: sqlite3.Connection, opportunity_id: int) -> dict | None:
    row = connection.execute(PROJECTION_SQL + " WHERE o.id=?", (opportunity_id,)).fetchone()
    if row is None:
        return None
    result = {
        **card(row, connection), "first_seen_at": row["first_seen_at"],
        "content_changed_at": row["content_changed_at"], "source_updated_at": row["source_updated_at"],
        "version": row["version"], "roster_fragments": _decode(row["roster_fragments_json"], list),
        "job_fragments": _decode(row["job_fragments_json"], list),
        "attachments": _decode(row["attachments_json"], list),
        "official_sources": [{"source_key": row["source_key"], "url": row["source_url"]}],
    }
    try:
        for field in ('roster_fragments','job_fragments','attachments'):
            if len(result[field]) > 8:
                raise ValueError('片段超过限量')
            for fragment in result[field]:
                if not isinstance(fragment, dict) or not fragment.get('scope'):
                    raise ValueError('片段适用范围无效')
                _stored_evidence(fragment.get('evidence', []), row, connection)
                if not fragment.get('evidence'):
                    raise ValueError('片段无材料')
                if field == 'attachments':
                    safe_url(fragment.get('url'), row['school_key'])
                    if not isinstance(fragment.get('label'),str) or len(fragment['label'])>500:
                        raise ValueError('附件标题无效')
                elif fragment['scope'] not in ('partial','complete_for_material','unknown') or not isinstance(fragment.get('text'),str) or not fragment['text'] or len(fragment['text'])>2000:
                    raise ValueError('片段范围或内容无效')
        ids = set()
        def collect(value):
            if isinstance(value,dict):
                if 'material_id' in value: ids.add(value['material_id'])
                for nested in value.values(): collect(nested)
            elif isinstance(value,list):
                for nested in value: collect(nested)
        collect(result)
        materials = []
        for material_id in sorted(ids):
            material = connection.execute('SELECT * FROM source_materials WHERE id=? AND source_key=?', (material_id,row['source_key'])).fetchone()
            if material is None or material['acquisition_status']!='success':
                raise ValueError('材料缺失或来源错配')
            materials.append({key:material[key] for key in ('id','source_key','source_url','material_hash','fetched_at','acquisition_status','parsing_status','parser_version') } | {'scope':_decode(material['scope_json'],dict)})
        result['materials'] = materials
        source = connection.execute('SELECT scope_json FROM sources WHERE source_key=?',(row['source_key'],)).fetchone()
        result['coverage'] = _decode(source[0],dict)
        return result
    except (ValueError, TypeError, KeyError) as error:
        raise DatabaseUnavailable('数据库中的公告片段或材料证据不可读。') from error


def summary(connection, metadata, today):
    run = connection.execute('SELECT * FROM runs ORDER BY started_at DESC,id DESC LIMIT 1').fetchone()
    last_success = connection.execute("SELECT MAX(finished_at) FROM runs WHERE status IN ('complete','partial')").fetchone()[0]
    checked_today = connection.execute('SELECT 1 FROM runs WHERE substr(started_at,1,10)=? LIMIT 1',(today.isoformat(),)).fetchone()
    counts = {row[0]:row[1] for row in connection.execute('SELECT change_kind,COUNT(DISTINCT opportunity_id) FROM changes WHERE substr(committed_at,1,10)=? GROUP BY change_kind',(today.isoformat(),))} if checked_today else {}
    values = {kind:counts.get(kind,0) if checked_today else None for kind in ('newly_collected','official_change','parser_improvement','evidence_conflict')}
    source_checks = connection.execute("SELECT MAX(last_attempt_at),MAX(last_success_at) FROM sources").fetchone()
    status = run['status'] if run else 'not_checked'
    return {**identity(metadata),'check_status':status,'last_attempt_at':run['started_at'] if run else source_checks[0],
        'last_success_at':last_success or source_checks[1],
        'today':{'date':today.isoformat(),'newly_collected':values['newly_collected'],
            'modified':None if not checked_today else len({r[0] for r in connection.execute("SELECT opportunity_id FROM changes WHERE change_kind IN ('official_change','parser_improvement','evidence_conflict') AND substr(committed_at,1,10)=?",(today.isoformat(),))}),
            'official_changes':values['official_change'],'parser_improvements':values['parser_improvement'],'evidence_conflicts':values['evidence_conflict'],'manual_corrections':None},
        'scope':_decode(run['scope_json'],dict) if run else None,
        'message':'尚未检查，新增与变化数量未知' if not run else '本轮已检查登记范围；新收录按取得时间计，不代表今天官方发布。人工更正汇总尚未实现。'}
