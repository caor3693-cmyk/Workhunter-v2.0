"""Only `init` creates a database; `serve` verifies it before binding a port."""

import argparse
import ipaddress
import json
from pathlib import Path
import sys

from backend.config import Settings
from backend.storage.database import DatabaseUnavailable, initialize_database, read_database


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Workhunter v2 隔离开发服务")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="显式初始化独立新库；未知旧库不会被改写")
    init.add_argument("--db", type=Path)
    init.add_argument('--fixture', action='store_true', help='显式独立隔离样例库，禁止与真实库混用')
    migrate = commands.add_parser('migrate', help='显式迁移已识别 v2 新库，先保留可恢复备份')
    migrate.add_argument('--db', type=Path)
    serve = commands.add_parser("serve", help="校验新库后启动 API")
    serve.add_argument("--db", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    refresh = commands.add_parser("refresh", help="手工有限刷新华工/广工公开栏目；范围与失败如实记录")
    refresh.add_argument("--db", type=Path)
    refresh.add_argument('--school', choices=['scut','gdut','ncepu','shiep','neepu','csust','ctgu','gzhu','hnu','csu'], action='append')
    refresh.add_argument('--pages', type=int, default=2)
    refresh.add_argument('--details', type=int, default=12)
    refresh.add_argument('--resume', help='已有部分轮次 ID，续跑已保存游标/详情任务')
    options = parser.parse_args(argv)
    settings = Settings.from_env(options.db)
    try:
        if options.command == "init":
            print(json.dumps(initialize_database(settings.db_path, fixture=options.fixture), ensure_ascii=False))
            return 0
        if options.command == 'migrate':
            from backend.storage.migrations import migrate_database
            print(json.dumps(migrate_database(settings.db_path), ensure_ascii=False))
            return 0
        if options.command == 'refresh':
            with read_database(settings.db_path):
                pass
            if not 1 <= options.pages <= 10 or not 0 <= options.details <= 100:
                raise ValueError('列表页预算为 1—10，核心详情预算为 0—100。')
            from backend.config import ROOT
            from backend.services.discovery import register_sources, refresh_sources
            from backend.sources import Fetcher
            schools = json.loads((ROOT / 'config' / 'schools.json').read_text(encoding='utf-8'))
            configs = register_sources(settings.db_path, schools)
            result = refresh_sources(settings.db_path, configs,
                school_keys=tuple(options.school or ['scut','gdut']), page_budget=options.pages,
                detail_budget=options.details, resume_run_id=options.resume,
                transport=lambda config: Fetcher(max_requests=options.pages + options.details + 2, max_seconds=120))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['status'] != 'failed' else 1
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
    except (DatabaseUnavailable, OSError, ValueError, RuntimeError) as exception:
        print(str(exception), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
