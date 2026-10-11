"""Bounded list-first refreshes with resumable commits and source isolation."""

from copy import deepcopy
import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from backend.domain.candidates import safe_url
from backend.services.ingestion import (
    _prepare_materials, _save_materials, _source, assert_data_mode, encoded, ingest_detail, ingest_page, now,
    record_detail_failure, save_task,
)
from backend.storage.database import read_database
from backend.storage.write import refresh_lock, writer_transaction


def register_sources(database_path, schools_config, fixture=False):
    """Explicitly register the observed two-school configuration, never the other eight."""
    schools = schools_config["schools"] if isinstance(schools_config, dict) else schools_config
    selected = [school for school in schools if school["school_key"] in {"scut", "gdut"}]
    if {school["school_key"] for school in selected} != {"scut", "gdut"} or len(selected) != 2:
        raise ValueError("来源登记必须包含已确认的华工和广工各一项。")
    sources = []
    with writer_transaction(database_path) as (connection, metadata):
        assert_data_mode(metadata, fixture)
        for school in selected:
            key = school["school_key"]
            safe_url(school["official_owner_evidence_url"], key)
            connection.execute("UPDATE schools SET verification_state=?,verified_at=?,official_owner_evidence_url=?,scope_note=? WHERE school_key=?", (school["verification_state"], school["verified_at"], school["official_owner_evidence_url"], school.get("scope_note"), key))
            for campus in school.get("campuses", []):
                safe_url(campus["evidence_url"], key)
                existing = connection.execute("SELECT name FROM campuses WHERE school_key=? AND campus_key=?", (key, campus["campus_key"])).fetchone()
                if existing and existing["name"] != campus["name"]:
                    raise ValueError("已有校区名称变更须先核对受影响的机会投影。")
                connection.execute("INSERT INTO campuses(school_key,campus_key,name,evidence_url,observed_at) VALUES (?,?,?,?,?) ON CONFLICT(school_key,campus_key) DO UPDATE SET evidence_url=excluded.evidence_url,observed_at=excluded.observed_at", (key, campus["campus_key"], campus["name"], campus["evidence_url"], campus["observed_at"]))
            observation = school.get("seed_observation", {})
            if observation:
                connection.execute("UPDATE sources SET verification_state=?,status=?,last_attempt_at=?,public_message=? WHERE source_key=?", ("restricted" if observation["status"] == "restricted" else "verified", observation["status"], observation["observed_at"], observation["message"], key + "_homepage"))
            for config in school.get("sources", []):
                if config["school_key"] != key:
                    raise ValueError("来源登记不能跨学校。")
                safe_url(config["official_entry_url"], key)
                previous = connection.execute("SELECT school_key,channel_key FROM sources WHERE source_key=?", (config["source_key"],)).fetchone()
                if previous and (previous["school_key"] != key or previous["channel_key"] != config["channel_key"]):
                    raise ValueError("已有来源不能改变学校或栏目身份。")
                connection.execute("INSERT INTO sources(source_key,school_key,name,channel_key,official_entry_url,adapter,scope_json,verification_state) VALUES (?,?,?,?,?,?,?,'verified') ON CONFLICT(source_key) DO UPDATE SET name=excluded.name,official_entry_url=excluded.official_entry_url,adapter=excluded.adapter,scope_json=excluded.scope_json,verification_state=excluded.verification_state", (config["source_key"], key, config["name"], config["channel_key"], config["official_entry_url"], config["adapter"], encoded(config["scope"])))
                sources.append({**deepcopy(config), "campuses": deepcopy(school.get("campuses", []))})
        if {item["source_key"] for item in sources} != {"scut_cnsba", "gdut_teachin", "gdut_jobfair", "gdut_campus"} or len(sources) != 4:
            raise ValueError("本轮只登记已核验的四个公开栏目。")
    return sources


