"""Refresh orchestration uses synthetic adapters and the production write boundary."""

from copy import deepcopy
import json

import pytest

from backend.config import ROOT
from backend.services.discovery import refresh_sources, register_sources
from backend.sources import FetchError
from backend.storage.database import initialize_database, read_database
from backend.storage.write import RefreshBusy, writer_transaction
from test_ingestion import candidate, material, snapshot, source


class Transport:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Adapter:
    def __init__(self, database, *, pages=1, fail_list=False, fail_detail=False, interrupt_second=False):
        self.database = database
        self.pages = pages
        self.fail_list = fail_list
        self.fail_detail = fail_detail
        self.interrupt_second = interrupt_second
        self.visited = []
        self.enriched = []

    def discover(self, config, fetcher, cursor=None):
        # A network callback can acquire the writer immediately: no long transaction.
        with writer_transaction(self.database, timeout_seconds=0):
            pass
        if self.fail_list:
            raise FetchError("隔离反例限制", restricted=True)
        number = int(cursor or "1")
        self.visited.append(number)
        if self.interrupt_second and number == 2:
            raise KeyboardInterrupt("synthetic crash after first page commit")
        archive = material(config, "page-" + str(number))
        item = candidate(config, archive, identity="official-" + str(number))
        return {"source_key": config["source_key"], "channel_key": config["channel_key"], "records": [item], "next_cursor": str(number + 1) if number < self.pages else None, "scope": {"coverage": "isolated_fixture"}, "completeness": "partial" if number < self.pages else "complete_for_channel", "material_refs": [archive], "warnings": []}

    def enrich(self, item, fetcher):
        with writer_transaction(self.database, timeout_seconds=0):
            pass
        self.enriched.append(item["source_identity"])
        if self.fail_detail:
            raise FetchError("隔离详情超时", status="network_failed")
        return {"patch": {}, "material_refs": [], "warnings": []}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "fixture.sqlite3"
    initialize_database(path, fixture=True)
    return path


def test_restricted_school_does_not_stop_other_school_and_leaves_other_eight_untouched(database):
    configs = [source(), source("gdut")]
    failed = Adapter(database, fail_list=True)
    healthy = Adapter(database)
    before = snapshot(database)["metadata"]["dataset_id"]
    result = refresh_sources(database, configs, lambda config: failed if config["school_key"] == "scut" else healthy, lambda _: Transport(), fixture=True)
    state = snapshot(database)
    assert result["status"] == "partial"
    assert result["sources"][0]["status"] == "restricted"
    assert result["sources"][1]["status"] == "complete"
    assert {row["school_key"] for row in state["rows"]} == {"gdut"}
    assert state["metadata"]["dataset_id"] != before
    with read_database(database) as (connection, _):
        others = list(connection.execute("SELECT status,last_attempt_at,last_success_at FROM sources WHERE school_key NOT IN ('scut','gdut')"))
    assert len(others) == 8 and all(tuple(row) == ("not_checked", None, None) for row in others)
    assert state["materials"][0]["acquisition_status"] == "restricted"


def test_all_failed_sources_without_a_committed_page_return_failed_not_partial(database):
    before = snapshot(database)
    result = refresh_sources(database, [source(), source("gdut")], lambda _: Adapter(database, fail_list=True), lambda _: Transport(), fixture=True)
    assert result["status"] == "failed" and result["pages"] == 0
    assert result["commits"] == {"new": 0, "modified": 0, "unchanged": 0}
    after = snapshot(database)
    assert after["rows"] == before["rows"] and after["metadata"] == before["metadata"]
    with read_database(database) as (connection, _):
        assert connection.execute("SELECT status FROM runs").fetchone()[0] == "failed"


def test_detail_timeout_does_not_remove_list_facts_or_stop_next_list_page(database):
    config = source()
    adapter = Adapter(database, pages=3, fail_detail=True)
    result = refresh_sources(database, [config], lambda _: adapter, lambda _: Transport(), fixture=True)
    state = snapshot(database)
    assert adapter.visited == [1, 2]
    assert len(state["rows"]) == 2
    assert state["rows"][0]["event_venue"] == "官方本场教室"
    assert state["rows"][0]["event_date"] == "2026-10-20"
    assert result["sources"][0]["status"] == "partial"
    assert result["sources"][0]["detail_failures"] == 2


