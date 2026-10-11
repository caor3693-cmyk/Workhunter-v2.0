"""Synthetic inputs exercise the real write service, never official coverage."""

from copy import deepcopy
import hashlib
import json

import pytest

from backend.domain.candidates import CORE_FIELDS
from backend.services.ingestion import ingest_detail, ingest_page, now, record_detail_failure
from backend.storage.database import initialize_database, read_database
from backend.storage.write import writer_transaction


def source(school="scut"):
    origin = "https://jyzx.scut.edu.cn" if school == "scut" else "https://career.gdut.edu.cn"
    return {"source_key": school + "_homepage", "school_key": school, "channel_key": "homepage", "official_entry_url": origin + "/", "adapter": "fixture", "scope": {"coverage": "isolated_fixture"}}


def material(config, key="list-1"):
    return {"source_key": config["source_key"], "reference_key": key, "source_url": config["official_entry_url"] + "notice/42", "material_hash": hashlib.sha256(key.encode()).hexdigest(), "fetched_at": "2026-10-11T10:00:00+08:00", "raw_reference": "isolated_fixture/" + key, "acquisition_status": "success", "parsing_status": "success", "parser_version": "fixture-1", "scope": {"coverage": "isolated_fixture"}}


def candidate(config, archive, *, identity="official-42"):
    item = {"source_key": config["source_key"], "school_key": config["school_key"], "source_identity": identity, "title": "隔离反例宣讲", "kind": "campus_talk", "original_kind": "宣讲会", "date_basis": "event", "source_url": archive["source_url"], "published_date": "2026-10-10", "event_date": "2026-10-20", "start_time": "14:30", "end_time": "16:00", "deadline": None, "event_venue": "官方本场教室", "work_locations": [], "work_locations_scope": "this_announcement", "relevance": "unknown", "event_status": "unknown", "recruitment_status": "unknown", "source_updated_at": None, "campus_key": None, "roster_fragments": [], "job_fragments": [], "attachments": []}
    item["field_observations"] = {}
    for field in CORE_FIELDS:
        value = item[field]
        item["field_observations"][field] = {"state": "known" if value else "not_collected", "value": value if value else None, "evidence": [{"material_ref": archive["reference_key"], "source_url": archive["source_url"], "excerpt": "隔离样例：" + str(value), "locator": "fixture:" + field, "scope": "this_announcement", "observed_at": archive["fetched_at"], "parser_version": "fixture-1"}] if value else []}
    return item


def run(database, run_id="run-test"):
    with writer_transaction(database) as (connection, _):
        connection.execute("INSERT INTO runs(id,trigger,started_at,status,scope_json) VALUES (?,'test',?,'running','{}')", (run_id, now()))
    return run_id


def snapshot(database):
    with read_database(database) as (connection, metadata):
        rows = [dict(row) for row in connection.execute("SELECT * FROM opportunities ORDER BY id")]
        changes = [dict(row) for row in connection.execute("SELECT * FROM changes ORDER BY id")]
        materials = [dict(row) for row in connection.execute("SELECT * FROM source_materials ORDER BY id")]
        tasks = [dict(row) for row in connection.execute("SELECT * FROM processing_tasks ORDER BY id")]
        return {"metadata": metadata, "rows": rows, "changes": changes, "materials": materials, "tasks": tasks}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "fixture.sqlite3"
    initialize_database(path, fixture=True)
    return path


def test_list_commits_then_failed_detail_preserves_time_venue_and_evidence(database):
    config = source()
    archive = material(config)
    item = candidate(config, archive)
    run_id = run(database)
    result = ingest_page(database, config, [item], [archive], run_id=run_id, next_cursor="page-2", fixture=True)
    before = snapshot(database)
    assert result["new"] == 1
    assert before["rows"][0]["event_venue"] == item["event_venue"]
    record_detail_failure(database, config, item, [], run_id=run_id, fixture=True)
    after = snapshot(database)
    assert after["rows"] == before["rows"]
    assert after["metadata"]["dataset_id"] == before["metadata"]["dataset_id"]
    observations = json.loads(after["rows"][0]["field_observations_json"])
    assert observations["event_venue"]["evidence"][0]["material_id"] == before["materials"][0]["id"]
    assert "material_ref" not in observations["event_venue"]["evidence"][0]
    assert next(task for task in after["tasks"] if task["task_kind"] == "detail")["status"] == "failed"