def _failure_material(error, config, run_id):
    raw = getattr(error, "material_ref", None)
    status = "restricted" if getattr(error, "restricted", False) else "failed"
    if raw:
        return [{
            "source_key": config["source_key"], "reference_key": raw["reference_key"],
            "source_url": raw["url"], "material_hash": raw["material_hash"],
            "fetched_at": raw["fetched_at"], "raw_reference": raw["raw_reference"],
            "acquisition_status": status, "parsing_status": "not_attempted",
            "parser_version": "not_attempted", "scope": config.get("scope", {}),
        }]
    return [{
        "source_key": config["source_key"],
        "reference_key": hashlib.sha256((run_id + config["source_key"] + now()).encode()).hexdigest(),
        "source_url": config["official_entry_url"], "fetched_at": now(),
        "acquisition_status": status, "parsing_status": "not_attempted",
        "parser_version": "not_attempted", "scope": config.get("scope", {}),
    }]


def _source_status(database_path, config, status, *, message, fixture):
    with writer_transaction(database_path) as (connection, metadata):
        assert_data_mode(metadata, fixture)
        _source(connection, config)
        connection.execute("UPDATE sources SET status=?,last_attempt_at=?,public_message=? WHERE source_key=?", (status, now(), message, config["source_key"]))


def _pending_details(database_path, config, run_id, retry_failed=False):
    with read_database(database_path) as (connection, _):
        statuses = "('pending','failed','partial')" if retry_failed else "('pending')"
        rows = connection.execute(f"SELECT result_json FROM processing_tasks WHERE source_key=? AND task_kind='detail' AND run_id=? AND status IN {statuses} ORDER BY id", (config["source_key"], run_id)).fetchall()
        return [json.loads(row["result_json"])["candidate"] for row in rows]


def _detail_states(database_path, config, run_id):
    with read_database(database_path) as (connection, _):
        return dict(connection.execute("SELECT status,COUNT(*) FROM processing_tasks WHERE source_key=? AND task_kind='detail' AND run_id=? GROUP BY status", (config["source_key"], run_id)))


def _cursor(database_path, config, run_id):
    with read_database(database_path) as (connection, _):
        row = connection.execute("SELECT cursor_json,status FROM processing_tasks WHERE source_key=? AND task_kind='list' AND run_id=?", (config["source_key"], run_id)).fetchone()
        return (json.loads(row["cursor_json"]), row["status"] == "complete") if row else (None, False)


def _finish(database_path, run_id, summary, status):
    with writer_transaction(database_path) as (connection, _):
        progress = json.loads(connection.execute("SELECT result_json FROM runs WHERE id=?", (run_id,)).fetchone()[0])
        if status == "partial" and progress.get("pages", 0) == 0 and all(item["status"] in {"failed", "restricted"} for item in summary["sources"]):
            status = "failed"
        summary = {**summary, "status": status, "pages": progress.get("pages", 0), "commits": progress.get("commits", {"new": 0, "modified": 0, "unchanged": 0})}
        connection.execute("UPDATE runs SET finished_at=?,status=?,completeness=?,result_json=?,committed_at=? WHERE id=?", (now(), status, "complete_for_selected_channels" if status == "complete" else "partial", encoded(summary), now(), run_id))
        return summary


