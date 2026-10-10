"""Temporary synthetic stores test boundaries, never official-source coverage."""

from datetime import datetime, timezone, timedelta
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.config import Settings
from backend.storage.database import DatabaseUnavailable, initialize_database, read_database


PUBLIC_PATHS = ("/health", "/version", "/api/catalog", "/api/opportunities", "/api/updates/summary", "/api/sources/status", "/api/opportunities/1")


def client(db_path, token="", remote="127.0.0.1"):
    settings = Settings(db_path=Path(db_path), backend_commit="test-commit", service_token=token)
    return TestClient(create_app(settings), client=(remote, 54321))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "isolated" / "workhunter-v2.sqlite3"
    initialize_database(path)
    return path


def test_explicit_init_is_idempotent_and_restart_keeps_dataset(database):
    initial_hash = digest(database)
    metadata = initialize_database(database)
    assert digest(database) == initial_hash
    for restarted in (client(database), client(database)):
        version = restarted.get("/version").json()
        assert version["dataset_id"] == metadata["dataset_id"]
        assert version["project"] == "Workhunter-v2.0"
        assert version["backend_commit"] == "test-commit"
        assert version["data_mode"] == "empty"
    assert digest(database) == initial_hash


def test_empty_new_database_keeps_ten_pending_schools_and_unknown_counts(database):
    api = client(database)
    schools = api.get("/api/catalog").json()["schools"]
    assert len(schools) == 10
    assert {school["school_key"] for school in schools} == {"scut", "gdut", "ncepu", "shiep", "neepu", "csust", "ctgu", "gzhu", "hnu", "csu"}
    assert all(school["availability"] == "pending" and school["campuses"] == [] for school in schools)
    assert all(school["opportunity_count"] == 0 for school in schools)
    result = api.get("/api/opportunities?school_key=gdut&campus_unknown=true&view=undated").json()
    assert result["items"] == [] and result["total"] == 0
    assert result["has_more"] is False
    assert result["empty_reason"] == "empty_database"
    assert result["applied_filters"]["school_key"] == "gdut"
    assert result["applied_filters"]["campus_unknown"] is True
    summary = api.get("/api/updates/summary").json()
    assert summary["check_status"] == "not_checked"
    assert summary["today"]["newly_collected"] is None
    assert summary["today"]["modified"] is None
    assert summary["last_success_at"] is None
    sources = api.get("/api/sources/status").json()["sources"]
    assert len(sources) == 10
    assert all(source["status"] == "not_checked" and source["last_success_at"] is None for source in sources)


def test_every_read_path_does_not_create_missing_database_or_directory(tmp_path):
    path = tmp_path / "does-not-exist" / "new.sqlite3"
    api = client(path)
    for route in PUBLIC_PATHS:
        response = api.get(route)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"
    assert not path.parent.exists()