def test_page_and_detail_budgets_persist_partial_cursor_and_pending_tasks(database):
    config = source()
    adapter = Adapter(database, pages=100)
    result = refresh_sources(database, [config], lambda _: adapter, lambda _: Transport(), page_budget=2, detail_budget=0, fixture=True)
    assert adapter.visited == [1, 2] and adapter.enriched == []
    assert result["status"] == "partial"
    state = snapshot(database)
    assert len(state["rows"]) == 2
    task = next(task for task in state["tasks"] if task["task_kind"] == "list")
    assert json.loads(task["cursor_json"]) == "3" and task["status"] == "partial"
    assert len([task for task in state["tasks"] if task["status"] == "pending"]) == 2


def test_committed_page_survives_interruption_and_resume_does_not_rediscover_it(database):
    config = source()
    interrupted = Adapter(database, pages=2, interrupt_second=True)
    with pytest.raises(KeyboardInterrupt):
        refresh_sources(database, [config], lambda _: interrupted, lambda _: Transport(), detail_budget=0, fixture=True)
    state = snapshot(database)
    assert len(state["rows"]) == 1
    with read_database(database) as (connection, _):
        run = connection.execute("SELECT id,status FROM runs").fetchone()
    assert run["status"] == "interrupted"
    resumed = Adapter(database, pages=2)
    result = refresh_sources(database, [config], lambda _: resumed, lambda _: Transport(), resume_run_id=run["id"], fixture=True)
    assert resumed.visited == [2]
    assert resumed.enriched == ["official-1", "official-2"]
    assert len(snapshot(database)["rows"]) == 2
    assert result["status"] == "complete" and result["commits"]["new"] == 2


def test_repeat_refresh_changes_only_run_status_not_dataset_or_opportunity(database):
    config = source()
    refresh_sources(database, [config], lambda _: Adapter(database), lambda _: Transport(), fixture=True)
    before = snapshot(database)
    result = refresh_sources(database, [config], lambda _: Adapter(database), lambda _: Transport(), fixture=True)
    after = snapshot(database)
    assert after["rows"] == before["rows"]
    assert after["metadata"] == before["metadata"]
    assert result["commits"]["new"] == 0 and result["commits"]["modified"] == 0
    assert len([task for task in after["tasks"] if task["task_kind"] == "list"]) == 1


def test_whole_run_lock_rejects_a_second_refresh_before_network(database):
    config = source()
    adapter = Adapter(database)
    original = adapter.discover

    def discover(*args):
        with pytest.raises(RefreshBusy):
            refresh_sources(database, [config], lambda _: Adapter(database), lambda _: Transport(), fixture=True)
        return original(*args)

    adapter.discover = discover
    refresh_sources(database, [config], lambda _: adapter, lambda _: Transport(), fixture=True)
    with read_database(database) as (connection, _):
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_registration_is_explicit_idempotent_and_does_not_change_empty_dataset(database):
    config = json.loads((ROOT / "config" / "schools.json").read_text(encoding="utf-8"))
    before = snapshot(database)["metadata"]
    registered = register_sources(database, config, fixture=True)
    assert len(registered) == 4
    assert register_sources(database, config, fixture=True) == registered
    assert snapshot(database)["metadata"] == before
    with read_database(database) as (connection, _):
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 14
        registered_campuses = {(row["school_key"], row["campus_key"]) for row in connection.execute("SELECT school_key,campus_key FROM campuses")}
        assert registered_campuses == {(school["school_key"], campus["campus_key"]) for school in config["schools"] for campus in school.get("campuses", []) if school["school_key"] in {"scut", "gdut"}}
        assert connection.execute("SELECT status FROM sources WHERE source_key='scut_homepage'").fetchone()[0] == "restricted"
        others = connection.execute("SELECT verification_state,verified_at FROM schools WHERE school_key NOT IN ('scut','gdut')").fetchall()
    assert all(tuple(row) == ("pending", None) for row in others)