def test_new_material_and_attempt_time_alone_do_not_change_dataset_or_known_observation(database):
    config = source()
    first = material(config)
    item = candidate(config, first)
    run_id = run(database)
    ingest_page(database, config, [item], [first], run_id=run_id, fixture=True)
    before = snapshot(database)
    second = material(config, "new-content-hash")
    second["fetched_at"] = "2026-10-11T11:00:00+08:00"
    repeated = candidate(config, second)
    result = ingest_page(database, config, [repeated], [second], run_id=run_id, fixture=True)
    after = snapshot(database)
    assert result["unchanged"] == 1
    assert after["rows"] == before["rows"]
    assert after["changes"] == before["changes"]
    assert after["metadata"]["dataset_id"] == before["metadata"]["dataset_id"]
    assert len(after["materials"]) == 2


def test_same_identity_changed_date_and_deadline_update_history_dataset_once(database):
    config = source()
    first = material(config)
    item = candidate(config, first)
    run_id = run(database)
    ingest_page(database, config, [item], [first], run_id=run_id, fixture=True)
    second = material(config, "revised")
    revised = candidate(config, second)
    revised["event_date"] = "2026-10-21"
    revised["field_observations"]["event_date"]["value"] = revised["event_date"]
    revised["deadline"] = "2026-10-30"
    revised["field_observations"]["deadline"] = deepcopy(revised["field_observations"]["event_date"])
    revised["field_observations"]["deadline"]["value"] = revised["deadline"]
    before = snapshot(database)
    ingest_detail(database, config, revised, [second], run_id=run_id, fixture=True)
    after = snapshot(database)
    assert len(after["rows"]) == 1 and after["rows"][0]["version"] == 2
    assert after["metadata"]["dataset_id"] != before["metadata"]["dataset_id"]
    history = {entry["field_name"]: entry["change_kind"] for entry in after["changes"]}
    assert history["event_date"] == "official_change"
    assert history["deadline"] == "parser_improvement"
    third = material(config, "deadline-only")
    revised = candidate(config, third)
    revised["event_date"] = "2026-10-21"
    revised["field_observations"]["event_date"]["value"] = revised["event_date"]
    revised["deadline"] = "2026-11-01"
    revised["field_observations"]["deadline"] = deepcopy(revised["field_observations"]["event_date"])
    revised["field_observations"]["deadline"]["value"] = revised["deadline"]
    ingest_detail(database, config, revised, [third], run_id=run_id, fixture=True)
    final = snapshot(database)
    assert final["metadata"]["dataset_id"] != after["metadata"]["dataset_id"]
    assert final["changes"][-1]["field_name"] == "deadline"
    assert final["changes"][-1]["change_kind"] == "official_change"


def test_missing_detail_fields_do_not_clear_previously_known_facts(database):
    config = source()
    archive = material(config)
    item = candidate(config, archive)
    run_id = run(database)
    ingest_page(database, config, [item], [archive], run_id=run_id, fixture=True)
    before = snapshot(database)
    failed_parse = deepcopy(item)
    for field in CORE_FIELDS:
        failed_parse[field] = [] if field == "work_locations" else None
        failed_parse["field_observations"][field] = {"state": "not_collected", "value": None, "evidence": []}
    ingest_detail(database, config, failed_parse, [], run_id=run_id, fixture=True)
    assert snapshot(database)["rows"] == before["rows"]


