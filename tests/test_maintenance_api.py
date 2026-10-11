"""Protected maintenance routes use the actual business session boundary."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from backend.api.auth import register_auth_routes
from backend.api.maintenance import register_maintenance_routes
from backend.services.auth import hash_password
from backend.storage.database import DatabaseUnavailable
from test_ingestion import snapshot
from test_maintenance import maintenance_setup, request, commit_request


@pytest.fixture
def api_setup(maintenance_setup):
    settings,_=maintenance_setup
    settings.maintenance_password_hash=hash_password('isolated-test-password')
    settings.maintenance_actor='synthetic-maintainer'
    settings.maintenance_origin='https://maintenance.example'
    app=FastAPI()
    @app.exception_handler(DatabaseUnavailable)
    def unavailable(request,exc):return JSONResponse({'detail':{'code':'database_unavailable','message':'数据库不可用。'}},status_code=503)
    register_auth_routes(app,settings);register_maintenance_routes(app,settings)
    return settings,app


def logged_in(app):
    client=TestClient(app,base_url='https://maintenance.example')
    bootstrap=client.get('/api/admin/session').json()
    login=client.post('/api/admin/session/login',json={'password':'isolated-test-password'},
        headers={'Origin':'https://maintenance.example','X-WH-CSRF':bootstrap['csrf_token']})
    assert login.status_code==200
    return client,{'Origin':'https://maintenance.example','X-WH-CSRF':login.json()['csrf_token']}


@pytest.mark.parametrize('method,path',[
    ('get','/api/admin/operations'),('get','/api/admin/tasks'),
    ('get','/api/admin/opportunities/1?environment=isolated'),('get','/api/admin/opportunities/1/history?environment=isolated'),
    ('post','/api/admin/materials/preview'),('post','/api/admin/operations/commit'),
    ('post','/api/admin/operations/unknown/revert-preview'),('post','/api/admin/operations/unknown/revert'),
    ('post','/api/admin/tasks/1/retry-preview'),
])
def test_all_maintenance_routes_require_business_login(api_setup,method,path):
    settings,app=api_setup;before=snapshot(settings.acceptance_db_path)
    client=TestClient(app,base_url='https://maintenance.example')
    result=getattr(client,method)(path,**({'json':{},'headers':{'Origin':'https://maintenance.example'}} if method=='post' else {}))
    assert result.status_code==401 and result.json()['detail']['code']=='maintenance_unauthorized'
    assert snapshot(settings.acceptance_db_path)==before


def test_full_material_preview_commit_history_and_revert_use_real_auth_with_isolated_facts(api_setup):
    settings,app=api_setup;client,headers=logged_in(app)
    preview=client.post('/api/admin/materials/preview',json=request(),headers=headers)
    assert preview.status_code==200 and preview.headers['cache-control']=='no-store'
    binding=commit_request(preview.json())
    assert snapshot(settings.acceptance_db_path)['rows']==[]
    wrong=client.post('/api/admin/operations/commit',json=binding,headers={**headers,'X-WH-CSRF':'x'*43})
    assert wrong.status_code==403 and snapshot(settings.acceptance_db_path)['rows']==[]
    committed=client.post('/api/admin/operations/commit',json=binding,headers=headers)
    assert committed.status_code==200 and committed.json()['new']==1
    record=client.get('/api/admin/opportunities/1/history?environment=isolated')
    assert record.status_code==200 and record.json()['event_date']=='2026-10-20' and record.json()['history']
    operations=client.get('/api/admin/operations?environment=isolated')
    assert operations.status_code==200 and operations.json()['items'][0]['reason']
    assert client.get('/api/admin/tasks?environment=isolated').status_code==200
    original=committed.json()['operation_id']
    revert=client.post('/api/admin/operations/'+original+'/revert-preview',json={'environment':'isolated','reason':'撤回合成演练贡献'},headers=headers)
    assert revert.status_code==200 and revert.json()['visible'] is False
    result=client.post('/api/admin/operations/'+original+'/revert',json=commit_request(revert.json()),headers=headers)
    assert result.status_code==200 and result.json()['visible'] is False
    assert snapshot(settings.db_path)['rows']==[]
    assert client.post('/api/admin/session/logout',headers=headers).status_code==200
    assert client.get('/api/admin/operations?environment=isolated').status_code==401
    assert client.post('/api/admin/operations/commit',json=binding,headers=headers).status_code==401


def test_different_valid_session_cannot_use_preview_and_client_cannot_supply_actor_or_path(api_setup):
    settings,app=api_setup;first,headers=logged_in(app)
    preview=first.post('/api/admin/materials/preview',json=request(),headers=headers).json()
    second,second_headers=logged_in(app)
    result=second.post('/api/admin/operations/commit',json=commit_request(preview),headers=second_headers)
    assert result.status_code==409 and snapshot(settings.acceptance_db_path)['rows']==[]
    assert first.post('/api/admin/materials/preview',json={**request(),'actor':'attacker'},headers=headers).status_code==422
    assert first.post('/api/admin/materials/preview',json={**request(),'db_path':'C:/unrelated.sqlite3'},headers=headers).status_code==422
    assert first.post('/api/admin/materials/preview',json=request(),headers={**headers,'Origin':'https://other.example'}).status_code==403


def test_environment_unavailable_and_oversized_body_fail_without_facts(api_setup):
    settings,app=api_setup;client,headers=logged_in(app)
    settings.acceptance_db_path=None
    response=client.post('/api/admin/materials/preview',json=request(),headers=headers)
    assert response.status_code==503 and response.json()['detail']['code']=='maintenance_isolation_unavailable'
    assert client.post('/api/admin/materials/preview',content=b'x'*524289,headers=headers).status_code==413
