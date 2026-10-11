"""One evidence-aware write service for list, detail and future maintenance inputs."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from backend.config import ROOT
from backend.domain.candidates import CORE_FIELDS, safe_url, validate_candidate, locator_identifies_identity
from backend.storage.write import writer_transaction, WriteContext, WriteConflict, context_request_hash, begin_fact_write, finish_fact_write


BUSINESS_FIELDS = (
    "campus_id", "title", "kind", "original_kind", "date_basis", "source_url",
    *CORE_FIELDS, "work_locations_scope", "relevance", "event_status",
    "recruitment_status", "source_updated_at", "field_observations",
    "roster_fragments", "job_fragments", "attachments",
)
JSON_FIELDS = {"work_locations", "field_observations", "roster_fragments", "job_fragments", "attachments"}
DETAIL_HEADER_FIELDS = {"title", "kind", "original_kind", "date_basis"}


def queue_policy(config):
    policy={'head_pages':1,'detail_recheck_hours':24,'failure_backoff_minutes':60}
    supplied=config.get('queue_policy',{})
    if not isinstance(supplied,dict) or set(supplied)-set(policy):
        raise ValueError('队列配置字段无效。')
    policy.update(supplied)
    bounds={'head_pages':(1,1),'detail_recheck_hours':(1,168),'failure_backoff_minutes':(1,1440)}
    if any(type(policy[key]) is not int or not lower<=policy[key]<=upper for key,(lower,upper) in bounds.items()):
        raise ValueError('队列复核与退避必须使用有界配置。')
    return policy


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assert_data_mode(metadata, fixture):
    mode = metadata["data_mode"]
    if fixture and mode != "isolated_fixture":
        raise ValueError("隔离样例只能写入显式 fixture 初始化的新库。")
    if not fixture and mode == "isolated_fixture":
        raise ValueError("真实采集不能混入隔离样例库，请使用独立真实新库。")


def _source(connection, config):
    row = connection.execute("SELECT * FROM sources WHERE source_key=?", (config["source_key"],)).fetchone()
    if row is None or row["school_key"] != config["school_key"] or row["channel_key"] != config["channel_key"]:
        raise ValueError("来源未显式登记，或学校、栏目归属不一致。")
    return row


def _prepare_materials(materials, source_config, fixture):
    prepared = []
    for material in materials:
        item = deepcopy(material)
        if item.get("source_key") != source_config["source_key"] or not isinstance(item.get("reference_key"), str) or not 1 <= len(item["reference_key"]) <= 256:
            raise ValueError("材料身份或来源归属不一致。")
        safe_url(item.get("source_url", ""), source_config["school_key"])
        if item.get("acquisition_status") not in {"pending", "success", "failed", "restricted"}:
            raise ValueError("材料获取状态无效。")
        if item.get("parsing_status") not in {"pending", "success", "failed", "partial", "not_attempted"}:
            raise ValueError("材料解析状态无效。")
        if not isinstance(item.get("scope", {}), dict):
            raise ValueError("材料范围必须是对象。")
        if item["acquisition_status"] == "success" and not fixture:
            raw = Path(item.get("raw_reference", ""))
            if not raw.is_absolute():
                raw = ROOT / raw
            if not raw.is_file() or raw.stat().st_size > 8_000_000 or hashlib.sha256(raw.read_bytes()).hexdigest() != item.get("material_hash"):
                raise ValueError("成功材料缺少实际归档或内容 hash 不匹配。")
        prepared.append(item)
    return prepared


def _save_materials(connection, materials):
    for item in materials:
        previous = connection.execute(
            "SELECT * FROM source_materials WHERE source_key=? AND reference_key=?",
            (item["source_key"], item["reference_key"]),
        ).fetchone()
        if previous is not None:
            if previous["source_url"] != item["source_url"] or previous["material_hash"] != item.get("material_hash") or previous["official_record_id"] != item.get("official_record_id"):
                raise ValueError("已有材料引用不能指向不同 URL 或内容。")
            continue
        connection.execute(
            "INSERT INTO source_materials(source_key,reference_key,source_url,official_record_id,material_hash,fetched_at,raw_reference,acquisition_status,parsing_status,parser_version,scope_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item["source_key"], item["reference_key"], item["source_url"], item.get("official_record_id"),
             item.get("material_hash"), item.get("fetched_at"), item.get("raw_reference"),
             item["acquisition_status"], item["parsing_status"], item.get("parser_version"), encoded(item.get("scope", {}))),
        )


def _bind_evidence(connection, candidate, material_overrides=()):
    result = deepcopy(candidate)
    overrides={item["reference_key"]:item for item in material_overrides}

    def visit(value):
        if isinstance(value, dict):
            if 'material_ref' in value:
                row = connection.execute('SELECT * FROM source_materials WHERE source_key=? AND reference_key=?',
                                         (candidate['source_key'], value['material_ref'])).fetchone()
                override=overrides.get(value['material_ref'])
                if row is not None and override and any(row[key]!=override.get(key) for key in ('source_url','material_hash','official_record_id')):
                    raise ValueError('已有材料引用不能改换内容或身份。')
                if row is None and override:
                    row={**override,'id':None,'scope_json':encoded(override.get('scope',{}))}
                if row is None or row['acquisition_status']!='success'  or row['source_url']!=value.get('source_url'):
                    raise ValueError('字段证据必须绑定同源实际成功材料，URL不能错配。')
                identity = value.get('source_identity')
                if identity != candidate['source_identity'] or not value.get('locator'):
                    raise ValueError('材料关联缺少本条身份与定位。')
                scope=json.loads(row['scope_json'])
                if not isinstance(scope,dict): raise ValueError('材料范围结构无效。')
                if row['official_record_id'] is not None:
                    if row['official_record_id'] != identity:
                        raise ValueError('单条公告材料不可用于另一条公告。')
                else:
                    if scope.get('type') != 'source_list' or not locator_identifies_identity(value['locator'],identity):
                        raise ValueError('共享列表材料必须有本条身份定位。')
                value['material_id'] = row['id']
                del value['material_ref']
                value.pop('association_id', None)
            elif 'material_id' in value:
                raise ValueError('输入候选不能自造数据库材料ID。')
            for nested in list(value.values()):
                visit(nested)
        elif isinstance(value,list):
            for nested in value: visit(nested)
    visit(result)
    return result


def _associate(connection, candidate, opportunity_id, timestamp):
    def visit(value):
        if isinstance(value,dict):
            if 'material_id' in value:
                identity, locator = value['source_identity'], value['locator']
                chain = {k:v for k,v in value.items() if k not in {'association_id','material_id'}} if 'target_url' in value else {}
                material=connection.execute('SELECT official_record_id,material_hash FROM source_materials WHERE id=?',(value['material_id'],)).fetchone()
                kind='attachment_link' if chain else 'body' if material['official_record_id'] is not None else 'list'
                basis={k:value[k] for k in ('source_identity','source_url','locator','excerpt','observed_at','parser_version')}
                basis['material_hash']=material['material_hash']
                connection.execute('INSERT INTO opportunity_materials(opportunity_id,material_id,school_key,source_key,source_identity,relation_kind,locator,scope_json,basis_json,link_chain_json,verified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id,material_id,locator) DO NOTHING',
                                   (opportunity_id,value['material_id'],candidate['school_key'],candidate['source_key'],identity,kind,locator,encoded(value['scope']),encoded(basis),encoded(chain),timestamp))
                relation = connection.execute('SELECT * FROM opportunity_materials WHERE opportunity_id=? AND material_id=? AND locator=?',
                                              (opportunity_id,value['material_id'],locator)).fetchone()
                if relation['source_identity'] != identity or json.loads(relation['scope_json']) != value['scope']:
                    raise ValueError('同一材料定位不能改换公告身份或范围。')
                if chain:
                    previous = json.loads(relation['link_chain_json'])
                    if previous and _semantic(previous) != _semantic(chain):
                        raise ValueError('同一附件定位不能改换链接目标。')
                    if not previous:
                        connection.execute("UPDATE opportunity_materials SET link_chain_json=?,relation_kind='attachment_link' WHERE id=?",(encoded(chain),relation['id']))
                value['association_id'] = relation['id']
            for nested in list(value.values()): visit(nested)
        elif isinstance(value,list):
            for nested in value: visit(nested)
    visit(candidate)


def _semantic(value):
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if key not in {"evidence", "observed_at", "parser_version", "association_id", "material_id", "material_ref", "excerpt"}}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def _from_row(row):
    result = dict(row)
    for field in JSON_FIELDS:
        raw=result.pop(field+'_json')
        try: result[field]=json.loads(raw)
        except (ValueError,TypeError):
            if field not in {'roster_fragments','job_fragments','attachments'}: raise
            result[field]=[{'_unreadable_json':raw}]
    return result


def _merge(old, candidate, *, task_kind, list_title=None, replace_fields=()):
    if old is None:
        return candidate
    result = {**old, **candidate}
    if task_kind == "list" and list_title == candidate["title"]:
        result["title"] = old["title"]
    observations = deepcopy(candidate["field_observations"])
    for field in CORE_FIELDS:
        previous = old["field_observations"].get(field, {"state": "not_collected", "value": None, "evidence": []})
        incoming = observations[field]
        if incoming["state"] == "conflict":
            result[field] = old[field]
        elif task_kind == "list" and previous["state"] == "conflict" and incoming["state"] == "known" and candidate[field] == old[field]:
            observations[field] = previous
        elif (previous["state"] == "known" and incoming["state"] != "known") or (incoming["state"] == "not_collected" and not incoming.get("evidence")):
            result[field] = old[field]
            observations[field] = previous
        elif _semantic(previous) == _semantic(incoming):
            observations[field] = previous
    result["field_observations"] = observations
    if old["date_basis"] == "event" and candidate["date_basis"] == "publication" and all(candidate["field_observations"][field]["state"] == "not_collected" for field in ("event_date", "start_time", "end_time", "event_venue")):
        for field in ("kind", "original_kind", "date_basis", "event_status"):
            result[field] = old[field]
    if candidate["field_observations"]["work_locations"]["state"] != "known" and old["field_observations"].get("work_locations", {}).get("state") == "known":
        result["work_locations_scope"] = old["work_locations_scope"]
    if candidate["relevance"] == "unknown" and old["relevance"] != "unknown":
        result["relevance"] = old["relevance"]
        if "relevance" in old["field_observations"]:
            observations["relevance"] = old["field_observations"]["relevance"]
    for field in ("event_status", "recruitment_status"):
        if candidate[field] == "unknown" and old[field] != "unknown":
            if field != "event_status" or old[field] != "not_applicable" or result["date_basis"] != "event":
                result[field] = old[field]
    for field in ("original_kind", "source_updated_at"):
        if candidate[field] is None:
            result[field] = old[field]
    for field in ("roster_fragments", "job_fragments", "attachments"):
        if not candidate[field] or _semantic(old[field]) == _semantic(candidate[field]):
            result[field] = old[field]
    for field in replace_fields:
        result[field] = candidate[field]
        if field in CORE_FIELDS or field == 'relevance':
            result['field_observations'][field] = candidate['field_observations'][field]
    return result


def _material_for(candidate, field, fallback_id=None):
    observations = candidate["field_observations"]
    evidence = observations.get(field, {}).get("evidence", [])
    if evidence:
        index = -1 if observations[field].get("state") == "conflict" else 0
        return evidence[index].get("material_id")
    return fallback_id


def _detail_context(connection, candidate):
    row = connection.execute("SELECT * FROM processing_tasks WHERE source_key=? AND task_identity=? AND task_kind='detail'", (candidate["source_key"], "detail:" + candidate["source_identity"])).fetchone()
    result = json.loads(row["result_json"]) if row and row["result_json"] else {}
    context = {"list_title": result.get("list_title", result.get("candidate", {}).get("title"))}
    successful = result.get("last_successful_detail")
    if not successful and row and row["status"] == "committed":
        # Compatibility with completed tasks written before this classification
        # correction. Their changes remain immutable; the task supplies provenance.
        successful = {"run_id": row["run_id"], "committed_at": row["committed_at"]}
    if successful:
        context["last_successful_detail"] = successful
    return context


def _change_kind(connection, old, current, field, *, task_kind, detail_context):
    before, after = old.get(field), current.get(field)
    if field in CORE_FIELDS or field == "relevance":
        previous = old["field_observations"].get(field, {})
        incoming = current["field_observations"].get(field, {})
        if incoming.get("state") == "conflict":
            return "evidence_conflict"
        # An unknown/failed/non-applicable observation becoming more informative
        # is extraction progress. It does not establish an official edit.
        if previous.get("state") != "known" or incoming.get("state") != "known" or before == after:
            return "parser_improvement"
        reliable_ids = [item.get("material_id") for item in previous.get("evidence", [])]
        reliable = any(connection.execute("SELECT 1 FROM source_materials WHERE id=? AND source_key=? AND acquisition_status='success'", (material_id, old["source_key"])).fetchone() for material_id in reliable_ids)
        return "official_change" if reliable else "parser_improvement"
    if before in (None, [], "unknown", "not_applicable") or before == after:
        return "parser_improvement"
    if task_kind == "detail" and field in DETAIL_HEADER_FIELDS and not detail_context.get("last_successful_detail"):
        return "parser_improvement"
    # Header/status/fragment changes also need a previously material-backed fact.
    reliable = connection.execute("SELECT 1 FROM changes c JOIN source_materials m ON m.id=c.material_id WHERE c.opportunity_id=? AND c.field_name IN (?,'__record__') AND m.source_key=? AND m.acquisition_status='success' LIMIT 1", (old["id"], field, old["source_key"])).fetchone()
    return "official_change" if reliable else "parser_improvement"


def _sanitize_old_supplement(connection,row,old,context,timestamp):
    from backend.services.queries import _stored_evidence, _attachment_chain, _observations
    from backend.storage.database import DatabaseUnavailable
    _observations(row,connection)
    # Core remains strictly material-backed; only optional values are isolated.
    validate_candidate({**old,'roster_fragments':[],'job_fragments':[],'attachments':[]},
                       {'school_key':old['school_key'],'source_key':old['source_key']})
    damaged={}
    for field in ('roster_fragments','job_fragments','attachments'):
        kept=[];bad=[]
        values=old[field]
        if not isinstance(values,list) or len(values)>8: values=[{'_unreadable_json':row[field+'_json']}]
        for fragment in values:
            try:
                if not isinstance(fragment,dict) or not fragment.get('scope') or not fragment.get('evidence'): raise ValueError('附加内容无依据')
                _stored_evidence(fragment['evidence'],row,connection)
                if field=='attachments':
                    safe_url(fragment.get('url'),row['school_key'])
                    if not isinstance(fragment.get('label'),str) or not fragment['label'] or len(fragment['label'])>500: raise ValueError('附件标题无效')
                    _attachment_chain(fragment,row,connection)
                elif fragment['scope'] not in {'partial','complete_for_material','unknown'} or not isinstance(fragment.get('text'),str) or not fragment['text'] or len(fragment['text'])>2000:
                    raise ValueError('片段范围无效')
                kept.append(fragment)
            except (DatabaseUnavailable,ValueError,TypeError,KeyError):
                bad.append(fragment)
        if bad:
            damaged[field]=row[field+'_json']
            old[field]=kept
            for fragment in bad:
                original=encoded(fragment);digest=hashlib.sha256(original.encode()).hexdigest()
                connection.execute('INSERT OR IGNORE INTO quarantined_evidence(opportunity_id,field_name,input_hash,original_json,reason,recorded_at) VALUES (?,?,?,?,?,?)',
                                   (old['id'],field,digest,original,'stored_applicability_unverified',timestamp))
            save_task(connection,{'source_key':old['source_key']},task_kind='maintenance',task_identity='quarantine:'+str(old['id'])+':'+field,opportunity_id=old['id'],run_id=context.run_id,status='pending',result={'type':'material_applicability','field':field},attempted=False)
    return damaged


def _commit_candidate(connection, candidate, context, timestamp, *, task_kind, fallback_id, replace_fields=()):
    row = connection.execute(
        "SELECT * FROM opportunities WHERE source_key=? AND source_identity=?",
        (candidate["source_key"], candidate["source_identity"]),
    ).fetchone()
    old = _from_row(row) if row else None
    visibility = connection.execute("SELECT * FROM field_decisions WHERE opportunity_id=? AND field_name='__visibility__'", (row['id'],)).fetchone() if row else None
    reviving = bool(old and context.change_kind == 'automatic' and visibility and json.loads(visibility['value_json']) is False and _candidate_proofs(candidate))
    if context.base_version is not None and context.base_version != (row['version'] if row else 0):
        raise WriteConflict('公告版本已变化，请重新预览。')
    if replace_fields and (context.change_kind == 'automatic' or context.base_version is None):
        raise ValueError('定向替换必须有明确操作类型和基础版本。')
    damaged=_sanitize_old_supplement(connection,row,old,context,timestamp) if old else {}
    campus_key = candidate.pop("campus_key", None)
    candidate["campus_id"] = None
    if campus_key:
        campus = connection.execute(
            "SELECT id FROM campuses WHERE school_key=? AND campus_key=?", (candidate["school_key"], campus_key),
        ).fetchone()
        if campus is None:
            raise ValueError("校区没有同校官方归属登记。")
        candidate["campus_id"] = campus["id"]
    elif old and not reviving:
        candidate["campus_id"] = old["campus_id"]
    detail_context = _detail_context(connection, candidate)
    baseline = _revival_baseline(connection, row, old, candidate, visibility) if reviving else old
    current = _merge(baseline, candidate, task_kind=task_kind, list_title=detail_context['list_title'], replace_fields=replace_fields)
    if old and context.change_kind == 'automatic':
        for decision in connection.execute('SELECT field_name FROM field_decisions WHERE opportunity_id=?',(old['id'],)):
            field = decision['field_name']
            if field in BUSINESS_FIELDS and _semantic(current[field]) != _semantic(old[field]):
                save_task(connection, {'source_key':old['source_key']}, task_kind='maintenance', task_identity='manual-conflict:'+str(old['id'])+':'+field,
                          opportunity_id=old['id'], run_id=context.run_id, status='pending', result={'type':'manual_decision_conflict','field':field},attempted=False)
                current[field] = old[field]
                if field in CORE_FIELDS or field == 'relevance':
                    current['field_observations'][field] = old['field_observations'][field]
    changed = list(BUSINESS_FIELDS) if old is None else [field for field in BUSINESS_FIELDS if _semantic(old[field]) != _semantic(current[field])]
    changed += [field for field in damaged if field not in changed]
    if not changed and not reviving:
        return row["id"], "unchanged", []
    columns = [field + "_json" if field in JSON_FIELDS else field for field in BUSINESS_FIELDS]
    values = [encoded(current[field]) if field in JSON_FIELDS else current[field] for field in BUSINESS_FIELDS]
    if old is None:
        columns = ["school_key", "source_key", "source_identity", *columns, "first_seen_at", "content_changed_at"]
        values = [current["school_key"], current["source_key"], current["source_identity"], *values, timestamp, timestamp]
        cursor = connection.execute(f"INSERT INTO opportunities({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
        opportunity_id = cursor.lastrowid
        _associate(connection,current,opportunity_id,timestamp)
        for field in JSON_FIELDS:
            connection.execute('UPDATE opportunities SET '+field+'_json=? WHERE id=?',(encoded(current[field]),opportunity_id))
        connection.execute(
            "INSERT INTO changes(opportunity_id,field_name,after_json,change_kind,material_id,run_id,manual_operation_id,actor,committed_at,reason,write_context_key) VALUES (?,'__record__',?,?,?,?,?,?,?,?,?)",
            (opportunity_id, encoded({field: current[field] for field in BUSINESS_FIELDS}), 'newly_collected' if context.change_kind=='automatic' else context.change_kind, _material_for(current, 'published_date', fallback_id), context.run_id, context.operation_id, context.actor, timestamp, context.reason, context.key),
        )
        return opportunity_id, "new", changed
    opportunity_id = old['id']
    _associate(connection,current,opportunity_id,timestamp)
    values = [encoded(current[field]) if field in JSON_FIELDS else current[field] for field in BUSINESS_FIELDS]
    connection.execute(
        f"UPDATE opportunities SET {','.join(column + '=?' for column in columns)},content_changed_at=?,version=version+1 WHERE id=?",
        [*values, timestamp, opportunity_id],
    )
    if reviving:
        connection.execute("DELETE FROM field_decisions WHERE opportunity_id=? AND field_name='__visibility__'", (opportunity_id,))
        connection.execute("INSERT INTO changes(opportunity_id,field_name,before_json,after_json,change_kind,run_id,actor,committed_at,reason,write_context_key) VALUES (?,'__visibility__','false','true','parser_improvement',?,?,?,?,?)", (opportunity_id,context.run_id,context.actor,timestamp,context.reason,context.key))
    # Field state and value form one change; fetched time/hash alone are not facts.
    history_fields = [field for field in changed if field != "field_observations"]
    history_fields += [field for field in CORE_FIELDS if field not in history_fields and _semantic(old["field_observations"].get(field)) != _semantic(current["field_observations"].get(field))]
    for field in history_fields:
        before, after = old.get(field), current.get(field)
        kind = _change_kind(connection, old, current, field, task_kind=task_kind, detail_context=detail_context) if context.change_kind=='automatic' else context.change_kind
        if reviving: kind = 'parser_improvement'
        if field in damaged:
            try: before=json.loads(damaged[field])
            except (ValueError,TypeError): before={'unreadable_json':damaged[field]}
            if context.change_kind=='automatic': kind='evidence_conflict'
        if field in CORE_FIELDS:
            before_state = old["field_observations"].get(field, {}).get("state")
            after_state = current["field_observations"].get(field, {}).get("state")
            before = {"value": before, "state": before_state}
            after = {"value": after, "state": after_state}
        connection.execute(
            'INSERT INTO changes(opportunity_id,field_name,before_json,after_json,change_kind,material_id,run_id,manual_operation_id,actor,committed_at,reason,write_context_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (opportunity_id,field,encoded(before),encoded(after),kind,_material_for(current,field,fallback_id),context.run_id,context.operation_id,context.actor,timestamp,context.reason,context.key),
        )
    return opportunity_id, "modified", changed


def _candidate_proofs(candidate):
    proofs = []
    def visit(value):
        if isinstance(value,dict):
            if 'material_id' in value and 'association_id' in value or 'material_id' in value and 'locator' in value:
                proofs.append(value)
            for nested in value.values(): visit(nested)
        elif isinstance(value,list):
            for nested in value: visit(nested)
    visit(candidate)
    return proofs


def reliable_official_snapshot(field, snapshot):
    """Missing optional parser output is not an official deletion observation."""
    if not isinstance(snapshot,dict) or 'value' not in snapshot: return False
    value=snapshot['value']; observation=snapshot.get('observation')
    if field in CORE_FIELDS or field=='relevance':
        return isinstance(observation,dict) and observation.get('state') in {'known','not_disclosed','not_applicable','conflict'} and bool(observation.get('evidence'))
    if field in {'roster_fragments','job_fragments','attachments'}:
        return isinstance(value,list) and bool(value) and all(isinstance(item,dict) and item.get('evidence') for item in value)
    return field in BUSINESS_FIELDS and field!='field_observations' and value not in (None,[], '', 'unknown','not_applicable')


def _official_field_proofs(candidate, field, record_proofs):
    observation=candidate['field_observations'].get(field)
    if observation: return observation.get('evidence',[])
    if field in {'roster_fragments','job_fragments','attachments'}:
        return [proof for item in candidate[field] for proof in item['evidence']]
    if field=='campus_id': return candidate['field_observations'].get('event_venue',{}).get('evidence',[]) if candidate.get(field) else []
    if field=='work_locations_scope': return candidate['field_observations']['work_locations'].get('evidence',[]) if candidate['field_observations']['work_locations']['state']=='known' else []
    return record_proofs


def _revival_baseline(connection, row, old, candidate, marker):
    """A withdrawn manual contribution cannot be conservatively merged back in."""
    from backend.services.queries import _stored_evidence
    from backend.storage.database import DatabaseUnavailable
    baseline = deepcopy(candidate)
    withdrawn = connection.execute('SELECT committed_at FROM manual_operations WHERE id=?', (marker['operation_id'],)).fetchone()
    threshold = withdrawn['committed_at'] if withdrawn else marker['committed_at']
    for field in BUSINESS_FIELDS:
        if field == 'field_observations': continue
        for stored in connection.execute('SELECT snapshot_json,committed_at FROM official_observations WHERE opportunity_id=? AND field_name=? ORDER BY julianday(committed_at) DESC,id DESC', (row['id'],field)):
            try:
                if threshold and datetime.fromisoformat(stored['committed_at']) <= datetime.fromisoformat(threshold): continue
                snapshot=json.loads(stored['snapshot_json'])
                if not reliable_official_snapshot(field,snapshot): continue
                proofs=snapshot.get('evidence') or (snapshot.get('observation') or {}).get('evidence')
                if not proofs: continue
                _stored_evidence(proofs,row,connection)
                baseline[field]=snapshot['value']
                if field in CORE_FIELDS or field=='relevance': baseline['field_observations'][field]=snapshot['observation']
                break
            except (ValueError,TypeError,KeyError,DatabaseUnavailable): continue
    for decision in connection.execute('SELECT field_name FROM field_decisions WHERE opportunity_id=?', (row['id'],)):
        field=decision['field_name']
        if field in BUSINESS_FIELDS and field!='field_observations':
            baseline[field]=deepcopy(old[field])
            if field in CORE_FIELDS or field=='relevance': baseline['field_observations'][field]=deepcopy(old['field_observations'][field])
    return baseline


def save_task(connection, config, *, task_kind, task_identity, opportunity_id=None, run_id=None, cursor=None, status='committed', result=None, budget=None, attempted=True, next_eligible_at=None):
    timestamp = now()
    policy=queue_policy(config)
    if task_kind in {'detail','list'}:
        budget={**(budget or {}),'queue_policy':policy,'single_page_strategy':'alternate_head_tail'}
    if next_eligible_at is None and task_kind=='detail' and status!='restricted':
        minutes = policy['detail_recheck_hours']*60 if status=='committed' else policy['failure_backoff_minutes'] if status in {'failed','partial'} else 0
        next_eligible_at = (datetime.fromisoformat(timestamp)+timedelta(minutes=minutes)).isoformat()
    connection.execute(
        'INSERT INTO processing_tasks(source_key,opportunity_id,task_kind,task_identity,cursor_json,budget_json,attempts,status,run_id,result_json,committed_at,last_attempt_at,next_eligible_at,queued_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_key,task_identity,task_kind) DO UPDATE SET opportunity_id=excluded.opportunity_id,cursor_json=excluded.cursor_json,budget_json=excluded.budget_json,attempts=processing_tasks.attempts+excluded.attempts,status=excluded.status,run_id=excluded.run_id,result_json=excluded.result_json,committed_at=excluded.committed_at,last_attempt_at=CASE WHEN excluded.attempts>0 THEN excluded.last_attempt_at ELSE processing_tasks.last_attempt_at END,next_eligible_at=excluded.next_eligible_at',
        (config['source_key'],opportunity_id,task_kind,task_identity,encoded(cursor),encoded(budget or {}),int(attempted),status,run_id,encoded(result or {}),timestamp,timestamp if attempted else None,next_eligible_at,timestamp),
    )


def commit_facts_in_transaction(connection, metadata, source_config, candidates, materials, context, *, fixture=False, task_kind='detail', replace_fields=()):
    """The sole fact merge API. Caller owns writer_transaction; no nested lock.

    Candidates use adapter evidence references, never supplied DB IDs. Materials
    are archived references. Operations use operation_id, not fabricated runs.
    Receipt, facts, material associations, version, history and dataset commit or
    roll back together with the caller's operation/session bookkeeping.
    """
    if not connection.in_transaction or not isinstance(context,WriteContext):
        raise ValueError('事实提交必须位于共享写事务并携带WriteContext。')
    normalized = [validate_candidate(candidate,source_config) for candidate in candidates]
    prepared = _prepare_materials(materials,source_config,fixture)
    if set(replace_fields)-set(BUSINESS_FIELDS) or 'field_observations' in replace_fields:
        raise ValueError('定向修订字段无效。')
    request_hash = context_request_hash(context,{'source_key':source_config['source_key'],'candidates':normalized,'materials':prepared,'replace_fields':list(replace_fields),'fixture':fixture,'task_kind':task_kind})
    replay = begin_fact_write(connection,context,request_hash)
    if replay is not None:
        return {**replay,'replayed':True}
    assert_data_mode(metadata,fixture)
    _source(connection,source_config)
    _save_materials(connection,prepared)
    counts = {'new':0,'modified':0,'unchanged':0}
    ids = []
    timestamp = now()
    for candidate in normalized:
        successful = [m for m in prepared if m['acquisition_status']=='success' and m.get('official_record_id')==candidate['source_identity']]
        fallback = connection.execute('SELECT id FROM source_materials WHERE source_key=? AND reference_key=?',(source_config['source_key'],successful[-1]['reference_key'])).fetchone()[0] if successful else None
        bound = _bind_evidence(connection,candidate)
        opportunity_id,outcome,changed = _commit_candidate(connection,bound,context,timestamp,task_kind=task_kind,fallback_id=fallback,replace_fields=replace_fields)
        counts[outcome] += 1
        ids.append(opportunity_id)
        if context.change_kind=='automatic':
            _associate(connection,bound,opportunity_id,timestamp)
            record_proofs=_candidate_proofs(bound)
            for field in BUSINESS_FIELDS:
                if field=='field_observations': continue
                observation=bound['field_observations'].get(field)
                proofs=_official_field_proofs(bound,field,record_proofs)
                snapshot={'value':bound.get(field),'observation':observation,'evidence':proofs}
                if not reliable_official_snapshot(field,snapshot): continue
                value_hash=hashlib.sha256(encoded(_semantic(snapshot)).encode()).hexdigest()
                for proof in proofs:
                    connection.execute('INSERT OR IGNORE INTO official_observations(opportunity_id,field_name,material_id,association_id,value_hash,snapshot_json,parser_version,observed_at,committed_at,run_id,actor,write_context_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                       (opportunity_id,field,proof['material_id'],proof['association_id'],value_hash,encoded(snapshot),proof['parser_version'],proof['observed_at'],timestamp,context.run_id,context.actor,context.key))
        for m in successful:
            connection.execute('UPDATE source_materials SET opportunity_id=? WHERE source_key=? AND reference_key=? AND opportunity_id IS NULL',(opportunity_id,source_config['source_key'],m['reference_key']))
        if context.operation_id and context.change_kind in {'manual_correction','semantic_revision','manual_supplement'}:
            for field in replace_fields:
                stored_observations=json.loads(connection.execute('SELECT field_observations_json FROM opportunities WHERE id=?',(opportunity_id,)).fetchone()[0])
                proof=stored_observations.get(field,{}).get('evidence',[])
                connection.execute('INSERT INTO field_decisions(opportunity_id,field_name,operation_id,value_json,evidence_json,base_version,committed_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(opportunity_id,field_name) DO UPDATE SET operation_id=excluded.operation_id,value_json=excluded.value_json,evidence_json=excluded.evidence_json,base_version=excluded.base_version,committed_at=excluded.committed_at',
                                   (opportunity_id,field,context.operation_id,encoded(bound[field]),encoded(proof),context.base_version or 0,timestamp))
    if counts['new'] or counts['modified']:
        metadata['dataset_id'] = ('fixture-ds-' if fixture else 'ds-')+str(uuid4())
        connection.execute("UPDATE metadata SET value=? WHERE key='dataset_id'",(metadata['dataset_id'],))
        if not fixture:
            metadata['data_mode']='real'
            connection.execute("UPDATE metadata SET value='real' WHERE key='data_mode'")
    receipt = {**counts,'opportunity_ids':ids,'dataset_id':metadata['dataset_id'],'context_key':context.key,'committed_at':timestamp}
    finish_fact_write(connection,context,request_hash,receipt,timestamp)
    return receipt


def commit_facts(database_path, source_config, candidates, materials, context, **kwargs):
    with writer_transaction(database_path) as (connection,metadata):
        return commit_facts_in_transaction(connection,metadata,source_config,candidates,materials,context,**kwargs)


def ingest_page(database_path, source_config, candidates, materials, *, run_id, cursor=None, next_cursor=None, complete=False, fixture=False, budget=None, task_kind='list', queue_state=None):
    identity = hashlib.sha256(encoded({'candidates':candidates,'materials':materials,'cursor':cursor,'task_kind':task_kind}).encode()).hexdigest()
    context = WriteContext(actor='worker',run_id=run_id,reason='公开'+('列表发现' if task_kind=='list' else '详情复核'),idempotency_key=identity)
    with writer_transaction(database_path) as (connection,metadata):
        receipt = commit_facts_in_transaction(connection,metadata,source_config,candidates,materials,context,fixture=fixture,task_kind=task_kind)
        if receipt.get('replayed'):
            return receipt
        timestamp = receipt['committed_at']
        for candidate,opportunity_id in zip(candidates,receipt['opportunity_ids']):
            detail_context = _detail_context(connection,candidate)
            if task_kind=='detail':
                partial = any(item.get('parsing_status')=='partial' for item in materials)
                result = {**detail_context,'candidate':deepcopy(candidate),'outcome':'partial' if partial else 'committed',
                          'last_successful_detail':{'run_id':run_id,'committed_at':timestamp}}
                save_task(connection,source_config,task_kind='detail',task_identity='detail:'+candidate['source_identity'],opportunity_id=opportunity_id,run_id=run_id,status='partial' if partial else 'committed',result=result,budget=budget)
            else:
                pending = connection.execute("SELECT * FROM processing_tasks WHERE source_key=? AND task_identity=? AND task_kind='detail'",(source_config['source_key'],'detail:'+candidate['source_identity'])).fetchone()
                if pending is None:
                    save_task(connection,source_config,task_kind='detail',task_identity='detail:'+candidate['source_identity'],opportunity_id=opportunity_id,run_id=run_id,status='pending',result={**detail_context,'list_title':candidate['title'],'candidate':candidate},budget=budget,attempted=False)
                else:
                    # Rediscovery neither requeues a committed detail nor resets
                    # failure backoff/arrival order. Keep its last usable input.
                    result = json.loads(pending['result_json'] or '{}')
                    result['list_title']=candidate['title']
                    result.setdefault('candidate',candidate)
                    connection.execute('UPDATE processing_tasks SET result_json=? WHERE id=?',(encoded(result),pending['id']))
        if task_kind=='list':
            parsing_failed = any(m.get('parsing_status')=='failed' for m in materials)
            if parsing_failed:
                raise ValueError('列表正文未可靠解析，不能记为成功检查。')
            counts = {k:receipt[k] for k in ('new','modified','unchanged')}
            save_task(connection,source_config,task_kind='list',task_identity='list:'+source_config['channel_key'],run_id=run_id,cursor=next_cursor,status='complete' if complete else 'partial',result={**counts,'last_cursor':cursor,**(queue_state or {})},budget=budget)
            connection.execute('UPDATE sources SET status=?,last_attempt_at=?,last_success_at=?,public_message=? WHERE source_key=?',('success' if complete else 'partial',timestamp,timestamp,'已检查本栏目公开范围' if complete else '已取得部分公开列表，范围尚未完整',source_config['source_key']))
        run = connection.execute('SELECT result_json FROM runs WHERE id=?',(run_id,)).fetchone()
        progress = json.loads(run['result_json'])
        totals = progress.setdefault('commits',{'new':0,'modified':0,'unchanged':0})
        for key in totals: totals[key]+=receipt[key]
        if task_kind=='list': progress['pages']=progress.get('pages',0)+1
        connection.execute('UPDATE runs SET result_json=?,committed_at=? WHERE id=?',(encoded(progress),timestamp,run_id))
        return receipt


def ingest_detail(database_path, source_config, candidate, materials, *, run_id, fixture=False, budget=None):
    return ingest_page(database_path, source_config, [candidate], materials, run_id=run_id, fixture=fixture, budget=budget, task_kind="detail")


def record_detail_failure(database_path, source_config, candidate, materials, *, run_id, status="failed", fixture=False, budget=None):
    prepared = _prepare_materials(materials, source_config, fixture)
    with writer_transaction(database_path) as (connection, metadata):
        assert_data_mode(metadata, fixture)
        _source(connection, source_config)
        _save_materials(connection, prepared)
        row = connection.execute("SELECT id FROM opportunities WHERE source_key=? AND source_identity=?", (source_config["source_key"], candidate["source_identity"])).fetchone()
        if row is None:
            raise ValueError("详情失败只能登记已经提交的基础机会。")
        save_task(connection, source_config, task_kind="detail", task_identity="detail:" + candidate["source_identity"], opportunity_id=row["id"], run_id=run_id, status=status, result={**_detail_context(connection, candidate), "reason": status, "candidate": candidate}, budget=budget)
