"""Only `init` creates a database; `serve` verifies it before binding a port."""

import argparse
import ipaddress
import json
from pathlib import Path
import sys

from backend.config import Settings
from backend.storage.database import DatabaseUnavailable, initialize_database, read_database
from backend.worker import refresh_unavailable


def main() -> int:
    parser = argparse.ArgumentParser(description="Workhunter v2 隔离开发服务")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="显式初始化独立新库；未知旧库不会被改写")
    init.add_argument("--db", type=Path)
    serve = commands.add_parser("serve", help="校验新库后启动 API")
    serve.add_argument("--db", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    refresh = commands.add_parser("refresh", help="S0 尚未实现；返回明确失败，不伪造采集")
    refresh.add_argument("--db", type=Path)
    options = parser.parse_args()
    if options.command == "refresh":
        return refresh_unavailable()
    settings = Settings.from_env(options.db)
    try:
        if options.command == "init":
            print(json.dumps(initialize_database(settings.db_path), ensure_ascii=False))
            return 0
        if not settings.service_token:
            try:
                loopback = ipaddress.ip_address(options.host).is_loopback
            except ValueError:
                loopback = options.host == "localhost"
            if not loopback:
                print("未配置 WH_API_SERVICE_TOKEN 时仅允许绑定环回地址。", file=sys.stderr)
                return 2
        if not 1 <= options.port <= 65535:
            print("端口必须在 1—65535 之间。", file=sys.stderr)
            return 2
        with read_database(settings.db_path):
            pass
        import uvicorn
        from backend.api.app import create_app
        uvicorn.run(create_app(settings), host=options.host, port=options.port, proxy_headers=False)
        return 0
    except (DatabaseUnavailable, OSError, ValueError) as exception:
        print(str(exception), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
