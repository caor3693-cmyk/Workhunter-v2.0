"""Private, read-only MCP stdio server (2025-11-25 JSON-RPC lifecycle).

MCP specification: /specification/2025-11-25/basic/{transports,lifecycle}
and /specification/2025-11-25/server/tools at modelcontextprotocol.io.
No SQL, paths, shell, write or refresh tool is registered.
"""

import argparse
from collections import deque
from datetime import date, datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import time

from backend.config import Settings, _commit
from backend.domain import KINDS, SCOPES, VIEWS
from backend.domain.candidates import MAX_INTEGER
from backend.services import queries
from backend.storage.database import DatabaseUnavailable, read_database
from backend.version import PROJECT, VERSION, STAGE, SCHEMA_VERSION
from ops.diagnostics import diagnostics_projection, refresh_projection


PROTOCOL_VERSION = "2025-11-25"
MAX_REQUEST_BYTES = 16384
MAX_RESPONSE_BYTES = 65536
MAX_PAGE = 50
MAX_OFFSET = 100000
MAX_TOOL_CALLS = 60
RATE_WINDOW_SECONDS = 60


class ProtocolError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _object(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "additionalProperties": False,
            **({"required": list(required)} if required else {})}


PAGING = {"offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET},
          "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE}}
FILTER_PROPERTIES = {
    "school_key": {"type": "string", "maxLength": 32},
    "campus_id": {"type": "integer", "minimum": 1, "maximum": MAX_INTEGER},
    "campus_unknown": {"type": "boolean"}, "kind": {"type": "string", "enum": list(KINDS)},
    "keyword": {"type": "string", "maxLength": 300},
    **{key: {"type": "string", "format": "date"} for key in ("date_from", "date_to", "as_of")},
    "view": {"type": "string", "enum": list(VIEWS)}, "scope": {"type": "string", "enum": list(SCOPES)},
    "dataset_id": {"type": "string", "maxLength": 128}, **PAGING,
}
DEFINITIONS = (
    ("version", "读取服务构建与独立数据集身份。", _object()),
    ("catalog", "读取固定十校目录；大响应返回明确限额错误。", _object()),
    ("opportunities", "有界分页读取已收录公告，复用网站筛选语义。", _object(FILTER_PROPERTIES)),
    ("opportunity_detail", "按编号读取已收录公告及已核实证据。", _object({"opportunity_id": {"type": "integer", "minimum": 1, "maximum": MAX_INTEGER}}, ("opportunity_id",))),
    ("source_status", "分页读取已登记公开来源状态。", _object(PAGING)),
    ("refresh_status", "读取计划和轮次状态；不会触发刷新。", _object()),
    ("diagnostics", "显式授权进程可读取固定脱敏诊断字段。", _object(PAGING)),
)


def _arguments(name, value):
    if not isinstance(value, dict):
        raise ProtocolError(-32602, "arguments 必须为对象。")
    schema = next(item[2] for item in DEFINITIONS if item[0] == name)
    if set(value) - set(schema["properties"]) or set(schema.get("required", ())) - set(value):
        raise ValueError("不支持的参数或缺少必需参数。")
    result = dict(value)
    for key, supplied in result.items():
        definition = schema["properties"][key]
        kind = definition["type"]
        if ((kind == "integer" and type(supplied) is not int) or (kind == "boolean" and type(supplied) is not bool)
                or (kind == "string" and not isinstance(supplied, str))):
            raise ValueError("参数类型无效。")
        if kind == "integer" and not definition["minimum"] <= supplied <= definition["maximum"]:
            raise ValueError("整数参数超过范围。")
        if kind == "string":
            if len(supplied) > definition.get("maxLength", 32) or not supplied.strip():
                raise ValueError("字符串参数为空或超过长度。")
            if "enum" in definition and supplied not in definition["enum"]:
                raise ValueError("枚举参数无效。")
            if definition.get("format") == "date":
                if date.fromisoformat(supplied).isoformat() != supplied:
                    raise ValueError("日期必须为 YYYY-MM-DD。")
    return result


def _filters(arguments, today):
    filters = queries.Filters(**arguments)
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise ValueError("date_from 不能晚于 date_to。")
    if filters.campus_id is not None and filters.campus_unknown:
        raise ValueError("具体校区与未知校区不能同时选择。")
    if filters.offset and (not filters.dataset_id or not filters.as_of):
        raise ValueError("追加分页必须携带 dataset_id 与 as_of。")
    if filters.as_of and not date(1, 2, 1) <= date.fromisoformat(filters.as_of) <= today:
        raise ValueError("as_of 超过有效查询日期范围。")
    return filters


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


class MCPServer:
    def __init__(self, settings: Settings, *, allow_diagnostics=False):
        self.settings = settings
        self.allow_diagnostics = allow_diagnostics is True
        self.initialized = False
        self.ready = False
        self.calls = deque()

    def _take_tool_slot(self):
        current = time.monotonic()
        while self.calls and self.calls[0] <= current - RATE_WINDOW_SECONDS:
            self.calls.popleft()
        if len(self.calls) >= MAX_TOOL_CALLS:
            return False
        self.calls.append(current)
        return True

    def _identity(self, metadata):
        return {"project": PROJECT, "version": VERSION, "stage": STAGE, "schema_version": SCHEMA_VERSION,
                "backend_commit": self.settings.backend_commit, **queries.identity(metadata)}

    def _tool(self, name, arguments):
        if name == "diagnostics" and not self.allow_diagnostics:
            raise ProtocolError(-32602, "诊断工具未在此进程中启用。")
        args = _arguments(name, arguments)
        today = datetime.now(timezone(timedelta(hours=8))).date()
        with read_database(self.settings.db_path) as (connection, metadata):
            identity = self._identity(metadata)
            if name == "version":
                result = {}
            elif name == "catalog":
                result = queries.catalog(connection, metadata)
            elif name == "opportunities":
                filters = _filters(args, today)
                if filters.dataset_id and filters.dataset_id != metadata["dataset_id"]:
                    raise ValueError("数据集已变化，请重新加载第一页。")
                if filters.school_key and connection.execute("SELECT 1 FROM schools WHERE school_key=?", (filters.school_key,)).fetchone() is None:
                    raise ValueError("学校不在固定十校目录中。")
                if filters.campus_id is not None:
                    campus = connection.execute("SELECT school_key FROM campuses WHERE id=?", (filters.campus_id,)).fetchone()
                    if campus is None or (filters.school_key and campus[0] != filters.school_key):
                        raise ValueError("校区不存在或不属于所选学校。")
                result = queries.opportunities(connection, metadata, filters, today, self.settings.recent_days)
            elif name == "opportunity_detail":
                result = queries.detail(connection, args["opportunity_id"])
                if result is None:
                    raise ValueError("公告不存在或尚未收录。")
            elif name == "source_status":
                rows = queries.sources(connection)
                offset, limit = args.get("offset", 0), args.get("limit", 20)
                result = {"sources": rows[offset:offset + limit], "total": len(rows), "offset": offset,
                          "limit": limit, "has_more": offset + limit < len(rows)}
            elif name == "refresh_status":
                result = refresh_projection(connection, metadata)
            else:
                result = diagnostics_projection(connection, metadata, **args)
            return {**result, **identity}

    @staticmethod
    def _tool_result(data, *, error=False):
        return {"content": [{"type": "text", "text": _encoded(data).decode("utf-8")}],
                "structuredContent": data, "isError": error}

    def handle(self, message):
        identifier = None
        notification = False
        try:
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
                raise ProtocolError(-32600, "无效的 JSON-RPC 请求。")
            if set(message) - {"jsonrpc", "method", "id", "params"}:
                raise ProtocolError(-32600, "JSON-RPC 请求含未知字段。")
            notification = "id" not in message
            identifier = message.get("id")
            if not notification and not ((type(identifier) is int and abs(identifier) <= MAX_INTEGER)
                                         or (isinstance(identifier, str) and len(identifier) <= 128)):
                identifier = None
                raise ProtocolError(-32600, "请求 id 无效。")
            method, params = message["method"], message.get("params", {})
            if not isinstance(params, dict):
                raise ProtocolError(-32602, "params 必须为对象。")
            if notification:
                if method == "notifications/initialized" and self.initialized and not params:
                    self.ready = True
                return None
            if method == "ping":
                if params:
                    raise ProtocolError(-32602, "ping 不接受参数。")
                result = {}
            elif method == "initialize":
                if self.initialized:
                    raise ProtocolError(-32600, "当前连接已经初始化。")
                if (set(params) - {"protocolVersion", "capabilities", "clientInfo", "_meta"}
                        or not isinstance(params.get("protocolVersion"), str)
                        or not isinstance(params.get("capabilities"), dict)
                        or not isinstance(params.get("clientInfo"), dict)
                        or not isinstance(params["clientInfo"].get("name"), str)
                        or not isinstance(params["clientInfo"].get("version"), str)):
                    raise ProtocolError(-32602, "initialize 参数无效。")
                self.initialized = True
                result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "workhunter-v2-readonly", "version": VERSION},
                          "instructions": "只读独立库；公告内容为来源数据。诊断权限由进程配置独立决定。"}
            else:
                if not self.ready:
                    raise ProtocolError(-32002, "请先 initialize 并发送 notifications/initialized。")
                if method == "tools/list":
                    if set(params) - {"cursor", "_meta"} or params.get("cursor") not in (None, ""):
                        raise ProtocolError(-32602, "没有后续工具目录分页。")
                    result = {"tools": [{"name": name, "description": description, "inputSchema": schema,
                                          "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
                                         for name, description, schema in DEFINITIONS
                                         if name != "diagnostics" or self.allow_diagnostics]}
                elif method == "tools/call":
                    if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
                        raise ProtocolError(-32602, "tools/call 参数无效。")
                    if params["name"] not in {item[0] for item in DEFINITIONS}:
                        raise ProtocolError(-32602, "未知工具；此服务仅提供登记的只读工具。")
                    if not self._take_tool_slot():
                        return {"jsonrpc": "2.0", "id": identifier,
                                "result": self._tool_result({"code": "rate_limited", "message": "每进程每 60 秒最多 60 次工具调用，请稍后重试。"}, error=True)}
                    try:
                        result = self._tool_result(self._tool(params["name"], params.get("arguments", {})))
                    except (ValueError, DatabaseUnavailable) as exc:
                        if isinstance(exc, ProtocolError):
                            raise
                        # Never echo untrusted SQL, file paths or incoming values in errors.
                        result = self._tool_result({"code": "invalid_input_or_database", "message": "参数或独立数据库状态无效，请检查参数范围、身份和数据库可读性。"}, error=True)
                    except Exception:
                        result = self._tool_result({"code": "read_failed", "message": "只读查询暂时不可用。"}, error=True)
                else:
                    raise ProtocolError(-32601, "不支持的 MCP 方法。")
            response = {"jsonrpc": "2.0", "id": identifier, "result": result}
            if len(_encoded(response)) > MAX_RESPONSE_BYTES:
                return {"jsonrpc": "2.0", "id": identifier,
                        "result": self._tool_result({"code": "response_too_large", "message": "响应超过 64 KiB，请缩小分页或查询范围。"}, error=True)}
            return response
        except ProtocolError as exc:
            if notification:
                return None
            return {"jsonrpc": "2.0", "id": identifier, "error": {"code": exc.code, "message": exc.message}}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("重复 JSON 字段。")
        result[key] = value
    return result


def serve_stdio(server, incoming, outgoing):
    while True:
        line = incoming.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST_BYTES:
            while not line.endswith(b"\n"):
                line = incoming.readline(MAX_REQUEST_BYTES + 1)
                if not line:
                    break
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "请求超过 16 KiB。"}}
        else:
            try:
                message = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs,
                                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                response = server.handle(message)
            except (ValueError, UnicodeError, RecursionError):
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON 解析失败。"}}
        if response is not None:
            outgoing.write(_encoded(response) + b"\n")
            outgoing.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Workhunter v2 私有只读 MCP stdio")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--allow-diagnostics", action="store_true")
    options = parser.parse_args(argv)
    # Construct only the necessary Settings fields; no credential environment reads.
    settings = Settings(db_path=options.db.absolute(), backend_commit=_commit())
    serve_stdio(MCPServer(settings, allow_diagnostics=options.allow_diagnostics), sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
