"""Business-authenticated maintenance routes; no caller-controlled database paths."""
import json

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.services import maintenance
from backend.services.auth import require_session
from backend.sources.transport import FetchError
from backend.storage.write import WriteConflict, WriterBusy


def _invoke(function,*args,**kwargs):
    try:return JSONResponse(function(*args,**kwargs),headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    except maintenance.MaintenanceError as exc:
        raise HTTPException(exc.status,detail={'code':exc.code,'message':str(exc)}) from exc
    except WriteConflict as exc:
        raise HTTPException(409,detail={'code':'maintenance_conflict','message':str(exc)}) from exc
    except WriterBusy as exc:
        raise HTTPException(409,detail={'code':'maintenance_busy','message':'另一项写入正在提交，请稍后重试。'}) from exc
    except FetchError as exc:
        raise HTTPException(422,detail={'code':'maintenance_material_unavailable','message':str(exc)}) from exc
    except (ValueError,TypeError,KeyError) as exc:
        raise HTTPException(422,detail={'code':'maintenance_input','message':'材料或操作输入无效，请重新核对预览。'}) from exc


async def _body(request):
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>524_288:
            raise HTTPException(413,detail={'code':'maintenance_body_size','message':'维护请求超过允许大小。'})
        body.extend(chunk)
    try:return json.loads(body)
    except (ValueError,TypeError):
        raise HTTPException(422,detail={'code':'maintenance_input','message':'维护请求必须为有效 JSON。'})


def register_maintenance_routes(app,settings):
    @app.post('/api/admin/materials/preview')
    async def material_preview(request: Request):
        principal=await run_in_threadpool(require_session,request,settings,write=True)
        payload=await _body(request)
        return await run_in_threadpool(_invoke,maintenance.preview_materials,settings,principal,payload)

    @app.post('/api/admin/operations/commit')
    async def operation_commit(request: Request):
        principal=await run_in_threadpool(require_session,request,settings,write=True)
        payload=await _body(request)
        return await run_in_threadpool(_invoke,maintenance.commit_operation,settings,principal,payload)

    @app.post('/api/admin/operations/{operation_id}/revert-preview')
    async def revert_preview(operation_id: str,request: Request):
        principal=await run_in_threadpool(require_session,request,settings,write=True)
        payload=await _body(request)
        return await run_in_threadpool(_invoke,maintenance.preview_revert,settings,principal,operation_id,payload)

    @app.post('/api/admin/operations/{operation_id}/revert')
    async def operation_revert(operation_id: str,request: Request):
        principal=await run_in_threadpool(require_session,request,settings,write=True)
        payload=await _body(request)
        return await run_in_threadpool(_invoke,maintenance.commit_operation,settings,principal,payload,expected_revert=operation_id)

    @app.get('/api/admin/operations')
    def operations(request: Request,environment: str='real',limit: int=Query(20,ge=1,le=100),before: str|None=None):
        principal=require_session(request,settings)
        return _invoke(maintenance.list_operations,settings,principal,environment=environment,limit=limit,before=before)

    @app.get('/api/admin/tasks')
    def tasks(request: Request,environment: str='real',limit: int=Query(20,ge=1,le=100),before: int|None=Query(None,ge=1)):
        principal=require_session(request,settings)
        return _invoke(maintenance.list_tasks,settings,principal,environment=environment,limit=limit,before=before)

    @app.post('/api/admin/tasks/{task_id}/retry-preview')
    async def task_retry(task_id: int,request: Request):
        principal=await run_in_threadpool(require_session,request,settings,write=True)
        payload=await _body(request)
        return await run_in_threadpool(_invoke,maintenance.retry_task_preview,settings,principal,task_id,payload)

    @app.get('/api/admin/opportunities/{opportunity_id}')
    def opportunity(opportunity_id: int,request: Request,environment: str='real'):
        principal=require_session(request,settings)
        return _invoke(maintenance.read_opportunity,settings,principal,opportunity_id,environment=environment)

    @app.get('/api/admin/opportunities/{opportunity_id}/history')
    def opportunity_history(opportunity_id: int,request: Request,environment: str='real'):
        principal=require_session(request,settings)
        return _invoke(maintenance.read_opportunity,settings,principal,opportunity_id,environment=environment,history=True)