def test_module_import_does_not_create_database(tmp_path):
    path = tmp_path / "absent" / "import.sqlite3"
    env = {**os.environ, "WH_DB_PATH": str(path)}
    result = subprocess.run([sys.executable, "-c", "from backend.api.app import app; assert app.title == 'Workhunter-v2.0'"], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert not path.parent.exists()


@pytest.mark.parametrize("table", ["metadata", "schools", "campuses", "sources", "opportunities", "source_materials", "processing_tasks", "runs", "changes", "manual_operations"])
def test_incomplete_schema_is_503_and_not_repaired(database, table):
    with sqlite3.connect(database) as connection:
        connection.execute(f'DROP TABLE "{table}"')
    before = digest(database)
    api = client(database)
    for route in PUBLIC_PATHS:
        assert api.get(route).status_code == 503
    with pytest.raises(DatabaseUnavailable):
        initialize_database(database)
    assert digest(database) == before


def test_missing_required_field_is_503(database):
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE opportunities DROP COLUMN deadline")
    before = digest(database)
    assert client(database).get("/health").status_code == 503
    assert client(database).get("/api/opportunities").status_code == 503
    assert digest(database) == before


@pytest.mark.parametrize("contents", [b"not a SQLite database", b""])
def test_corrupt_or_empty_existing_file_is_not_replaced(tmp_path, contents):
    path = tmp_path / "existing.sqlite3"
    path.write_bytes(contents)
    api = client(path)
    for route in PUBLIC_PATHS:
        assert api.get(route).status_code == 503
    with pytest.raises(DatabaseUnavailable):
        initialize_database(path)
    assert path.read_bytes() == contents


def test_wrong_project_is_not_read_or_overwritten(database):
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE metadata SET value='legacy-radar' WHERE key='project'")
    before = digest(database)
    assert client(database).get("/health").status_code == 503
    with pytest.raises(DatabaseUnavailable):
        initialize_database(database)
    assert digest(database) == before


def test_read_only_connection_and_all_gets_never_write(database):
    before = digest(database)
    files = {file.name for file in database.parent.iterdir()}
    with read_database(database) as (connection, _):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE prohibited(id INTEGER)")
    api = client(database)
    for route in PUBLIC_PATHS:
        response = api.get(route)
        assert response.status_code in {200, 404}
        assert response.headers["cache-control"] == "no-store"
    assert digest(database) == before
    assert {file.name for file in database.parent.iterdir()} == files


def test_service_token_protects_all_routes_including_identity(database):
    api = client(database, token="temporary-test-token", remote="203.0.113.12")
    before = digest(database)
    for route in PUBLIC_PATHS:
        assert api.get(route).status_code == 401
        assert api.get(route, headers={"Authorization": "Bearer wrong-token"}).status_code == 401
        assert api.get(route, headers={"Authorization": "Bearer temporary-test-token"}).status_code in {200, 404}
    assert api.post("/api/admin/operations/commit", headers={"Authorization": "Bearer temporary-test-token"}, json={}).status_code == 404
    assert digest(database) == before


def test_no_token_is_loopback_only(database):
    assert client(database, remote="203.0.113.12").get("/health").status_code == 403
    assert client(database, remote="::1").get("/health").status_code == 200


@pytest.mark.parametrize("query", [
    "salary_min=1", "view=jobs", "scope=strict", "date_from=2026-02-30", "date_from=2026-10-10&date_to=2026-10-09",
    "limit=0", "limit=101", "offset=-1", "campus_id=0", "campus_id=1&campus_unknown=true",
    "campus_unknown=yes", "kind=job", "school_key=scut&school_key=gdut", "offset=20",
])
def test_invalid_or_retired_filters_are_explicit_422(database, query):
    assert client(database).get("/api/opportunities?" + query).status_code == 422


def test_blank_filters_are_unrestricted_and_missing_ids_are_404(database):
    api = client(database)
    blank = api.get("/api/opportunities?school_key=%20%20&kind=&date_from=&date_to=&campus_id=&keyword=")
    assert blank.status_code == 200
    assert blank.json()["applied_filters"]["school_key"] is None
    assert api.get("/api/opportunities?school_key=unknown").status_code == 404
    assert api.get("/api/opportunities?campus_id=1").status_code == 404
    assert api.get("/api/opportunities/1").status_code == 404
    assert api.get("/api/opportunities/0").status_code == 422


def test_dataset_changed_rejects_page_without_returning_new_items(database):
    api = client(database)
    response = api.get("/api/opportunities?offset=20&dataset_id=obsolete")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dataset_changed"
    assert "items" not in response.json()
    dataset = api.get("/api/opportunities").json()["dataset_id"]
    assert api.get("/api/opportunities", params={"offset": 20, "dataset_id": dataset}).status_code == 200


def test_cli_refresh_explicitly_unimplemented_and_does_not_create_store(tmp_path):
    path = tmp_path / "not-created.sqlite3"
    for module, command in (("backend.cli", "refresh"), ("backend.worker", None)):
        args = [sys.executable, "-m", module] + ([command] if command else []) + ["--db", str(path)]
        result = subprocess.run(args, capture_output=True)
        assert result.returncode == 2
        assert not path.exists()


def test_cli_serve_fails_for_missing_database_or_unprotected_remote_bind(tmp_path):
    path = tmp_path / "no" / "database.sqlite3"
    env = {**os.environ, "WH_API_SERVICE_TOKEN": ""}
    for host in ("127.0.0.1", "0.0.0.0"):
        result = subprocess.run([sys.executable, "-m", "backend.cli", "serve", "--db", str(path), "--host", host], capture_output=True, env=env)
        assert result.returncode == 2
    assert not path.parent.exists()


def test_sql_views_scope_dates_stable_paging_and_literal_keyword(database):
    # Synthetic acceptance counterexamples live only in pytest's temporary directory.
    today = datetime.now(timezone(timedelta(hours=8))).date()
    old = (today - timedelta(days=90)).isoformat()
    future = (today + timedelta(days=2)).isoformat()
    rows = [
        (1, "普通公告 %", "publication", today.isoformat(), None, "unknown", "not_applicable"),
        (2, "历史公告", "publication", old, None, "related", "not_applicable"),
        (3, "未来活动", "event", old, future, "related", "scheduled"),
        (4, "未知日期活动", "event", None, None, "unknown", "unknown"),
        (5, "已核实无关", "publication", today.isoformat(), None, "unrelated", "not_applicable"),
        (6, "官方取消活动", "event", today.isoformat(), future, "related", "cancelled"),
    ]
    with sqlite3.connect(database) as connection:
        for item_id, title, basis, published, event, relevance, status in rows:
            connection.execute(
                "INSERT INTO opportunities(id,school_key,source_key,source_identity,title,kind,date_basis,source_url,published_date,event_date,relevance,event_status,first_seen_at) VALUES (?,'scut','scut_homepage',?,?,'announcement',?,'https://example.org/official-fixture',?,?,?,?,?)",
                (item_id, str(item_id), title, basis, published, event, relevance, status, today.isoformat() + "T12:00:00+08:00"),
            )
    api = client(database)
    assert {row["id"] for row in api.get("/api/opportunities").json()["items"]} == {1, 3, 6}
    assert {row["id"] for row in api.get("/api/opportunities?scope=all").json()["items"]} == {1, 3, 5, 6}
    for view, expected in (("upcoming", {3}), ("history", {2}), ("undated", {4})):
        result = api.get("/api/opportunities", params={"view": view}).json()
        assert {row["id"] for row in result["items"]} == expected
    assert [row["id"] for row in api.get("/api/opportunities", params={"keyword": "%"}).json()["items"]] == [1]
    page = api.get("/api/opportunities?limit=1").json()
    next_page = api.get("/api/opportunities", params={"limit": 1, "offset": 1, "dataset_id": page["dataset_id"]}).json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert page["total"] == next_page["total"] == 3
    detail = api.get("/api/opportunities/1").json()
    assert detail["work_locations"] == [] and detail["roster_fragments"] == []
    assert detail["job_fragments"] == [] and detail["attachments"] == []
