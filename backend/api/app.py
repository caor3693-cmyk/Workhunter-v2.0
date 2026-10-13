from dataclasses import fields
from datetime import date, datetime, timezone, timedelta
import hmac
import ipaddress
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.config import Settings
from backend.domain import KINDS, SCOPES, VIEWS
from backend.domain.candidates import MAX_INTEGER
from backend.services import queries
from backend.storage.database import DatabaseUnavailable, read_database
from backend.storage.write import WriterBusy
from backend.version import PROJECT, STAGE, VERSION


def _error(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _filters(request: Request, query_today: date) -> queries.Filters:
    allowed = {field.name for field in fields(queries.Filters)}
    unknown = set(request.query_params) - allowed
    if unknown:
        _error(422, "unsupported_parameter", "不支持的筛选参数：" + "、".join(sorted(unknown)))
    duplicate = [key for key in request.query_params if len(request.query_params.getlist(key)) > 1]
    if duplicate:
        _error(422, "duplicate_parameter", "筛选参数不能重复：" + "、".join(sorted(duplicate)))
    raw = {key: value.strip() for key, value in request.query_params.items()}
    optional = {key: raw.get(key) or None for key in ("school_key", "kind", "keyword", "date_from", "date_to", "dataset_id", "as_of")}
    if optional['keyword'] and len(optional['keyword']) > 300:
        _error(422, 'invalid_keyword', 'keyword 不能超过 300 字。')
    if optional['dataset_id'] and len(optional['dataset_id']) > 128:
        _error(422, 'invalid_dataset', 'dataset_id 超过允许长度。')
    for key in ("date_from", "date_to", "as_of"):
        if optional[key]:
            try:
                parsed = date.fromisoformat(optional[key])
                if parsed.isoformat() != optional[key]:
                    raise ValueError()
            except ValueError:
                _error(422, "invalid_date", f"{key} 必须为有效的 YYYY-MM-DD 日期。")
    if optional["date_from"] and optional["date_to"] and optional["date_from"] > optional["date_to"]:
        _error(422, "invalid_date_range", "date_from 不能晚于 date_to。")
    if optional["kind"] and optional["kind"] not in KINDS:
        _error(422, "invalid_kind", "kind 必须为已支持的招聘类型。")
    view, scope = raw.get("view") or "recent", raw.get("scope") or "electrical"
    if view not in VIEWS or scope not in SCOPES:
        _error(422, "invalid_view_or_scope", "view 或 scope 不属于支持的范围。")
    numbers = {}
    for key, default, minimum, maximum in (("offset", 0, 0, MAX_INTEGER), ("limit", 20, 1, 100), ("campus_id", None, 1, MAX_INTEGER)):
        text = raw.get(key)
        if not text:
            numbers[key] = default
            continue
        try:
            value = int(text)
            if str(value) != text or value < minimum or (maximum is not None and value > maximum):
                raise ValueError()
        except ValueError:
            _error(422, "invalid_number", f"{key} 必须为允许范围内的整数。")
        numbers[key] = value
    unknown_campus = raw.get("campus_unknown") or "false"
    if unknown_campus not in {"true", "false"}:
        _error(422, "invalid_campus_unknown", "campus_unknown 必须为 true 或 false。")
    if numbers["campus_id"] is not None and unknown_campus == "true":
        _error(422, "campus_conflict", "不能同时选择具体校区和未知校区。")
    if numbers["offset"] > 0 and not optional["dataset_id"]:
        _error(422, "dataset_required", "追加分页必须携带第一页返回的 dataset_id。")
    if numbers['offset'] > 0 and not optional['as_of']:
        _error(422, 'as_of_required', '追加分页必须携带第一页返回的 as_of 查询日期。')
    if optional['as_of']:
        anchor = date.fromisoformat(optional['as_of'])
        if anchor > query_today or anchor < date(1, 2, 1):
            _error(422, 'invalid_as_of', 'as_of 不能晚于当前北京时间日期，且必须可构造完整查询窗口。')
    return queries.Filters(**optional, **numbers, view=view, scope=scope, campus_unknown=unknown_campus == "true")


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or Settings.from_env()
    app = FastAPI(title=PROJECT, version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = configuration

    @app.middleware("http")
    async def service_boundary(request: Request, call_next):
        started_at = time.time_ns() // 1_000_000
        started = time.perf_counter()
        if configuration.service_token:
            supplied = request.headers.get("authorization", "")
            expected = "Bearer " + configuration.service_token
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                return JSONResponse(status_code=401, content={"detail": {"code": "service_unauthorized", "message": "开发 API 仅允许已授权的同源代理访问。"}}, headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
        elif not request.client or not _loopback(request.client.host):
            return JSONResponse(status_code=403, content={"detail": {"code": "loopback_only", "message": "未配置服务令牌时仅允许本机环回访问。"}}, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f"api;dur={elapsed:.3f}"
        response.headers["X-WH-API-Started-At"] = str(started_at)
        response.headers["X-WH-API-Ended-At"] = str(time.time_ns() // 1_000_000)
        return response

    @app.exception_handler(DatabaseUnavailable)
    async def unavailable_handler(request: Request, exception: DatabaseUnavailable):
        return JSONResponse(status_code=503, content={"detail": {"code": "database_unavailable", "message": str(exception)}}, headers={"Cache-Control": "no-store"})

    @app.exception_handler(WriterBusy)
    async def writer_busy_handler(request: Request, exception: WriterBusy):
        return JSONResponse(status_code=503, content={"detail": {"code": "maintenance_busy", "message": str(exception)}}, headers={"Cache-Control": "no-store"})

    def build_identity(metadata):
        return {"project": PROJECT, "version": VERSION, "backend_commit": configuration.backend_commit, "stage": STAGE, **queries.identity(metadata)}

    def today():
        return datetime.now(timezone(timedelta(hours=8))).date()

    @app.get("/health")
    def health():
        with read_database(configuration.db_path) as (_, metadata):
            return {"status": "ok", "database": "readable", **build_identity(metadata)}

    @app.get("/version")
    def version():
        with read_database(configuration.db_path) as (_, metadata):
            return build_identity(metadata)

    @app.get("/api/catalog")
    def catalog():
        with read_database(configuration.db_path) as (connection, metadata):
            return queries.catalog(connection, metadata)

    @app.get("/api/opportunities")
    def opportunities(request: Request):
        current_date = today()
        filters = _filters(request, current_date)
        with read_database(configuration.db_path) as (connection, metadata):
            if filters.dataset_id and filters.dataset_id != metadata["dataset_id"]:
                _error(409, "dataset_changed", "数据集已变化，请保持已提交条件并重新加载第一页。")
            if filters.school_key and connection.execute("SELECT 1 FROM schools WHERE school_key=?", (filters.school_key,)).fetchone() is None:
                _error(404, "school_not_found", "所选学校不在固定十校目录中。")
            if filters.campus_id is not None:
                campus = connection.execute("SELECT school_key FROM campuses WHERE id=?", (filters.campus_id,)).fetchone()
                if campus is None:
                    _error(404, "campus_not_found", "所选校区尚未在目录中登记。")
                if filters.school_key and campus["school_key"] != filters.school_key:
                    _error(422, "school_campus_conflict", "所选校区不属于当前学校。")
            return queries.opportunities(connection, metadata, filters, current_date, configuration.recent_days)

    @app.get("/api/opportunities/{opportunity_id}")
    def opportunity_detail(opportunity_id: int):
        if not 1 <= opportunity_id <= MAX_INTEGER:
            _error(422, "invalid_opportunity", "公告编号必须为允许范围内的正整数。")
        with read_database(configuration.db_path) as (connection, metadata):
            result = queries.detail(connection, opportunity_id)
            if result is None:
                _error(404, "opportunity_not_found", "公告不存在，或尚未收录。")
            return {**queries.identity(metadata), **result}

    @app.get("/api/sources/status")
    def source_status():
        with read_database(configuration.db_path) as (connection, metadata):
            return {**build_identity(metadata), "sources": queries.sources(connection), "schedule": public_schedule(connection, metadata)}

    def public_schedule(connection, metadata):
        from backend.services.scheduling import schedule_projection
        projection = schedule_projection(connection, metadata)
        # Public state contains no host action, filesystem path or diagnostic text.
        allowed = ('enabled', 'status', 'interval_hours', 'next_run_at', 'overdue_since',
                   'natural_run_count', 'observed_natural_days', 'continuous_days', 'observed_at')
        result = {key: projection.get(key) for key in allowed}
        last = projection.get('last_execution')
        if last:
            result['last_execution'] = {key: last.get(key) for key in
                ('slot_at', 'triggered_at', 'finished_at', 'run_id', 'run_ids', 'status', 'business_status',
                 'business_completeness', 'process_exit_code', 'process_exit_scope', 'scheduler_exit_code',
                 'host_task_exit_code', 'trigger', 'backup_status')}
            backup = last.get('backup')
            if isinstance(backup, dict) and backup.get('status') in {'complete', 'failed'}:
                result['last_execution']['backup_status'] = backup['status']
        return {**build_identity(metadata), **result}

    @app.get('/api/refresh/status')
    def refresh_status():
        with read_database(configuration.db_path) as (connection, metadata):
            return public_schedule(connection, metadata)

    @app.get("/api/updates/summary")
    def summary():
        with read_database(configuration.db_path) as (connection, metadata):
            return queries.summary(connection, metadata, today(),recent_days=configuration.recent_days)

    from backend.api.auth import register_auth_routes
    from backend.api.maintenance import register_maintenance_routes
    register_auth_routes(app, configuration)
    register_maintenance_routes(app, configuration)
    return app


app = create_app()
