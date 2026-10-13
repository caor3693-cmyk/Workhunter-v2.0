"""MCP protocol, read-only and redaction tests over temporary fixture databases."""

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from backend.config import Settings
from backend.storage.database import initialize_database
from ops.mcp import MCPServer, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, serve_stdio


def request(method, params=None, identifier=1):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}


def ready(server):
    result = server.handle(request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                  "clientInfo": {"name": "test", "version": "1"}}))
    assert result["result"]["protocolVersion"] == "2025-11-25"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return server


def call(server, name, arguments=None):
    return server.handle(request("tools/call", {"name": name, "arguments": arguments or {}}))


@pytest.fixture
def setup(tmp_path):
    database = tmp_path / "fixture.sqlite3"
    initialize_database(database, fixture=True)
    settings = Settings(db_path=database, backend_commit="test-sha", maintenance_actor="maintainer",
                        maintenance_password_hash="secret-hash", service_token="secret-token")
    return database, settings


def test_protocol_lifecycle_unknown_methods_and_tool_allowlist(setup):
    _, settings = setup
    server = MCPServer(settings)
    assert server.handle(request("tools/list"))["error"]["code"] == -32002
    ready(server)
    listing = server.handle(request("tools/list"))["result"]["tools"]
    assert {item["name"] for item in listing} == {"version", "catalog", "opportunities", "opportunity_detail", "source_status", "refresh_status"}
    assert all(item["annotations"]["readOnlyHint"] for item in listing)
    for name in ("refresh", "sql", "shell", "write", "restore", "maintenance", "diagnostics"):
        assert "error" in call(server, name)
    assert server.handle(request("resources/read"))["error"]["code"] == -32601
    assert server.handle(request("tools/list", {"cursor": "arbitrary"}))["error"]["code"] == -32602
    assert server.handle(request("initialize", {}))["error"]["code"] == -32600


def test_queries_share_identity_and_never_mutate_database(setup):
    database, settings = setup
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    server = ready(MCPServer(settings, allow_diagnostics=True))
    for name in ("version", "catalog", "opportunities", "source_status", "diagnostics"):
        response = call(server, name)
        data = response["result"]["structuredContent"]
        assert response["result"]["isError"] is False
        assert data["project"] == "Workhunter-v2.0"
        assert data["backend_commit"] == "test-sha"
        assert data["data_mode"] == "isolated_fixture"
        assert data["dataset_id"].startswith("fixture-ds-")
        assert len(json.dumps(response).encode()) <= MAX_RESPONSE_BYTES
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("arguments", [{"limit": 51}, {"limit": True}, {"offset": -1}, {"offset": 1},
                                      {"sql": "DELETE FROM opportunities"}, {"db": "private-path"},
                                      {"campus_unknown": "true"}, {"date_from": "2026-02-30"},
                                      {"date_from": "2026-10-14", "date_to": "2026-10-13"},
                                      {"view": "all"}, {"keyword": "x" * 301}, {"campus_id": 999999999},
                                      {"dataset_id": "wrong"}, {"as_of": "9999-12-31"},
                                      {"school_key": "missing"}])
def test_input_bounds_and_dataset_boundary(setup, arguments):
    _, settings = setup
    response = call(ready(MCPServer(settings)), "opportunities", arguments)
    assert response["result"]["isError"] is True


def test_source_pagination_is_bounded(setup):
    _, settings = setup
    server = ready(MCPServer(settings))
    data = call(server, "source_status", {"limit": 2})["result"]["structuredContent"]
    assert len(data["sources"]) == 2 and data["total"] == 10 and data["has_more"]
    second = call(server, "source_status", {"offset": 2, "limit": 2})["result"]["structuredContent"]
    assert {item["source_key"] for item in data["sources"]}.isdisjoint(item["source_key"] for item in second["sources"])


def test_diagnostics_only_fixed_columns_and_enum_categories(setup):
    database, settings = setup
    secret = "token=secret-user http://private.invalid C:/credentials/private.txt"
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO runs(id,trigger,started_at,status,scope_json,result_json,completeness) VALUES (?,?,?,?,?,?,?)",
                           (secret, secret, secret, secret, json.dumps({"password": secret}), json.dumps({"headers": secret}), secret))
        connection.execute("INSERT INTO processing_tasks(source_key,task_identity,task_kind,budget_json,status) VALUES ('scut_homepage',?,'detail','{}',?)", (secret, secret))
    server = ready(MCPServer(settings, allow_diagnostics=True))
    response = call(server, "diagnostics")
    text = json.dumps(response)
    assert secret not in text and "private.invalid" not in text and "secret-hash" not in text and "secret-token" not in text
    data = response["result"]["structuredContent"]
    assert data["runs"]["items"][0]["run_id"] is None
    assert data["runs"]["items"][0]["status"] == "unknown"
    assert data["processing_task_counts"]["unknown"] == 1
    listing = server.handle(request("tools/list"))["result"]["tools"]
    assert "diagnostics" in {item["name"] for item in listing}


