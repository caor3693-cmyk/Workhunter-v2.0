"""Temporary synthetic stores test boundaries, never official-source coverage."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.config import Settings
from backend.domain.candidates import CORE_FIELDS
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


@pytest.fixture
def fixture_database(tmp_path):
    path = tmp_path / "synthetic-only" / "workhunter-v2.sqlite3"
    initialize_database(path, fixture=True)
    return path


def seed_opportunity(connection, item_id=1, **values):
    """SQL fixtures bind explicit synthetic observations to archived fixture rows."""
    assert connection.execute("SELECT value FROM metadata WHERE key='data_mode'").fetchone()[0] == "isolated_fixture"
    fields = {
        "id": item_id, "school_key": "scut", "source_key": "scut_homepage",
        "source_identity": f"isolated-fixture:{item_id}", "title": "隔离合成公告",
        "kind": "announcement", "date_basis": "publication",
        "source_url": f"https://cnsba.scut.edu.cn/isolated-fixture/{item_id}",
        "first_seen_at": "2026-10-11T12:00:00+08:00", "relevance": "unknown",
        **values,
    }
    connection.execute(
        f"INSERT INTO opportunities({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
        tuple(fields.values()),
    )
    material_id = connection.execute(
        "INSERT INTO source_materials(source_key,reference_key,opportunity_id,source_url,material_hash,fetched_at,raw_reference,acquisition_status,parsing_status,parser_version,scope_json) VALUES (?,?,?,?,?,?,?,'success','success','isolated-fixture-1',?)",
        (fields["source_key"], f"synthetic-material:{item_id}", item_id, fields["source_url"],
         hashlib.sha256(f"isolated synthetic material {item_id}".encode()).hexdigest(),
         fields["first_seen_at"], f"isolated_fixture/{item_id}.txt",
         json.dumps({"type": "isolated_fixture", "coverage": "synthetic_only"})),
    ).lastrowid
    connection.execute('UPDATE source_materials SET official_record_id=? WHERE id=?',(fields['source_identity'],material_id))
    def relation(locator):
        basis={'source_identity':fields['source_identity'],'source_url':fields['source_url'],'locator':locator,'excerpt':'隔离合成依据','material_hash':hashlib.sha256(f"isolated synthetic material {item_id}".encode()).hexdigest()}
        return connection.execute('INSERT INTO opportunity_materials(opportunity_id,material_id,school_key,source_key,source_identity,relation_kind,locator,scope_json,basis_json,verified_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(item_id,material_id,fields['school_key'],fields['source_key'],fields['source_identity'],'body',locator,json.dumps('this_announcement'),json.dumps(basis),fields['first_seen_at'])).lastrowid
    evidence = {
        'source_identity': fields['source_identity'], 'association_id': relation(f'fixture:announcement:{item_id}'),
        "material_id": material_id, "source_url": fields["source_url"],
        "locator": f"fixture:announcement:{item_id}", "excerpt": "隔离合成材料，仅用于读取边界回归",
        "scope": "this_announcement", "observed_at": fields["first_seen_at"],
        "parser_version": "isolated-fixture-1",
    }
    observations = {}
    for field in CORE_FIELDS:
        value = json.loads(fields.get("work_locations_json", "[]")) if field == "work_locations" else fields.get(field)
        observations[field] = {
            "state": "known" if value not in (None, []) else "not_collected",
            "value": value if value not in (None, []) else None,
            "evidence": [{**evidence, "locator": f"fixture:{field}", "association_id":relation(f"fixture:{field}"), "excerpt": f"隔离合成 {field}: {value}"}] if value not in (None, []) else [],
        }
    if fields["relevance"] != "unknown":
        observations["relevance"] = {"state": "known", "value": fields["relevance"], "evidence": [evidence]}
    connection.execute("UPDATE opportunities SET field_observations_json=? WHERE id=?", (json.dumps(observations, ensure_ascii=False), item_id))
    return evidence


def change_observations(connection, transform, item_id=1):
    observations = json.loads(connection.execute("SELECT field_observations_json FROM opportunities WHERE id=?", (item_id,)).fetchone()[0])
    transform(observations)
    connection.execute("UPDATE opportunities SET field_observations_json=? WHERE id=?", (json.dumps(observations, ensure_ascii=False), item_id))


def assert_rejected_without_writes(database, routes=("/api/opportunities", "/api/opportunities/1")):
    before = digest(database)
    api = client(database)
    for route in routes:
        response = api.get(route)
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "database_unavailable"
    assert digest(database) == before


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


def test_explicit_migration_preserves_backup_dataset_and_null_task_history(tmp_path):
    from backend.storage.migrations import migrate_database
    from backend.config import ROOT
    path = tmp_path / 'old-v2.sqlite3'
    schema = (ROOT / 'backend/storage/schema.sql').read_text(encoding='utf-8').split('-- Ownership constraints')[0]
    schema = schema.replace('  reference_key TEXT NOT NULL,\n', '').replace(", UNIQUE(source_key,reference_key)", '')
    schema = schema.replace('  task_identity TEXT NOT NULL,\n', '').replace('UNIQUE(source_key,task_identity,task_kind)', 'UNIQUE(source_key,opportunity_id,task_kind)')
    with sqlite3.connect(path) as connection:
        connection.executescript(schema)
        connection.executemany('INSERT INTO metadata VALUES (?,?)', [('project','Workhunter-v2.0'),('schema_version','1'),('dataset_id','old-isolated-dataset'),('data_mode','empty')])
        connection.execute("INSERT INTO schools(school_key,name,homepage_seed_url) VALUES ('gdut','广东工业大学','https://career.gdut.edu.cn/')")
        connection.execute("INSERT INTO sources(source_key,school_key,name,channel_key,official_entry_url,adapter,scope_json) VALUES ('gdut_teachin','gdut','公开宣讲会','teachin','https://career.gdut.edu.cn/teachin','gdut','{}')")
        for _ in range(2):
            connection.execute("INSERT INTO processing_tasks(source_key,task_kind,budget_json) VALUES ('gdut_teachin','list','{}')")
    before = digest(path)
    with sqlite3.connect(path) as connection:
        original_dump = list(connection.iterdump())
    assert client(path).get('/health').status_code == 503
    assert digest(path) == before
    receipt = migrate_database(path)
    with sqlite3.connect(receipt['backup']) as connection:
        assert list(connection.iterdump()) == original_dump
    with read_database(path) as (connection, metadata):
        assert metadata['schema_version'] == '3' and metadata['dataset_id'] == 'old-isolated-dataset'
        tasks = connection.execute('SELECT task_identity,status FROM processing_tasks ORDER BY id').fetchall()
        assert len(tasks) == 2 and tasks[0][0] == 'list:teachin' and tasks[1][1] == 'superseded'
        with pytest.raises(sqlite3.OperationalError):
            connection.execute('DELETE FROM processing_tasks')
    assert migrate_database(path)['migration'] == 'already_current'


def test_foreign_database_cannot_be_migrated(database):
    from backend.storage.migrations import migrate_database
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE metadata SET value='legacy-radar' WHERE key='project'")
    before = digest(database)
    with pytest.raises(DatabaseUnavailable):
        migrate_database(database)
    assert digest(database) == before


def test_compound_ownership_is_enforced_by_storage(fixture_database):
    database = fixture_database
    with sqlite3.connect(database) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute("INSERT INTO campuses(school_key,campus_key,name,evidence_url,observed_at) VALUES ('gdut','university_city','大学城','https://career.gdut.edu.cn/teachin','2026-10-11T13:25:26+08:00')")
        campus = connection.execute('SELECT last_insert_rowid()').fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE sources SET campus_id=? WHERE source_key='scut_homepage'", (campus,))
        connection.execute("UPDATE sources SET campus_id=? WHERE source_key='gdut_homepage'", (campus,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE campuses SET school_key='scut' WHERE id=?", (campus,))


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
    response = api.get('/api/opportunities',params={'offset':20,'dataset_id':'obsolete','as_of':datetime.now(timezone(timedelta(hours=8))).date().isoformat()})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dataset_changed"
    assert "items" not in response.json()
    dataset = api.get("/api/opportunities").json()["dataset_id"]
    assert api.get("/api/opportunities", params={"offset": 20, "dataset_id": dataset,"as_of":datetime.now(timezone(timedelta(hours=8))).date().isoformat()}).status_code == 200


def test_cli_refresh_requires_explicit_store_and_does_not_create_it(tmp_path):
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


def test_sql_views_scope_dates_stable_paging_and_literal_keyword(fixture_database):
    database = fixture_database
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
            seed_opportunity(
                connection, item_id, title=title, kind="campus_talk" if basis == "event" else "announcement",
                date_basis=basis, published_date=published, event_date=event, relevance=relevance,
                event_status=status, first_seen_at=today.isoformat() + "T12:00:00+08:00",
            )
    api = client(database)
    assert api.get("/version").json()["data_mode"] == "isolated_fixture"
    assert {row["id"] for row in api.get("/api/opportunities").json()["items"]} == {1, 3, 6}
    assert {row["id"] for row in api.get("/api/opportunities?scope=all").json()["items"]} == {1, 3, 5, 6}
    for view, expected in (("upcoming", {3}), ("history", {2}), ("undated", {4})):
        result = api.get("/api/opportunities", params={"view": view}).json()
        assert {row["id"] for row in result["items"]} == expected
    assert [row["id"] for row in api.get("/api/opportunities", params={"keyword": "%"}).json()["items"]] == [1]
    page = api.get("/api/opportunities?limit=1").json()
    next_page = api.get("/api/opportunities", params={"limit": 1, "offset": 1, "dataset_id": page["dataset_id"],"as_of":page['as_of']}).json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert page["total"] == next_page["total"] == 3
    detail = api.get("/api/opportunities/1").json()
    assert detail["work_locations"] == [] and detail["roster_fragments"] == []
    assert detail["job_fragments"] == [] and detail["attachments"] == []


@pytest.mark.parametrize('route', [
    '/api/opportunities?offset=9223372036854775808', '/api/opportunities?campus_id=9223372036854775808',
    '/api/opportunities/9223372036854775808', '/api/opportunities?as_of=9999-12-31',
    '/api/opportunities?as_of=0001-01-01', '/api/opportunities?as_of=2026-02-30',
])
def test_large_numbers_and_invalid_query_clock_are_422(database, route):
    assert client(database).get(route).status_code == 422


def test_paging_requires_dataset_and_frozen_date(database):
    api = client(database)
    first = api.get('/api/opportunities').json()
    missing = api.get('/api/opportunities',params={'offset':1,'dataset_id':first['dataset_id']})
    assert missing.status_code==422 and missing.json()['detail']['code']=='as_of_required'
    assert api.get('/api/opportunities',params={'offset':1,'dataset_id':first['dataset_id'],'as_of':first['as_of']}).status_code==200


def test_midnight_paging_keeps_first_window_without_changing_dataset(fixture_database):
    database = fixture_database
    from datetime import date
    from backend.services.queries import Filters, opportunities
    with sqlite3.connect(database) as connection:
        for item_id,published in [(1,'2026-09-12'),(2,'2026-09-13'),(3,'2026-10-11')]:
            seed_opportunity(connection, item_id, title="隔离跨午夜公告", published_date=published, first_seen_at="2026-10-11T14:00:00+08:00")
    with read_database(database) as (connection,metadata):
        first = opportunities(connection,metadata,Filters(limit=1),date(2026,10,11),30)
        second = opportunities(connection,metadata,Filters(limit=1,offset=1,as_of=first['as_of']),date(2026,10,12),30)
        third = opportunities(connection,metadata,Filters(limit=1,offset=2,as_of=first['as_of']),date(2026,10,12),30)
        assert [p['items'][0]['id'] for p in (first,second,third)]==[3,2,1]
        assert first['dataset_id']==second['dataset_id']==third['dataset_id']
        assert first['total']==second['total']==third['total']==3
        moved = opportunities(connection,metadata,Filters(limit=1),date(2026,10,12),30)
        assert moved['total']==2


def test_missing_publication_sort_uses_full_first_seen_time(fixture_database):
    database = fixture_database
    with sqlite3.connect(database) as connection:
        for item_id,hour in [(1,23),(2,9),(3,12)]:
            seed_opportunity(connection, item_id, title="隔离缺日期公告", first_seen_at=f"2026-10-11T{hour:02}:00:00+08:00")
    assert [item['id'] for item in client(database).get('/api/opportunities?view=undated').json()['items']]==[1,3,2]


@pytest.mark.parametrize('column,value', [
    ('work_locations_json','[{"bad":"nested"}]'),
    ('field_observations_json','{"event_date":{"state":"known","value":"2026-10-12","evidence":[]}}'),
    ('source_url','javascript:alert(1)'),
])
def test_invalid_nested_projection_and_link_are_explainable_503(fixture_database,column,value):
    database = fixture_database
    with sqlite3.connect(database) as connection:
        seed_opportunity(connection, title="隔离坏字段公告")
        connection.execute(f'UPDATE opportunities SET {column}=?',(value,))
    assert_rejected_without_writes(database, ("/api/opportunities?view=undated", "/api/opportunities/1"))


@pytest.mark.parametrize("owner", [1, None], ids=["same-opportunity", "shared-source-material"])
def test_projection_uses_actual_successful_material_with_matching_url(fixture_database, owner):
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection, published_date=today)
        connection.execute("UPDATE source_materials SET opportunity_id=? WHERE id=?", (owner, evidence["material_id"]))
    before = digest(fixture_database)
    api = client(fixture_database)
    listing = api.get("/api/opportunities")
    detail = api.get("/api/opportunities/1")
    assert listing.status_code == detail.status_code == 200
    assert listing.json()["data_mode"] == "isolated_fixture"
    observation = detail.json()["field_observations"]["published_date"]
    assert observation["state"] == "known" and observation["value"] == today
    assert observation["evidence"][0]["material_id"] == evidence["material_id"]
    material = detail.json()["materials"][0]
    assert material["id"] == evidence["material_id"]
    assert material["source_key"] == "scut_homepage"
    assert material["source_url"] == observation["evidence"][0]["source_url"]
    assert material["acquisition_status"] == "success"
    assert "raw_reference" not in material
    assert digest(fixture_database) == before


@pytest.mark.parametrize("fault", [
    "missing-material", "boolean-material-id", "wrong-url", "other-source", "other-opportunity",
    "material-ref-only", "material-ref-with-id", "pending-material", "failed-material", "restricted-material",
])
def test_projection_rejects_unbound_or_mismatched_evidence_without_writes(fixture_database, fault):
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection, published_date=today)
        if fault in {'other-source','other-opportunity'}:
            # Simulate damage by an external writer; normal transactions reject
            # these mutations before they can create an invalid association.
            connection.execute('DROP TRIGGER materials_applicability_update')
        if fault in {"other-source", "other-opportunity", "pending-material", "failed-material", "restricted-material"}:
            if fault == "other-source":
                connection.execute("UPDATE source_materials SET source_key='gdut_homepage',opportunity_id=NULL WHERE id=?", (evidence["material_id"],))
            elif fault == "other-opportunity":
                seed_opportunity(connection, 2)
                connection.execute("UPDATE source_materials SET opportunity_id=2 WHERE id=?", (evidence["material_id"],))
            else:
                connection.execute("UPDATE source_materials SET acquisition_status=? WHERE id=?", (fault.removesuffix("-material"), evidence["material_id"]))
        else:
            def corrupt(observations):
                proof = observations["published_date"]["evidence"][0]
                if fault == "missing-material":
                    proof["material_id"] = 999999
                elif fault == "boolean-material-id":
                    # True must not resolve to the actual material row with ID 1.
                    assert evidence["material_id"] == 1
                    proof["material_id"] = True
                elif fault == "wrong-url":
                    proof["source_url"] += "?different-announcement=1"
                else:
                    proof["material_ref"] = "synthetic-material:1"
                    if fault == "material-ref-only":
                        proof.pop("material_id")
            change_observations(connection, corrupt)
    assert_rejected_without_writes(fixture_database)


@pytest.mark.parametrize("field,value", [
    ("published_date", "2026-10-11"), ("event_date", "2026-10-12"),
    ("start_time", "14:00"), ("end_time", "15:00"),
    ("deadline", "2026-10-20"), ("event_venue", "隔离合成会场"),
    ("work_locations", ["广州"]),
])
def test_missing_core_observation_cannot_display_nonempty_business_value(fixture_database, field, value):
    values = {"published_date": datetime.now(timezone(timedelta(hours=8))).date().isoformat()}
    if field == "published_date":
        value = values["published_date"]
    values["work_locations_json" if field == "work_locations" else field] = json.dumps(value) if field == "work_locations" else value
    with sqlite3.connect(fixture_database) as connection:
        seed_opportunity(connection, **values)
        change_observations(connection, lambda observations: observations.pop(field))
    assert_rejected_without_writes(fixture_database)


def test_missing_observations_only_default_unknown_when_business_values_are_empty(fixture_database):
    with sqlite3.connect(fixture_database) as connection:
        seed_opportunity(connection)
        connection.execute("UPDATE opportunities SET field_observations_json='{}' WHERE id=1")
    before = digest(fixture_database)
    api = client(fixture_database)
    for route in ("/api/opportunities?view=undated", "/api/opportunities/1"):
        response = api.get(route)
        assert response.status_code == 200
        item = response.json()["items"][0] if "items" in response.json() else response.json()
        assert set(item["field_observations"]) == set(CORE_FIELDS)
        assert all(observation == {"state": "not_collected", "value": None, "evidence": []} for observation in item["field_observations"].values())
        assert item["work_locations"] == []
    assert digest(fixture_database) == before


@pytest.mark.parametrize("state", ["not_disclosed", "not_applicable"])
@pytest.mark.parametrize("has_evidence", [True, False], ids=["material-backed", "no-material-basis"])
def test_checked_unknown_states_require_actual_material_basis(fixture_database, state, has_evidence):
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection)
        change_observations(connection, lambda observations: observations.update({
            "deadline": {"state": state, "value": None, "evidence": [evidence] if has_evidence else []},
        }))
    if not has_evidence:
        assert_rejected_without_writes(fixture_database, ("/api/opportunities?view=undated", "/api/opportunities/1"))
        return
    before = digest(fixture_database)
    response = client(fixture_database).get("/api/opportunities/1")
    assert response.status_code == 200
    assert response.json()["deadline"] is None
    assert response.json()["field_observations"]["deadline"]["state"] == state
    assert response.json()["materials"][0]["id"] == evidence["material_id"]
    assert digest(fixture_database) == before


@pytest.mark.parametrize("relevance", ["related", "unrelated"])
def test_explicit_relevance_requires_matching_material_observation(fixture_database, relevance):
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    with sqlite3.connect(fixture_database) as connection:
        seed_opportunity(connection, published_date=today, relevance=relevance)
        change_observations(connection, lambda observations: observations.pop("relevance"))
    assert_rejected_without_writes(fixture_database, ("/api/opportunities?scope=all", "/api/opportunities/1"))


@pytest.mark.parametrize("field", ["roster_fragments_json", "job_fragments_json"])
@pytest.mark.parametrize("scope", ["partial", "complete_for_material", "unknown"])
def test_fragment_scope_is_bounded_to_the_observed_material(fixture_database, field, scope):
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection)
        fragment = {"text": "隔离合成片段，不代表完整名单", "scope": scope, "evidence": [evidence]}
        connection.execute(f"UPDATE opportunities SET {field}=? WHERE id=1", (json.dumps([fragment], ensure_ascii=False),))
    before = digest(fixture_database)
    response = client(fixture_database).get("/api/opportunities/1")
    assert response.status_code == 200
    assert response.json()[field.removesuffix("_json")][0]["scope"] == scope
    assert digest(fixture_database) == before


@pytest.mark.parametrize("scope", ["complete_school", "this_announcement", {"coverage": "all"}, ""])
def test_invalid_fragment_scope_is_503_without_mutating_database(fixture_database, scope):
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection)
        fragment = {"text": "隔离合成片段", "scope": scope, "evidence": [evidence]}
        connection.execute("UPDATE opportunities SET roster_fragments_json=? WHERE id=1", (json.dumps([fragment], ensure_ascii=False),))
    before=digest(fixture_database)
    result=client(fixture_database).get('/api/opportunities/1')
    assert result.status_code==200 and result.json()['roster_fragments']==[]
    assert result.json()['supplemental_status']=='pending_verification'
    assert digest(fixture_database)==before


@pytest.mark.parametrize("field", ["roster_fragments_json", "job_fragments_json", "attachments_json"])
def test_fragment_and_attachment_evidence_cannot_borrow_another_opportunity(fixture_database, field):
    with sqlite3.connect(fixture_database) as connection:
        seed_opportunity(connection)
        other_evidence = seed_opportunity(connection, 2)
        fragment = {"scope": "partial", "evidence": [other_evidence]}
        if field == "attachments_json":
            fragment.update({"label": "隔离合成附件", "url": "https://cnsba.scut.edu.cn/isolated-fixture/attachment.pdf"})
        else:
            fragment["text"] = "隔离合成片段"
        connection.execute(f"UPDATE opportunities SET {field}=? WHERE id=1", (json.dumps([fragment], ensure_ascii=False),))
    before=digest(fixture_database)
    result=client(fixture_database).get('/api/opportunities/1')
    assert result.status_code==200 and result.json()[field.removesuffix('_json')]==[]
    assert result.json()['supplemental_status']=='pending_verification'
    assert digest(fixture_database)==before


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://user:password@career.gdut.edu.cn/",
    "http://localhost/", "http://127.0.0.1/",
])
def test_unsafe_official_entry_links_fail_catalog_and_source_views_without_writes(fixture_database, url):
    with sqlite3.connect(fixture_database) as connection:
        connection.execute("UPDATE sources SET official_entry_url=? WHERE source_key='ncepu_homepage'", (url,))
    assert_rejected_without_writes(fixture_database, ("/api/catalog", "/api/sources/status"))


def test_campus_evidence_cannot_use_another_school_host(fixture_database):
    with sqlite3.connect(fixture_database) as connection:
        connection.execute("INSERT INTO campuses(school_key,campus_key,name,evidence_url,observed_at) VALUES ('scut','synthetic-campus','隔离合成校区','https://career.gdut.edu.cn/isolated-fixture/campus','2026-10-11T12:00:00+08:00')")
    assert_rejected_without_writes(fixture_database, ("/api/catalog",))


def add_date_conflict(connection, field, evidence, item_id=1):
    other_id = connection.execute(
        "INSERT INTO source_materials(source_key,reference_key,opportunity_id,source_url,material_hash,fetched_at,raw_reference,acquisition_status,parsing_status,parser_version,scope_json) SELECT source_key,reference_key||':conflict',opportunity_id,source_url,?,fetched_at,raw_reference||':conflict',acquisition_status,parsing_status,parser_version,scope_json FROM source_materials WHERE id=?",
        (hashlib.sha256(b"isolated synthetic conflicting date material").hexdigest(), evidence["material_id"]),
    ).lastrowid
    identity=connection.execute('SELECT source_identity FROM opportunities WHERE id=?',(item_id,)).fetchone()[0]
    connection.execute('UPDATE source_materials SET official_record_id=? WHERE id=?',(identity,other_id))
    material=connection.execute('SELECT school_key,source_key FROM opportunities WHERE id=?',(item_id,)).fetchone()
    basis={'source_identity':identity,'source_url':evidence['source_url'],'locator':evidence['locator'],'excerpt':'隔离合成冲突依据','material_hash':hashlib.sha256(b'isolated synthetic conflicting date material').hexdigest()}
    association=connection.execute('INSERT INTO opportunity_materials(opportunity_id,material_id,school_key,source_key,source_identity,relation_kind,locator,scope_json,basis_json,verified_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(item_id,other_id,material[0],material[1],identity,'body',evidence['locator'],json.dumps(evidence['scope']),json.dumps(basis),evidence['observed_at'])).lastrowid
    conflict = {"state": "conflict", "value": None, "evidence": [evidence, {
        **evidence, "material_id": other_id, "association_id":association, "excerpt": "隔离合成材料中出现另一个日期，尚未裁定",
    }]}
    change_observations(connection, lambda observations: observations.update({field: conflict}), item_id)


@pytest.mark.parametrize("field,basis,old_date,known_publication", [
    ("published_date", "publication", "2026-10-11", None),
    ("published_date", "publication", "2026-07-01", None),
    ("event_date", "event", "2026-10-12", None),
    ("event_date", "event", "2026-10-10", None),
    ("event_date", "event", "2026-10-12", "2026-10-11"),
], ids=["recent-publication", "historical-publication", "upcoming-event", "past-event", "event-with-known-publication"])
def test_conflict_date_is_unknown_for_queries_but_other_known_date_can_match_recent(fixture_database, field, basis, old_date, known_publication):
    from datetime import date
    from backend.services.queries import Filters, opportunities
    values = {field: old_date, "date_basis": basis, "kind": "campus_talk" if basis == "event" else "announcement"}
    if known_publication:
        values["published_date"] = known_publication
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection, **values)
        add_date_conflict(connection, field, evidence)
    before = digest(fixture_database)
    with read_database(fixture_database) as (connection, metadata):
        for view in ("recent", "upcoming", "history", "undated"):
            result = opportunities(connection, metadata, Filters(view=view), date(2026, 10, 11), 30)
            expected = [1] if view == "undated" or (view == "recent" and known_publication) else []
            assert [item["id"] for item in result["items"]] == expected
            assert result["total"] == len(expected)
            for item in result["items"]:
                assert item["field_observations"][field]["state"] == "conflict"
                assert item["field_observations"][field]["value"] is None
                assert len(item["field_observations"][field]["evidence"]) == 2
        for view in ("recent", "upcoming", "history", "undated"):
            bounded = opportunities(connection, metadata, Filters(view=view, date_from=old_date, date_to=old_date), date(2026, 10, 11), 30)
            assert bounded["items"] == [] and bounded["total"] == 0
        assert connection.execute(f"SELECT {field} FROM opportunities WHERE id=1").fetchone()[0] == old_date
        assert metadata["data_mode"] == "isolated_fixture"
    assert digest(fixture_database) == before


def test_conflicted_publication_sort_uses_first_seen_without_erasing_old_date(fixture_database):
    with sqlite3.connect(fixture_database) as connection:
        evidence = seed_opportunity(connection, published_date="2020-01-01", first_seen_at="2026-10-11T23:00:00+08:00")
        add_date_conflict(connection, "published_date", evidence)
        seed_opportunity(connection, 2, first_seen_at="2026-10-11T09:00:00+08:00")
    before = digest(fixture_database)
    response = client(fixture_database).get("/api/opportunities?view=undated")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [1, 2]
    assert response.json()["items"][0]["published_date"] == "2020-01-01"
    assert response.json()["items"][0]["field_observations"]["published_date"]["state"] == "conflict"
    assert digest(fixture_database) == before