@pytest.mark.parametrize("violation", ["missing", "other_source", "wrong_url", "forged_id"])
def test_bad_evidence_rolls_back_whole_page_materials_tasks_and_dataset(database, violation):
    config = source()
    archive = material(config)
    item = candidate(config, archive)
    evidence = item["field_observations"]["event_date"]["evidence"][0]
    if violation == "missing":
        evidence["material_ref"] = "never-acquired"
    elif violation == "other_source":
        archive["source_key"] = "gdut_homepage"
    elif violation == "wrong_url":
        evidence["source_url"] = config["official_entry_url"] + "notice/other"
    else:
        del evidence["material_ref"]
        evidence["material_id"] = 9000
    run_id = run(database)
    before = snapshot(database)
    with pytest.raises(ValueError):
        ingest_page(database, config, [item], [archive], run_id=run_id, fixture=True)
    assert snapshot(database) == before


def test_stable_null_list_task_and_detail_identity_across_runs(database):
    config = source()
    archive = material(config)
    item = candidate(config, archive)
    for run_id in (run(database, "one"), run(database, "two")):
        ingest_page(database, config, [item], [archive], run_id=run_id, next_cursor="page-2", fixture=True)
    state = snapshot(database)
    assert len(state["rows"]) == 1
    lists = [task for task in state["tasks"] if task["task_kind"] == "list"]
    assert len(lists) == 1 and lists[0]["opportunity_id"] is None
    assert lists[0]["task_identity"] == "list:homepage" and lists[0]["attempts"] == 2
    assert len([task for task in state["tasks"] if task["task_kind"] == "detail"]) == 1


def test_fixture_and_real_writes_cannot_mix(database, tmp_path):
    config = source()
    run_id = run(database)
    with pytest.raises(ValueError, match="真实采集"):
        ingest_page(database, config, [], [], run_id=run_id)
    real = tmp_path / "real.sqlite3"
    initialize_database(real)
    run_id = run(real)
    with pytest.raises(ValueError, match="隔离样例"):
        ingest_page(real, config, [], [], run_id=run_id, fixture=True)


def test_unregistered_or_cross_school_source_cannot_write(database):
    config = source()
    config["school_key"] = "gdut"
    run_id = run(database)
    with pytest.raises(ValueError):
        ingest_page(database, config, [], [], run_id=run_id, fixture=True)
    assert snapshot(database)["rows"] == []


def test_generic_list_does_not_erase_detail_type_campus_relevance_or_cancelled_state(database):
    config = source("gdut")
    archive = material(config)
    item = candidate(config, archive)
    item["campus_key"] = "verified_campus"
    item["relevance"] = "related"
    item["event_status"] = "cancelled"
    item["recruitment_status"] = "closed"
    item["field_observations"]["relevance"] = deepcopy(item["field_observations"]["event_date"])
    item["field_observations"]["relevance"]["value"] = "related"
    with writer_transaction(database) as (connection, _):
        connection.execute("INSERT INTO campuses(school_key,campus_key,name,evidence_url,observed_at) VALUES ('gdut','verified_campus','隔离官方校区',?,?)", (archive["source_url"], archive["fetched_at"]))
    run_id = run(database)
    ingest_detail(database, config, item, [archive], run_id=run_id, fixture=True)
    before = snapshot(database)
    generic = candidate(config, archive)
    generic.update(kind="announcement", original_kind="栏目通用公告", date_basis="publication", event_status="unknown")
    for field in ("event_date", "start_time", "end_time", "event_venue"):
        generic[field] = None
        generic["field_observations"][field] = {"state": "not_collected", "value": None, "evidence": []}
    ingest_page(database, config, [generic], [], run_id=run_id, fixture=True)
    assert snapshot(database)["rows"] == before["rows"]
    assert snapshot(database)["metadata"] == before["metadata"]