def test_large_response_returns_explicit_error_without_partial_payload(setup):
    database, settings = setup
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE schools SET scope_note=?", ("x" * MAX_RESPONSE_BYTES,))
    response = call(ready(MCPServer(settings)), "catalog")
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["code"] == "response_too_large"
    assert len(json.dumps(response).encode()) < MAX_RESPONSE_BYTES


def test_stdio_parse_errors_notifications_and_oversized_input_do_not_break_stream(setup):
    _, settings = setup
    messages = [b"not-json\n", b'{"jsonrpc":"2.0","jsonrpc":"2.0"}\n',
                b"x" * (MAX_REQUEST_BYTES + 20) + b"\n",
                json.dumps(request("initialize", {"protocolVersion": "old", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})).encode() + b"\n",
                b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
                json.dumps(request("tools/call", {"name": "version"})).encode() + b"\n"]
    incoming, outgoing = io.BytesIO(b"".join(messages)), io.BytesIO()
    serve_stdio(MCPServer(settings), incoming, outgoing)
    replies = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert len(replies) == 5
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["error"]["code"] == -32700
    assert replies[2]["error"]["code"] == -32600
    assert replies[-1]["result"]["structuredContent"]["project"] == "Workhunter-v2.0"


def test_real_stdio_subprocess_reads_only_configured_store_and_stdout_is_protocol(setup):
    database, settings = setup
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    messages = [request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}),
                {"jsonrpc": "2.0", "method": "notifications/initialized"}, request("tools/list"),
                request("tools/call", {"name": "version"}), request("tools/call", {"name": "refresh"})]
    environment = dict(os.environ, WH_MAINTENANCE_PASSWORD_HASH="must-not-appear", WH_API_SERVICE_TOKEN="must-not-appear")
    result = subprocess.run([sys.executable, "-m", "ops.mcp", "--db", str(database)],
                            input=b"\n".join(json.dumps(item).encode() for item in messages) + b"\n",
                            capture_output=True, timeout=15, env=environment)
    assert result.returncode == 0
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == 4
    assert replies[-1]["error"]["code"] == -32602
    assert b"must-not-appear" not in result.stdout + result.stderr
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_missing_database_does_not_create_files(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    server = ready(MCPServer(Settings(db_path=missing, backend_commit="test")))
    assert call(server, "version")["result"]["isError"]
    assert not missing.exists()


def test_refresh_projection_uses_shared_status_and_excludes_private_ledger(setup, monkeypatch):
    from backend.services import scheduling
    _, settings = setup
    private = "http://private.invalid/token-secret C:/private/db.sqlite3"
    identifier = "run-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    monkeypatch.setattr(scheduling, "schedule_projection", lambda *args: {
        "enabled": True, "status": "overdue", "next_run_at": None, "overdue_since": "2026-10-13T08:00:00+08:00",
        "natural_run_count": None, "continuous_days": None,
        "ledger": [{"command": private}], "host_registration": {"command": private},
        "last_execution": {"status": "finished", "business_status": "partial", "trigger": "scheduled",
                           "triggered_at": "2026-10-13T02:00:00+08:00", "finished_at": "2026-10-13T02:05:00+08:00",
                           "process_exit_code": 0, "host_task_exit_code": None, "run_ids": [identifier, private],
                           "result_json": private, "backup": {"path": private}}})
    response = call(ready(MCPServer(settings)), "refresh_status")
    data = response["result"]["structuredContent"]
    assert data["status"] == "overdue" and data["next_run_at"] is None
    assert data["natural_run_count"] is None and data["continuous_days"] is None
    assert data["last_execution"]["status"] == "finished"
    assert data["last_execution"]["run_ids"] == [identifier]
    assert data["last_execution"]["process_exit_code"] == 0
    assert private not in json.dumps(response)


def test_read_call_rate_limit_is_bounded_and_window_expires(setup, monkeypatch):
    from ops import mcp
    _, settings = setup
    monkeypatch.setattr(mcp, "MAX_TOOL_CALLS", 2)
    current = [0.0]
    monkeypatch.setattr(mcp.time, "monotonic", lambda: current[0])
    server = ready(MCPServer(settings))
    assert call(server, "version")["result"]["isError"] is False
    assert call(server, "version")["result"]["isError"] is False
    response = call(server, "version")
    assert response["result"]["structuredContent"]["code"] == "rate_limited"
    assert len(server.calls) == 2
    current[0] = 60.0
    assert call(server, "version")["result"]["isError"] is False
    assert len(server.calls) == 1


@pytest.mark.parametrize("message", [[], {"jsonrpc": "1.0", "id": 1, "method": "ping"},
                                     {"jsonrpc": "2.0", "id": True, "method": "ping"},
                                     {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []},
                                     {"jsonrpc": "2.0", "id": 1, "method": "ping", "path": "secret"}])
def test_invalid_protocol_envelopes(setup, message):
    _, settings = setup
    assert "error" in MCPServer(settings).handle(message)
