"""Business maintenance authentication; auth state never changes the dataset."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from backend.storage.database import read_database
from backend.storage.write import writer_transaction


COOKIE_NAME = "wh_maintenance"
BOOTSTRAP_SECONDS = 600
SESSION_SECONDS = 8 * 60 * 60
FAILURE_SECONDS = 15 * 60
MAX_FAILURES = 5
MAX_BOOTSTRAPS = 128
MAX_SESSION_RECORDS = 256
MAX_PASSWORD_LENGTH = 1024
_BOOTSTRAP_ACTOR = "@maintenance-bootstrap"
_TOKEN = re.compile(r"^[bs]\.[A-Za-z0-9_-]{43}$")
_BASE64 = re.compile(r"^[A-Za-z0-9_-]+$")
_FAILED_MESSAGE = "登录未成功，请检查口令或稍后重试。"


def _now():
    return datetime.now(timezone.utc)


def _error(status, code, message):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value):
    if not isinstance(value, str) or not _BASE64.fullmatch(value):
        raise ValueError("Invalid password hash encoding")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _encode(decoded) != value:
        raise ValueError("Noncanonical password hash encoding")
    return decoded


def _password_parameters(encoded):
    if not isinstance(encoded, str) or len(encoded) > 256:
        raise ValueError("Invalid password hash")
    parts = encoded.split("$")
    if len(parts) != 7 or parts[:2] != ["", "scrypt"]:
        raise ValueError("Invalid password hash")
    n, r, p = map(int, parts[2:5])
    if [str(n), str(r), str(p)] != parts[2:5] or n not in {16384, 32768, 65536, 131072} or r != 8 or p != 1:
        raise ValueError("Unsupported password hash cost")
    salt, digest = _decode(parts[5]), _decode(parts[6])
    if len(salt) != 16 or len(digest) != 32:
        raise ValueError("Invalid password hash length")
    return n, r, p, salt, digest


def hash_password(password: str) -> str:
    """Create a self-contained salted scrypt hash for server-side configuration."""
    if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("维护口令不能为空或超过允许长度。")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=256 * 1024 * 1024)
    return f"$scrypt$32768$8$1${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        n, r, p, salt, expected = _password_parameters(encoded)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=256 * 1024 * 1024)
    except (ValueError, TypeError, UnicodeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def _configuration(settings):
    password_hash = getattr(settings, "maintenance_password_hash", "")
    actor = getattr(settings, "maintenance_actor", "")
    origin = getattr(settings, "maintenance_origin", "")
    try:
        _password_parameters(password_hash)
        parsed = urlsplit(origin)
        valid_origin = (isinstance(origin, str) and len(origin) <= 2048 and parsed.scheme == "https"
                        and bool(parsed.hostname) and parsed.username is None and parsed.password is None
                        and not parsed.path and not parsed.query and not parsed.fragment and parsed.port in {None, 443})
        valid_actor = isinstance(actor, str) and bool(actor.strip()) and actor == actor.strip() and len(actor) <= 1000 and actor != _BOOTSTRAP_ACTOR
        if not valid_origin or not valid_actor:
            raise ValueError()
    except (ValueError, TypeError, AttributeError, UnicodeError):
        _error(503, "maintenance_unavailable", "维护登录尚未配置，请联系维护者。")
    return {"password_hash": password_hash, "actor": actor, "origin": origin}


def _origin(request, configuration, *, write):
    origins = request.headers.getlist("origin")
    if len(origins) > 1 or (write and len(origins) != 1) or (origins and not hmac.compare_digest(origins[0].encode(), configuration["origin"].encode())):
        _error(403, "maintenance_origin", "维护请求必须来自已授权的同源页面。")
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        _error(403, "maintenance_origin", "维护请求必须来自已授权的同源页面。")


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _csrf(token):
    return _encode(hmac.new(token.encode("ascii"), b"workhunter-maintenance-csrf-v1", hashlib.sha256).digest())


def _request_token(request):
    token = request.cookies.get(COOKIE_NAME, "")
    return token if _TOKEN.fullmatch(token) else None


def _date(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _session(connection, token, configuration, now, *, bootstrap=False):
    if not token or (not bootstrap and token[0] != "s"):
        return None
    row = connection.execute("SELECT * FROM maintenance_sessions WHERE session_hash=?", (_digest(token),)).fetchone()
    if row is None or row["revoked_at"] is not None:
        return None
    created, expires = _date(row["created_at"]), _date(row["expires_at"])
    seconds = BOOTSTRAP_SECONDS if token[0] == "b" else SESSION_SECONDS
    expected_actor = _BOOTSTRAP_ACTOR if token[0] == "b" else configuration["actor"]
    if created is None or expires is None or created > now or expires <= now or expires > created + timedelta(seconds=seconds):
        return None
    if row["actor"] != expected_actor or not isinstance(row["csrf_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["csrf_hash"]) or not hmac.compare_digest(row["csrf_hash"], _digest(_csrf(token))):
        return None
    return row


def _check_csrf(request, row, token):
    values = request.headers.getlist("x-wh-csrf")
    if len(values) != 1 or len(values[0]) != 43 or not hmac.compare_digest(_digest(values[0]), row["csrf_hash"]):
        _error(403, "maintenance_csrf", "维护请求校验已失效，请重新打开维护页。")


def _public_session(row, token):
    authenticated = token[0] == "s"
    result = {"authenticated": authenticated, "csrf_token": _csrf(token), "expires_at": row["expires_at"]}
    if authenticated:
        result["actor"] = row["actor"]
    return result


def _insert_session(connection, kind, configuration, now):
    token = kind + "." + secrets.token_urlsafe(32)
    actor = _BOOTSTRAP_ACTOR if kind == "b" else configuration["actor"]
    seconds = BOOTSTRAP_SECONDS if kind == "b" else SESSION_SECONDS
    connection.execute("INSERT INTO maintenance_sessions(session_hash,csrf_hash,actor,created_at,expires_at) VALUES (?,?,?,?,?)",
                       (_digest(token), _digest(_csrf(token)), actor, now.isoformat(), (now + timedelta(seconds=seconds)).isoformat()))
    return _session(connection, token, configuration, now, bootstrap=True), token


def session_status(request: Request, settings):
    configuration = _configuration(settings)
    _origin(request, configuration, write=False)
    now, token = _now(), _request_token(request)
    with read_database(settings.db_path) as (connection, _):
        row = _session(connection, token, configuration, now, bootstrap=True)
        if row is not None:
            return _public_session(row, token), None
    with writer_transaction(settings.db_path) as (connection, _):
        # Only the anonymous auth bootstrap has GET-created state. Business data is untouched.
        connection.execute("DELETE FROM maintenance_sessions WHERE actor=? AND (expires_at<=? OR revoked_at IS NOT NULL)", (_BOOTSTRAP_ACTOR, now.isoformat()))
        count = connection.execute("SELECT COUNT(*) FROM maintenance_sessions WHERE actor=?", (_BOOTSTRAP_ACTOR,)).fetchone()[0]
        connection.execute("DELETE FROM maintenance_sessions WHERE session_hash IN (SELECT session_hash FROM maintenance_sessions WHERE actor=? ORDER BY created_at,session_hash LIMIT ?)", (_BOOTSTRAP_ACTOR, max(0, count - MAX_BOOTSTRAPS + 1)))
        row, token = _insert_session(connection, "b", configuration, now)
    return _public_session(row, token), token


def require_session(request: Request, settings, write=False) -> dict:
    """Trusted identity for protected maintenance reads and all preview/write calls."""
    configuration = _configuration(settings)
    _origin(request, configuration, write=write)
    token = _request_token(request)
    with read_database(settings.db_path) as (connection, _):
        row = _session(connection, token, configuration, _now())
        if row is None:
            _error(401, "maintenance_unauthorized", "请先登录维护页。")
        if write:
            _check_csrf(request, row, token)
        return {"session_id": row["session_hash"], "session_hash": row["session_hash"], "actor": row["actor"]}


def _failure_identifiers(configuration):
    return (_digest("maintenance-login:global"), _digest("maintenance-login:actor:" + configuration["actor"]))


def _blocked(connection, identifiers, now):
    for identifier in identifiers:
        row = connection.execute("SELECT blocked_until FROM maintenance_login_failures WHERE identifier_hash=?", (identifier,)).fetchone()
        until = _date(row["blocked_until"]) if row else None
        if until is not None and until > now:
            return True
    return False


def _record_failure(connection, identifiers, now):
    # Configuration changes cannot erase the global budget; only two current keys are retained.
    connection.execute("DELETE FROM maintenance_login_failures WHERE identifier_hash NOT IN (?,?)", identifiers)
    for identifier in identifiers:
        row = connection.execute("SELECT * FROM maintenance_login_failures WHERE identifier_hash=?", (identifier,)).fetchone()
        started = _date(row["window_started_at"]) if row else None
        fresh = started is None or started > now or started + timedelta(seconds=FAILURE_SECONDS) <= now
        started, attempts = (now, 1) if fresh else (started, row["attempts"] + 1)
        blocked = (now + timedelta(seconds=FAILURE_SECONDS)).isoformat() if attempts >= MAX_FAILURES else None
        connection.execute("INSERT INTO maintenance_login_failures(identifier_hash,attempts,window_started_at,last_attempt_at,blocked_until) VALUES (?,?,?,?,?) ON CONFLICT(identifier_hash) DO UPDATE SET attempts=excluded.attempts,window_started_at=excluded.window_started_at,last_attempt_at=excluded.last_attempt_at,blocked_until=excluded.blocked_until",
                           (identifier, attempts, started.isoformat(), now.isoformat(), blocked))


def login(request: Request, settings, password: str):
    configuration = _configuration(settings)
    _origin(request, configuration, write=True)
    token, now = _request_token(request), _now()
    identifiers = _failure_identifiers(configuration)
    with read_database(settings.db_path) as (connection, _):
        row = _session(connection, token, configuration, now, bootstrap=True)
        if row is None:
            _error(401, "maintenance_unauthorized", "请先重新打开维护页。")
        _check_csrf(request, row, token)
        blocked = _blocked(connection, identifiers, now)
    # Slow password hashing stays outside the shared writer transaction.
    if blocked:
        _error(429, "maintenance_login_failed", _FAILED_MESSAGE)
    valid = verify_password(password, configuration["password_hash"])
    failure = None
    with writer_transaction(settings.db_path) as (connection, _):
        now = _now()
        row = _session(connection, token, configuration, now, bootstrap=True)
        if row is None:
            _error(401, "maintenance_unauthorized", "请先重新打开维护页。")
        _check_csrf(request, row, token)
        if _blocked(connection, identifiers, now):
            failure = 429
        elif not valid:
            _record_failure(connection, identifiers, now)
            failure = 401
        else:
            connection.execute("UPDATE maintenance_sessions SET revoked_at=? WHERE session_hash=?", (now.isoformat(), row["session_hash"]))
            connection.execute("DELETE FROM maintenance_login_failures WHERE identifier_hash IN (?,?)", identifiers)
            count = connection.execute("SELECT COUNT(*) FROM maintenance_sessions WHERE actor<>?", (_BOOTSTRAP_ACTOR,)).fetchone()[0]
            connection.execute("DELETE FROM maintenance_sessions WHERE session_hash IN (SELECT session_hash FROM maintenance_sessions WHERE actor<>? ORDER BY created_at,session_hash LIMIT ?)", (_BOOTSTRAP_ACTOR, max(0, count - MAX_SESSION_RECORDS + 1)))
            row, new_token = _insert_session(connection, "s", configuration, now)
    # Raise after the transaction commits, otherwise the failed-attempt count would roll back.
    if failure is not None:
        _error(failure, "maintenance_login_failed", _FAILED_MESSAGE)
    return _public_session(row, new_token), new_token


def logout(request: Request, settings):
    configuration = _configuration(settings)
    _origin(request, configuration, write=True)
    token = _request_token(request)
    with writer_transaction(settings.db_path) as (connection, _):
        now = _now()
        row = _session(connection, token, configuration, now)
        if row is None:
            _error(401, "maintenance_unauthorized", "请先登录维护页。")
        _check_csrf(request, row, token)
        connection.execute("UPDATE maintenance_sessions SET revoked_at=? WHERE session_hash=?", (now.isoformat(), row["session_hash"]))
