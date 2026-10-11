"""One evidence-aware write service for list, detail and future maintenance inputs."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from backend.config import ROOT
from backend.domain.candidates import CORE_FIELDS, safe_url, validate_candidate
from backend.storage.write import writer_transaction


BUSINESS_FIELDS = (
    "campus_id", "title", "kind", "original_kind", "date_basis", "source_url",
    *CORE_FIELDS, "work_locations_scope", "relevance", "event_status",
    "recruitment_status", "source_updated_at", "field_observations",
    "roster_fragments", "job_fragments", "attachments",
)
JSON_FIELDS = {"work_locations", "field_observations", "roster_fragments", "job_fragments", "attachments"}
DETAIL_HEADER_FIELDS = {"title", "kind", "original_kind", "date_basis"}


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
            if previous["source_url"] != item["source_url"] or previous["material_hash"] != item.get("material_hash"):
                raise ValueError("已有材料引用不能指向不同 URL 或内容。")
            continue
        connection.execute(
            "INSERT INTO source_materials(source_key,reference_key,source_url,official_record_id,material_hash,fetched_at,raw_reference,acquisition_status,parsing_status,parser_version,scope_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item["source_key"], item["reference_key"], item["source_url"], item.get("official_record_id"),
             item.get("material_hash"), item.get("fetched_at"), item.get("raw_reference"),
             item["acquisition_status"], item["parsing_status"], item.get("parser_version"), encoded(item.get("scope", {}))),
        )


def _bind_evidence(connection, candidate):
    result = deepcopy(candidate)

    def visit(value):
        if isinstance(value, dict):
            if "material_ref" in value:
                row = connection.execute(
                    "SELECT id,source_url,acquisition_status FROM source_materials WHERE source_key=? AND reference_key=?",
                    (candidate["source_key"], value["material_ref"]),
                ).fetchone()
                if row is None or row["acquisition_status"] != "success" or row["source_url"] != value.get("source_url"):
                    raise ValueError("字段证据必须绑定同源实际成功材料，URL 不能错配。")
                value["material_id"] = row["id"]
                del value["material_ref"]
            elif "material_id" in value:
                raise ValueError("来源候选不能自造数据库材料 ID。")
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(result)
    return result


def _semantic(value):
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if key not in {"evidence", "observed_at", "parser_version"}}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def _from_row(row):
    result = dict(row)
    for field in JSON_FIELDS:
        result[field] = json.loads(result.pop(field + "_json"))
    return result


def _merge(old, candidate, *, task_kind, list_title=None):
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


def _commit_candidate(connection, candidate, run_id, timestamp, *, task_kind, fallback_id):
    row = connection.execute(
        "SELECT * FROM opportunities WHERE source_key=? AND source_identity=?",
        (candidate["source_key"], candidate["source_identity"]),
    ).fetchone()
    old = _from_row(row) if row else None
    campus_key = candidate.pop("campus_key", None)
    candidate["campus_id"] = None
    if campus_key:
        campus = connection.execute(
            "SELECT id FROM campuses WHERE school_key=? AND campus_key=?", (candidate["school_key"], campus_key),
        ).fetchone()
        if campus is None:
            raise ValueError("校区没有同校官方归属登记。")
        candidate["campus_id"] = campus["id"]
    elif old:
        candidate["campus_id"] = old["campus_id"]
    detail_context = _detail_context(connection, candidate)
    current = _merge(old, candidate, task_kind=task_kind, list_title=detail_context["list_title"])
    changed = list(BUSINESS_FIELDS) if old is None else [field for field in BUSINESS_FIELDS if _semantic(old[field]) != _semantic(current[field])]
    if not changed:
        return row["id"], "unchanged", []
    columns = [field + "_json" if field in JSON_FIELDS else field for field in BUSINESS_FIELDS]
    values = [encoded(current[field]) if field in JSON_FIELDS else current[field] for field in BUSINESS_FIELDS]
    if old is None:
        columns = ["school_key", "source_key", "source_identity", *columns, "first_seen_at", "content_changed_at"]
        values = [current["school_key"], current["source_key"], current["source_identity"], *values, timestamp, timestamp]
        cursor = connection.execute(f"INSERT INTO opportunities({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
        opportunity_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO changes(opportunity_id,field_name,after_json,change_kind,material_id,run_id,actor,committed_at) VALUES (?,'__record__',?,'newly_collected',?,?,'worker',?)",
            (opportunity_id, encoded({field: current[field] for field in BUSINESS_FIELDS}), _material_for(current, "published_date", fallback_id), run_id, timestamp),
        )
        return opportunity_id, "new", changed
    opportunity_id = old["id"]
    connection.execute(
        f"UPDATE opportunities SET {','.join(column + '=?' for column in columns)},content_changed_at=?,version=version+1 WHERE id=?",
        [*values, timestamp, opportunity_id],
    )
    # Field state and value form one change; fetched time/hash alone are not facts.
    history_fields = [field for field in changed if field != "field_observations"]
    history_fields += [field for field in CORE_FIELDS if field not in history_fields and _semantic(old["field_observations"].get(field)) != _semantic(current["field_observations"].get(field))]
    for field in history_fields:
        before, after = old.get(field), current.get(field)
        kind = _change_kind(connection, old, current, field, task_kind=task_kind, detail_context=detail_context)
        if field in CORE_FIELDS:
            before_state = old["field_observations"].get(field, {}).get("state")
            after_state = current["field_observations"].get(field, {}).get("state")
            before = {"value": before, "state": before_state}
            after = {"value": after, "state": after_state}
        connection.execute(
            "INSERT INTO changes(opportunity_id,field_name,before_json,after_json,change_kind,material_id,run_id,actor,committed_at) VALUES (?,?,?,?,?,?,?,'worker',?)",
            (opportunity_id, field, encoded(before), encoded(after), kind, _material_for(current, field, fallback_id), run_id, timestamp),
        )
    return opportunity_id, "modified", changed


def save_task(connection, config, *, task_kind, task_identity, opportunity_id=None, run_id, cursor=None, status="committed", result=None, budget=None, attempted=True):
    connection.execute(
        "INSERT INTO processing_tasks(source_key,opportunity_id,task_kind,task_identity,cursor_json,budget_json,attempts,status,run_id,result_json,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_key,task_identity,task_kind) DO UPDATE SET opportunity_id=excluded.opportunity_id,cursor_json=excluded.cursor_json,budget_json=excluded.budget_json,attempts=processing_tasks.attempts+excluded.attempts,status=excluded.status,run_id=excluded.run_id,result_json=excluded.result_json,committed_at=excluded.committed_at",
        (config["source_key"], opportunity_id, task_kind, task_identity, encoded(cursor), encoded(budget or {}), int(attempted), status, run_id, encoded(result or {}), now()),
    )


def ingest_page(database_path, source_config, candidates, materials, *, run_id, cursor=None, next_cursor=None, complete=False, fixture=False, budget=None, task_kind="list"):
    normalized = [validate_candidate(candidate, source_config) for candidate in candidates]
    prepared = _prepare_materials(materials, source_config, fixture)
    counts = {"new": 0, "modified": 0, "unchanged": 0}
    ids = []
    timestamp = now()
    with writer_transaction(database_path) as (connection, metadata):
        assert_data_mode(metadata, fixture)
        _source(connection, source_config)
        _save_materials(connection, prepared)
        successful = [item for item in prepared if item["acquisition_status"] == "success"]
        fallback_id = connection.execute("SELECT id FROM source_materials WHERE source_key=? AND reference_key=?", (source_config["source_key"], successful[-1]["reference_key"])).fetchone()[0] if successful else None
        for candidate in normalized:
            detail_context = _detail_context(connection, candidate)
            opportunity_id, outcome, _ = _commit_candidate(connection, _bind_evidence(connection, candidate), run_id, timestamp, task_kind=task_kind, fallback_id=fallback_id)
            counts[outcome] += 1
            ids.append(opportunity_id)
            if task_kind == "detail":
                partial = any(item["parsing_status"] == "partial" for item in prepared)
                result = {**detail_context, "outcome": outcome}
                if successful:
                    result["last_successful_detail"] = {"run_id": run_id, "material_id": fallback_id, "committed_at": timestamp}
                if partial:
                    result["candidate"] = candidate
                save_task(connection, source_config, task_kind="detail", task_identity="detail:" + candidate["source_identity"], opportunity_id=opportunity_id, run_id=run_id, status="partial" if partial else "committed", result=result, budget=budget)
                for item in prepared:
                    if item.get("official_record_id") == candidate["source_identity"]:
                        connection.execute("UPDATE source_materials SET opportunity_id=? WHERE source_key=? AND reference_key=? AND opportunity_id IS NULL", (opportunity_id, source_config["source_key"], item["reference_key"]))
            else:
                # The list commit also preserves the resumable, not-yet-fetched detail input.
                pending = connection.execute("SELECT run_id,status FROM processing_tasks WHERE source_key=? AND task_identity=? AND task_kind='detail'", (source_config["source_key"], "detail:" + candidate["source_identity"])).fetchone()
                if pending is None or pending["run_id"] != run_id:
                    save_task(connection, source_config, task_kind="detail", task_identity="detail:" + candidate["source_identity"], opportunity_id=opportunity_id, run_id=run_id, status="restricted" if pending and pending["status"] == "restricted" else "pending", result={**detail_context, "list_title": candidate["title"], "candidate": candidate}, budget=budget, attempted=False)
        if task_kind == "list":
            save_task(connection, source_config, task_kind="list", task_identity="list:" + source_config["channel_key"], run_id=run_id, cursor=next_cursor, status="complete" if complete else "partial", result={**counts, "last_cursor": cursor}, budget=budget)
            connection.execute("UPDATE sources SET status=?,last_attempt_at=?,last_success_at=?,public_message=? WHERE source_key=?", ("success" if complete else "partial", timestamp, timestamp, "已检查本栏目公开范围" if complete else "已取得部分公开列表，范围尚未完整", source_config["source_key"]))
        if counts["new"] or counts["modified"]:
            metadata["dataset_id"] = ("fixture-ds-" if fixture else "ds-") + str(uuid4())
            connection.execute("UPDATE metadata SET value=? WHERE key='dataset_id'", (metadata["dataset_id"],))
            if not fixture:
                connection.execute("UPDATE metadata SET value='real' WHERE key='data_mode'")
        run = connection.execute("SELECT result_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("写入必须绑定已登记采集轮次。")
        progress = json.loads(run["result_json"])
        totals = progress.setdefault("commits", {"new": 0, "modified": 0, "unchanged": 0})
        for key, count in counts.items():
            totals[key] += count
        if task_kind == "list":
            progress["pages"] = progress.get("pages", 0) + 1
        connection.execute("UPDATE runs SET result_json=?,committed_at=? WHERE id=?", (encoded(progress), timestamp, run_id))
        return {**counts, "opportunity_ids": ids, "dataset_id": metadata["dataset_id"]}


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