def test_refresh_rejects_fixture_mix_and_unapproved_school_before_network(database):
    config = source()
    with pytest.raises(ValueError, match="真实采集"):
        refresh_sources(database, [config], fixture=False)
    with pytest.raises(ValueError, match="仅允许"):
        refresh_sources(database, [config], fixture=True, school_keys=("ncepu",))
    assert snapshot(database)["rows"] == []


def test_failed_detail_is_retryable_on_resume_but_restricted_pattern_is_stopped(database):
    config = source()
    adapter = Adapter(database, pages=2)

    def restricted(item, fetcher):
        adapter.enriched.append(item["source_identity"])
        raise FetchError("synthetic restricted detail pattern", restricted=True)

    adapter.enrich = restricted
    result = refresh_sources(database, [config], lambda _: adapter, lambda _: Transport(), fixture=True)
    assert adapter.visited == [1, 2] and adapter.enriched == ["official-1"]
    assert result["sources"][0]["restricted_details"] == 2
    assert result["status"] == "partial"
    repeated = Adapter(database, pages=2)
    refresh_sources(database, [config], lambda _: repeated, lambda _: Transport(), fixture=True)
    assert repeated.enriched == []


def test_successful_http_with_failed_body_parser_is_a_detail_failure(database):
    config = source()
    adapter = Adapter(database)

    def missing_body(item, fetcher):
        archive = material(config, "unparsed-detail")
        archive["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [archive], "warnings": ["正文槽未取得"]}

    adapter.enrich = missing_body
    result = refresh_sources(database, [config], lambda _: adapter, lambda _: Transport(), fixture=True)
    assert result["status"] == "partial" and result["sources"][0]["detail_failures"] == 1
    assert snapshot(database)["rows"][0]["event_venue"] == "官方本场教室"
    resumed = Adapter(database)
    result = refresh_sources(database, [config], lambda _: resumed, lambda _: Transport(), fixture=True, resume_run_id=result["run_id"])
    assert resumed.visited == [] and resumed.enriched == ["official-1"]
    assert result["status"] == "complete"


def test_real_source_adapter_protocol_in_isolated_store_does_not_churn_on_repeat(database, tmp_path):
    from test_sources import fetcher, fixture

    config = json.loads((ROOT / "config" / "schools.json").read_text(encoding="utf-8"))
    # This campus exists only in the explicitly isolated synthetic fixture.
    config["schools"][0]["campuses"] = [{"campus_key": "wushan", "name": "隔离五山校区", "evidence_url": "https://cnsba.scut.edu.cn/2026/1009/c29313a9000002/page.htm", "observed_at": "2026-10-11T10:00:00+08:00"}]
    configs = register_sources(database, config, fixture=True)
    scut = next(item for item in configs if item["school_key"] == "scut")
    pages = {scut["official_entry_url"]: fixture("scut_list.html"), "https://cnsba.scut.edu.cn/2026/1009/c29313a9000001/page.htm": fixture("scut_announcement.html"), "https://cnsba.scut.edu.cn/2026/1009/c29313a9000002/page.htm": fixture("scut_month_day.html")}
    refresh_sources(database, [scut], transport=lambda _: fetcher(tmp_path, pages), page_budget=1, detail_budget=2, fixture=True)
    before = snapshot(database)
    assert not any(entry["change_kind"] == "official_change" for entry in before["changes"])
    assert any(entry["change_kind"] == "evidence_conflict" for entry in before["changes"])
    result = refresh_sources(database, [scut], transport=lambda _: fetcher(tmp_path, pages), page_budget=1, detail_budget=2, fixture=True)
    after = snapshot(database)
    assert len(after["rows"]) == 2
    assert after["rows"] == before["rows"]
    assert after["metadata"] == before["metadata"]
    assert result["commits"]["new"] == 0 and result["commits"]["modified"] == 0