def refresh_sources(database_path, source_configs, adapters=None, transport=None, *, school_keys=("scut", "gdut"), page_budget=2, detail_budget=20, fixture=False, resume_run_id=None, trigger="manual"):
    """Refresh only registered sources in the two-school scope; never migrate/init.

    Adapter and transport factories receive source_config. A fresh transport per
    source gives each channel its own request/time budget and closes owned clients.
    """
    from backend.sources import FetchError, Fetcher, get_adapter

    if not 1 <= page_budget <= 10 or not 0 <= detail_budget <= 100:
        raise ValueError("列表预算为 1—10 页，核心详情预算为 0—100 条。")
    if not school_keys or not set(school_keys).issubset({"scut", "gdut"}):
        raise ValueError("本轮真实刷新仅允许华南理工与广东工业。")
    configs = [deepcopy(config) for config in source_configs if config["school_key"] in school_keys]
    if not configs or len({config["source_key"] for config in configs}) != len(configs):
        raise ValueError("刷新需要非重复的已登记来源。")
    scope = {"school_keys": list(school_keys), "source_keys": [config["source_key"] for config in configs], "page_budget": page_budget, "detail_budget": detail_budget, "fixture": fixture}
    run_id = resume_run_id or "run-" + str(uuid4())
    with refresh_lock(database_path):
        with writer_transaction(database_path) as (connection, metadata):
            assert_data_mode(metadata, fixture)
            for config in configs:
                _source(connection, config)
            if resume_run_id:
                run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                if run is None or run["status"] == "complete":
                    raise ValueError("续跑轮次不存在或已经完成。")
                previous_scope = json.loads(run["scope_json"])
                if previous_scope["source_keys"] != scope["source_keys"] or previous_scope["fixture"] != fixture:
                    raise ValueError("续跑不能改变原轮次来源或样例身份。")
                connection.execute("UPDATE runs SET status='running',finished_at=NULL WHERE id=?", (run_id,))
            else:
                connection.execute("INSERT INTO runs(id,trigger,started_at,status,scope_json,result_json) VALUES (?,?,?,'running',?,'{}')", (run_id, trigger, now(), encoded(scope)))
        summary = {"run_id": run_id, "scope": scope, "sources": [], "status": "partial"}
        try:
            for config in configs:
                outcome = {"source_key": config["source_key"], "pages": 0, "details": 0, "detail_failures": 0, "restricted_details": 0, "status": "partial", "warnings": [], "next_cursor": None}
                summary["sources"].append(outcome)
                if adapters is None:
                    adapter = get_adapter(config)
                elif callable(adapters):
                    adapter = adapters(config)
                else:
                    adapter = adapters.get(config.get("adapter"), adapters.get(config["source_key"]))
                fetcher = transport(config) if callable(transport) else transport if transport is not None else Fetcher(max_requests=max(3, page_budget * 3 + detail_budget * 3))
                owns_fetcher = transport is None or callable(transport)
                remaining_details = detail_budget
                cursor, complete = _cursor(database_path, config, run_id)
                seen_cursors = set()
                restricted_patterns = set()
                attempted_details = set()
                phase = "detail"

                def details():
                    nonlocal remaining_details
                    for candidate in _pending_details(database_path, config, run_id, retry_failed=bool(resume_run_id)):
                        if candidate["source_identity"] in attempted_details:
                            continue
                        attempted_details.add(candidate["source_identity"])
                        pattern = re.sub(r"\d+", "{record}", urlsplit(candidate["source_url"]).path)
                        if pattern in restricted_patterns:
                            record_detail_failure(database_path, config, candidate, [], run_id=run_id, status="restricted", fixture=fixture)
                            outcome["restricted_details"] += 1
                            continue
                        if remaining_details == 0:
                            return
                        remaining_details -= 1
                        outcome["details"] += 1
                        try:
                            result = adapter.enrich(deepcopy(candidate), fetcher)
                            if any(item.get("parsing_status") == "failed" for item in result.get("material_refs", [])):
                                record_detail_failure(database_path, config, candidate, result.get("material_refs", []), run_id=run_id, fixture=fixture, budget={"detail_budget": detail_budget})
                                outcome["warnings"].extend(result.get("warnings", []))
                                continue
                            patch = result.get("patch", {})
                            enriched = {**candidate, **patch}
                            enriched["field_observations"] = {**candidate.get("field_observations", {}), **patch.get("field_observations", {})}
                            ingest_detail(database_path, config, enriched, result.get("material_refs", []), run_id=run_id, fixture=fixture, budget={"detail_budget": detail_budget})
                            outcome["warnings"].extend(result.get("warnings", []))
                        except FetchError as error:
                            status = "restricted" if error.restricted else "pending" if error.status == "budget_exhausted" else "failed"
                            record_detail_failure(database_path, config, candidate, _failure_material(error, config, run_id), run_id=run_id, status=status, fixture=fixture, budget={"detail_budget": detail_budget})
                            outcome["warnings"].append({"code": error.status, "layer": "detail"})
                            if error.restricted:
                                restricted_patterns.add(pattern)
                                outcome["restricted_details"] += 1
                            else:
                                outcome["detail_failures"] += 1
                            # Single detail failures retain the list-first flow. A
                            # restricted pattern is stopped while its public list
                            # remains independently readable; budget ends this source.
                            if error.status == "budget_exhausted":
                                raise

                try:
                    _source_status(database_path, config, "checking", message="正在检查公开来源", fixture=fixture)
                    details()
                    for _ in range(page_budget):
                        if complete:
                            break
                        marker = encoded(cursor)
                        if marker in seen_cursors:
                            outcome["warnings"].append({"code": "repeated_cursor", "layer": "list"})
                            break
                        seen_cursors.add(marker)
                        # There is deliberately no SQLite connection around network calls.
                        phase = "list"
                        page = adapter.discover(config, fetcher, cursor)
                        if page["source_key"] != config["source_key"] or page["channel_key"] != config["channel_key"]:
                            raise ValueError("适配器输出来源或栏目不匹配。")
                        next_cursor = page.get("next_cursor")
                        complete = page.get("completeness") == "complete_for_channel" and next_cursor is None
                        ingest_page(database_path, config, page["records"], page.get("material_refs", []), run_id=run_id, cursor=cursor, next_cursor=next_cursor, complete=complete, fixture=fixture, budget={"page_budget": page_budget, "detail_budget": detail_budget})
                        outcome["pages"] += 1
                        outcome["warnings"].extend(page.get("warnings", []))
                        outcome["next_cursor"] = next_cursor
                        phase = "detail"
                        details()
                        if next_cursor is None:
                            break
                        cursor = next_cursor
                    states = _detail_states(database_path, config, run_id)
                    pending = states.get("pending", 0) + states.get("partial", 0)
                    outcome["pending_details"] = pending
                    outcome["detail_failures"] = states.get("failed", 0)
                    outcome["restricted_details"] = states.get("restricted", 0)
                    outcome["status"] = "complete" if complete and not (pending or outcome["detail_failures"] or outcome["restricted_details"]) else "partial"
                    _source_status(database_path, config, "success" if outcome["status"] == "complete" else "partial", message="已完成本轮登记栏目范围" if outcome["status"] == "complete" else "已取得部分公开材料，尚有未完成范围", fixture=fixture)
                except FetchError as error:
                    status = "restricted" if error.restricted else "partial" if error.status == "budget_exhausted" else "failed"
                    outcome["status"] = status
                    outcome["warnings"].append({"code": error.status, "layer": "source"})
                    with writer_transaction(database_path) as (connection, _):
                        _save_materials(connection, _prepare_materials(_failure_material(error, config, run_id), config, fixture))
                        if phase == "list":
                            save_task(connection, config, task_kind="list", task_identity="list:" + config["channel_key"], run_id=run_id, cursor=outcome["next_cursor"] or cursor, status=status, result={"reason": error.status}, budget={"page_budget": page_budget})
                    _source_status(database_path, config, status, message="公开路径受限，已停止该路径" if status == "restricted" else "本轮来源检查未完成，已保留此前取得内容", fixture=fixture)
                except ValueError:
                    outcome["status"] = "failed"
                    outcome["warnings"].append({"code": "invalid_source_output", "layer": "validation"})
                    _source_status(database_path, config, "failed", message="来源结果未通过事实和证据校验，已保留此前内容", fixture=fixture)
                finally:
                    if owns_fetcher:
                        fetcher.close()
            status = "complete" if all(item["status"] == "complete" for item in summary["sources"]) else "partial"
            summary["status"] = status
            return _finish(database_path, run_id, summary, status)
        except BaseException:
            summary["status"] = "interrupted"
            _finish(database_path, run_id, summary, "interrupted")
            raise