def test_list_cannot_resolve_conflicting_list_detail_evidence_by_repeating_old_value(database):
    config = source()
    archive = material(config)
    item = candidate(config, archive)
    run_id = run(database)
    ingest_page(database, config, [item], [archive], run_id=run_id, fixture=True)
    conflicting = material(config, "conflicting-detail")
    revised = deepcopy(item)
    proof = deepcopy(item["field_observations"]["event_date"]["evidence"][0])
    proof["material_ref"] = conflicting["reference_key"]
    revised["field_observations"]["event_date"] = {"state": "conflict", "value": None, "evidence": [item["field_observations"]["event_date"]["evidence"][0], proof]}
    ingest_detail(database, config, revised, [conflicting], run_id=run_id, fixture=True)
    before = snapshot(database)
    observation = json.loads(before["rows"][0]["field_observations_json"])["event_date"]
    assert observation["state"] == "conflict" and len(observation["evidence"]) == 2
    assert before["rows"][0]["event_date"] == item["event_date"]
    assert before["changes"][-1]["change_kind"] == "evidence_conflict"
    ingest_page(database, config, [item], [], run_id=run_id, fixture=True)
    assert snapshot(database)["rows"] == before["rows"]
    assert snapshot(database)["metadata"] == before["metadata"]


@pytest.mark.parametrize("state", ["not_applicable", "not_disclosed", "parse_failed", "pending_extraction"])
def test_unknown_observation_refinement_is_parser_progress_not_official_change(database, state):
    config = source()
    archive = material(config)
    item = candidate(config, archive)
    run_id = run(database)
    ingest_page(database, config, [item], [archive], run_id=run_id, fixture=True)
    next_archive = material(config, "refinement-" + state)
    refined = candidate(config, next_archive)
    proof = deepcopy(refined["field_observations"]["event_date"]["evidence"])
    refined["field_observations"]["deadline"] = {"state": state, "value": None, "evidence": proof}
    ingest_detail(database, config, refined, [next_archive], run_id=run_id, fixture=True)
    history = [entry for entry in snapshot(database)["changes"] if entry["field_name"] == "deadline"]
    assert len(history) == 1 and history[0]["change_kind"] == "parser_improvement"


def test_first_detail_headers_are_parser_progress_and_success_provenance_survives_next_run_failure(database):
    config = source()
    archive = material(config)
    generic = candidate(config, archive)
    generic.update(title="列表通用标题", kind="announcement", original_kind="栏目公告", date_basis="publication", event_status="not_applicable")
    for field in ("event_date", "start_time", "end_time", "event_venue"):
        generic[field] = None
        generic["field_observations"][field] = {"state": "not_collected", "value": None, "evidence": []}
    first_run = run(database, "first-detail")
    ingest_page(database, config, [generic], [archive], run_id=first_run, fixture=True)
    detail_archive = material(config, "first-detail-material")
    detail = candidate(config, detail_archive)
    detail["title"] = "详情明确原标题"
    ingest_detail(database, config, detail, [detail_archive], run_id=first_run, fixture=True)
    after = snapshot(database)
    header_changes = [entry for entry in after["changes"] if entry["field_name"] in {"title", "kind", "original_kind", "date_basis"}]
    assert {entry["field_name"] for entry in header_changes} == {"title", "kind", "original_kind", "date_basis"}
    assert all(entry["change_kind"] == "parser_improvement" for entry in header_changes)
    assert after["rows"][0]["event_status"] == "unknown"
    assert not any(entry["change_kind"] == "official_change" for entry in after["changes"])
    prior_context = json.loads(next(task for task in after["tasks"] if task["task_kind"] == "detail")["result_json"])
    assert prior_context["last_successful_detail"]["run_id"] == first_run
    next_run = run(database, "later-detail")
    ingest_page(database, config, [generic], [], run_id=next_run, fixture=True)
    record_detail_failure(database, config, generic, [], run_id=next_run, fixture=True)
    failed_context = json.loads(next(task for task in snapshot(database)["tasks"] if task["task_kind"] == "detail")["result_json"])
    assert failed_context["last_successful_detail"] == prior_context["last_successful_detail"]
    revised_archive = material(config, "official-title-edit")
    revised = candidate(config, revised_archive)
    revised["title"] = "后续官方明确改名"
    ingest_detail(database, config, revised, [revised_archive], run_id=next_run, fixture=True)
    changed_title = [entry for entry in snapshot(database)["changes"] if entry["field_name"] == "title"]
    assert len(changed_title) == 2 and changed_title[-1]["change_kind"] == "official_change"
