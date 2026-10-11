"""Synthetic auth stores prove service boundaries, not owner acceptance."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Barrier
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from backend.api.auth import MAX_LOGIN_BODY_BYTES, register_auth_routes
from backend.services import auth
from backend.storage.database import DatabaseUnavailable, initialize_database, read_database


ORIGIN = "https://workhunter.test"
PASSWORD = "synthetic-only-maintenance-password"


@pytest.fixture(scope="module")
def password_hash():
    return auth.hash_password(PASSWORD)


@pytest.fixture
def settings(tmp_path, password_hash):
    path = tmp_path / "synthetic-auth" / "workhunter-v2.sqlite3"
    initialize_database(path, fixture=True)
    return SimpleNamespace(db_path=path, maintenance_password_hash=password_hash,
                           maintenance_actor="synthetic-maintainer", maintenance_origin=ORIGIN)


def application(settings):
    app = FastAPI()
    register_auth_routes(app, settings)

    @app.exception_handler(DatabaseUnavailable)
    async def unavailable(request, exception):
        return JSONResponse({"detail": {"code": "database_unavailable"}}, status_code=503)

    @app.get("/api/admin/operations")
    def audit(request: Request):
        # The real maintenance projection uses the same auth function.
        identity = auth.require_session(request, settings)
        return {"actor": identity["actor"], "session_id": identity["session_id"], "session_hash": identity["session_hash"], "operations": []}

    @app.post("/api/admin/protected-test")
    def protected_write(request: Request):
        return auth.require_session(request, settings, write=True)

    return app


def client(settings):
    return TestClient(application(settings), base_url=ORIGIN)


def bootstrap(api):
    response = api.get("/api/admin/session")
    assert response.status_code == 200, response.text
    assert response.json()["authenticated"] is False
    return response.json()["csrf_token"]


def login(api, password=PASSWORD, csrf=None):
    csrf = csrf if csrf is not None else bootstrap(api)
    return api.post("/api/admin/session/login", json={"password": password}, headers={"Origin": ORIGIN, "X-WH-CSRF": csrf})


def rows(settings, table):
    with read_database(settings.db_path) as (connection, _):
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def test_password_hash_salt_cost_and_constant_time_comparison(password_hash, monkeypatch):
    another = auth.hash_password(PASSWORD)
    assert password_hash != another
    assert password_hash.startswith("$scrypt$32768$8$1$")
    comparisons = []
    original = auth.hmac.compare_digest
    monkeypatch.setattr(auth.hmac, "compare_digest", lambda first, second: comparisons.append((len(first), len(second))) or original(first, second))
    assert auth.verify_password(PASSWORD, password_hash)
    assert not auth.verify_password("wrong synthetic password", password_hash)
    assert comparisons == [(32, 32), (32, 32)]
    for invalid in ("", "$scrypt$999999999$8$1$a$b", password_hash.replace("$8$", "$80$"), password_hash + "$"):
        assert not auth.verify_password(PASSWORD, invalid)


@pytest.mark.parametrize("value", ["", None, "x" * (auth.MAX_PASSWORD_LENGTH + 1)])
def test_invalid_password_cannot_be_hashed(value):
    with pytest.raises(ValueError):
        auth.hash_password(value)


def test_bootstrap_cookie_is_secure_minimal_persistent_and_reused(settings):
    api = client(settings)
    before = rows(settings, "metadata")
    response = api.get("/api/admin/session")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert all(value in cookie for value in ("Secure", "HttpOnly", "SameSite=strict", "Path=/", "Max-Age=600"))
    assert "Domain=" not in cookie
    assert set(response.json()) == {"authenticated", "csrf_token", "expires_at"}
    assert response.headers["cache-control"] == "no-store"
    token = api.cookies.get(auth.COOKIE_NAME)
    session = rows(settings, "maintenance_sessions")[0]
    assert token not in str(session) and response.json()["csrf_token"] not in str(session)
    assert session["session_hash"] == hashlib.sha256(token.encode()).hexdigest()
    reread = api.get("/api/admin/session")
    assert "set-cookie" not in reread.headers
    assert reread.json() == response.json()
    assert rows(settings, "metadata") == before
    assert rows(settings, "changes") == []
    assert rows(settings, "runs") == []


def test_authenticated_identity_uses_only_server_actor_and_survives_app_restart(settings):
    api = client(settings)
    old = bootstrap(api)
    old_token = api.cookies.get(auth.COOKIE_NAME)
    response = login(api, csrf=old)
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["actor"] == settings.maintenance_actor
    assert "Max-Age=28800" in response.headers["set-cookie"]
    token = api.cookies.get(auth.COOKIE_NAME)
    assert token != old_token and response.json()["csrf_token"] != old
    assert rows(settings, "maintenance_sessions")[0]["revoked_at"] is not None
    restarted = client(settings)
    restarted.cookies.set(auth.COOKIE_NAME, token)
    audit = restarted.get("/api/admin/operations")
    assert audit.status_code == 200
    assert audit.json()["actor"] == settings.maintenance_actor
    assert audit.json()["session_id"] == audit.json()["session_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert restarted.post("/api/admin/protected-test", headers={"Origin": ORIGIN, "X-WH-CSRF": response.json()["csrf_token"]}).status_code == 200
    assert restarted.post("/api/admin/protected-test", headers={"Origin": ORIGIN, "X-WH-CSRF": old}).status_code == 403
    # Rotated bootstrap tokens cannot establish another session or read audit details.
    anonymous = client(settings)
    anonymous.cookies.set(auth.COOKIE_NAME, old_token)
    assert anonymous.get("/api/admin/operations").status_code == 401
    assert login(anonymous, csrf=old).status_code == 401


def test_anonymous_and_bootstrap_cannot_read_audit_and_get_is_read_only(settings):
    api = client(settings)
    before = settings.db_path.read_bytes()
    response = api.get("/api/admin/operations")
    assert response.status_code == 401
    assert "operations" not in response.json()
    assert settings.db_path.read_bytes() == before
    bootstrap(api)
    before = settings.db_path.read_bytes()
    assert api.get("/api/admin/operations").status_code == 401
    assert settings.db_path.read_bytes() == before
    login(api)
    before = settings.db_path.read_bytes()
    assert api.get("/api/admin/operations").status_code == 200
    assert settings.db_path.read_bytes() == before


@pytest.mark.parametrize("headers", [{}, {"Origin": ORIGIN}, {"X-WH-CSRF": "a" * 43}, {"Origin": "https://other.test", "X-WH-CSRF": "a" * 43}, {"Origin": "null", "X-WH-CSRF": "a" * 43}])
def test_login_requires_fixed_origin_and_bootstrap_csrf(settings, headers):
    api = client(settings)
    bootstrap(api)
    before = settings.db_path.read_bytes()
    response = api.post("/api/admin/session/login", json={"password": PASSWORD}, headers=headers)
    assert response.status_code == 403
    assert settings.db_path.read_bytes() == before


def test_writes_logout_and_cross_origin_reads_are_protected(settings):
    api = client(settings)
    response = login(api)
    csrf = response.json()["csrf_token"]
    before = settings.db_path.read_bytes()
    for route in ("/api/admin/protected-test", "/api/admin/session/logout"):
        assert api.post(route, headers={"Origin": ORIGIN}).status_code == 403
        assert api.post(route, headers={"Origin": "https://other.test", "X-WH-CSRF": csrf}).status_code == 403
        assert api.post(route, headers={"Origin": ORIGIN, "X-WH-CSRF": "invalid"}).status_code == 403
    assert api.get("/api/admin/operations", headers={"Origin": "https://other.test"}).status_code == 403
    assert api.get("/api/admin/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert settings.db_path.read_bytes() == before


def test_logout_revokes_persistent_token_and_clears_cookie(settings):
    api = client(settings)
    response = login(api)
    token, csrf = api.cookies.get(auth.COOKIE_NAME), response.json()["csrf_token"]
    response = api.post("/api/admin/session/logout", headers={"Origin": ORIGIN, "X-WH-CSRF": csrf})
    assert response.status_code == 200 and response.json() == {"authenticated": False}
    assert all(value in response.headers["set-cookie"] for value in ("Max-Age=0", "Secure", "HttpOnly", "SameSite=strict", "Path=/"))
    assert api.get("/api/admin/operations").status_code == 401
    replay = client(settings)
    replay.cookies.set(auth.COOKIE_NAME, token)
    assert replay.get("/api/admin/operations").status_code == 401
    assert replay.post("/api/admin/protected-test", headers={"Origin": ORIGIN, "X-WH-CSRF": csrf}).status_code == 401
    matching = next(row for row in rows(settings, "maintenance_sessions") if row["session_hash"] == hashlib.sha256(token.encode()).hexdigest())
    assert matching["revoked_at"] is not None


def test_expired_session_and_bootstrap_cannot_authenticate(settings, monkeypatch):
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    api = client(settings)
    csrf = bootstrap(api)
    now += timedelta(seconds=auth.BOOTSTRAP_SECONDS)
    assert login(api, csrf=csrf).status_code == 401
    response = login(api)
    assert response.status_code == 200
    csrf = response.json()["csrf_token"]
    now += timedelta(seconds=auth.SESSION_SECONDS)
    assert api.get("/api/admin/operations").status_code == 401
    assert api.post("/api/admin/protected-test", headers={"Origin": ORIGIN, "X-WH-CSRF": csrf}).status_code == 401
    assert api.get("/api/admin/session").json()["authenticated"] is False


def test_failures_persist_globally_and_per_actor_and_new_bootstrap_cannot_bypass(settings, monkeypatch):
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    failures = []
    for index in range(auth.MAX_FAILURES):
        # New app, cookie and bootstrap on every attempt; the budget remains global.
        response = login(client(settings), password=f"wrong-{index}")
        assert response.status_code == 401
        failures.append(response.json())
    records = rows(settings, "maintenance_login_failures")
    assert len(records) == 2 and {row["attempts"] for row in records} == {5}
    assert all(row["blocked_until"] for row in records)
    response = login(client(settings))
    assert response.status_code == 429 and response.json() == failures[0]
    # A configured actor change still cannot evade the global budget.
    changed = SimpleNamespace(**{**vars(settings), "maintenance_actor": "second-synthetic-maintainer"})
    assert login(client(changed)).status_code == 429
    now += timedelta(seconds=auth.FAILURE_SECONDS)
    assert login(client(settings)).status_code == 200
    assert rows(settings, "maintenance_login_failures") == []


def test_failure_window_and_bootstrap_storage_are_bounded(settings, monkeypatch):
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    monkeypatch.setattr(auth, "MAX_BOOTSTRAPS", 3)
    for _ in range(8):
        bootstrap(client(settings))
    assert len(rows(settings, "maintenance_sessions")) == 3
    assert login(client(settings), password="wrong").status_code == 401
    now += timedelta(seconds=auth.FAILURE_SECONDS + 1)
    assert login(client(settings), password="wrong").status_code == 401
    assert {row["attempts"] for row in rows(settings, "maintenance_login_failures")} == {1}
    assert len(rows(settings, "maintenance_login_failures")) == 2
    # The password hash, raw token and CSRF value are not failure-record contents.
    assert settings.maintenance_password_hash not in str(rows(settings, "maintenance_login_failures"))


def test_concurrent_bad_logins_cannot_exceed_persistent_failure_budget(settings, monkeypatch):
    apis = [client(settings) for _ in range(7)]
    contexts = [(api, bootstrap(api)) for api in apis]
    barrier = Barrier(len(apis))

    def bad_password(password, encoded):
        # Align password checks outside the writer to exercise the actual commit race.
        barrier.wait(timeout=15)
        return False

    monkeypatch.setattr(auth, "verify_password", bad_password)
    with ThreadPoolExecutor(max_workers=len(apis)) as pool:
        responses = list(pool.map(lambda context: login(context[0], password="wrong", csrf=context[1]), contexts))
    assert sorted(response.status_code for response in responses) == [401] * 5 + [429] * 2
    records = rows(settings, "maintenance_login_failures")
    assert len(records) == 2 and {row["attempts"] for row in records} == {auth.MAX_FAILURES}


def test_real_session_storage_is_bounded(settings, monkeypatch):
    monkeypatch.setattr(auth, "MAX_SESSION_RECORDS", 2)
    tokens = []
    for _ in range(4):
        api = client(settings)
        assert login(api).status_code == 200
        tokens.append(api.cookies.get(auth.COOKIE_NAME))
    real_rows = [row for row in rows(settings, "maintenance_sessions") if row["actor"] == settings.maintenance_actor]
    assert len(real_rows) == 2
    stale = client(settings)
    stale.cookies.set(auth.COOKIE_NAME, tokens[0])
    assert stale.get("/api/admin/operations").status_code == 401


@pytest.mark.parametrize("field,value", [("maintenance_password_hash", ""), ("maintenance_password_hash", "not-a-hash"), ("maintenance_actor", ""), ("maintenance_origin", ""), ("maintenance_origin", "http://workhunter.test"), ("maintenance_origin", ORIGIN + "/path"), ("maintenance_origin", "https://user:password@workhunter.test")])
def test_unconfigured_or_invalid_configuration_fails_closed(settings, field, value):
    setattr(settings, field, value)
    api = client(settings)
    before = settings.db_path.read_bytes()
    assert api.get("/api/admin/session").status_code == 503
    assert api.get("/api/admin/operations").status_code == 503
    assert api.post("/api/admin/session/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN, "X-WH-CSRF": "a" * 43}).status_code == 503
    assert settings.db_path.read_bytes() == before


def test_missing_database_is_not_created_by_bootstrap(settings):
    settings.db_path = settings.db_path.parent / "absent.sqlite3"
    assert client(settings).get("/api/admin/session").status_code == 503
    assert not settings.db_path.exists()


@pytest.mark.parametrize("payload", [{"password": PASSWORD, "actor": "attacker"}, {"password": None}, {"password": ""}, {"password": "x" * (auth.MAX_PASSWORD_LENGTH + 1)}, [], {"sql": "SELECT 1"}])
def test_login_input_cannot_inject_actor_or_unbounded_password(settings, payload):
    api = client(settings)
    csrf = bootstrap(api)
    before = settings.db_path.read_bytes()
    response = api.post("/api/admin/session/login", json=payload, headers={"Origin": ORIGIN, "X-WH-CSRF": csrf})
    assert response.status_code == 422
    assert settings.db_path.read_bytes() == before


def test_body_and_duplicate_security_headers_are_rejected(settings):
    api = client(settings)
    csrf = bootstrap(api)
    response = api.post("/api/admin/session/login", content=b"x" * (MAX_LOGIN_BODY_BYTES + 1), headers={"Origin": ORIGIN, "X-WH-CSRF": csrf})
    assert response.status_code == 413
    response = api.post("/api/admin/session/login", content=b"{", headers={"Origin": ORIGIN, "X-WH-CSRF": csrf})
    assert response.status_code == 422
    response = api.post("/api/admin/session/login", json={"password": PASSWORD}, headers=[("Origin", ORIGIN), ("Origin", ORIGIN), ("X-WH-CSRF", csrf)])
    assert response.status_code == 403
    response = api.post("/api/admin/session/login", json={"password": PASSWORD}, headers=[("Origin", ORIGIN), ("X-WH-CSRF", csrf), ("X-WH-CSRF", csrf)])
    assert response.status_code == 403


def test_auth_changes_do_not_change_dataset_or_business_records(settings):
    metadata = rows(settings, "metadata")
    api = client(settings)
    response = login(api)
    api.post("/api/admin/session/logout", headers={"Origin": ORIGIN, "X-WH-CSRF": response.json()["csrf_token"]})
    login(client(settings), password="wrong")
    assert rows(settings, "metadata") == metadata
    for table in ("opportunities", "changes", "manual_operations", "write_receipts", "runs", "source_materials", "processing_tasks"):
        assert rows(settings, table) == []
