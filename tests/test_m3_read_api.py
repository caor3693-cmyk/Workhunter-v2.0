"""The scheduled state is a read-only projection, never an API trigger."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.config import Settings
from backend.storage.database import initialize_database
from backend.storage.write import writer_transaction
from backend.version import PROJECT, VERSION, STAGE


def api(path, token=''):
    return TestClient(create_app(Settings(db_path=path, backend_commit='c' * 40, service_token=token)),
                      client=('127.0.0.1', 54321))


def test_reading_missing_schedule_does_not_create_or_start_it(tmp_path):
    database = tmp_path / 'candidate.sqlite3'
    metadata = initialize_database(database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with patch('backend.services.discovery.refresh_sources', side_effect=AssertionError('GET started collection')):
        response = api(database).get('/api/refresh/status')
        assert response.status_code == 200
        state = response.json()
        assert state['project'] == PROJECT and state['version'] == VERSION and state['stage'] == STAGE
        assert state['dataset_id'] == metadata['dataset_id'] and state['data_mode'] == 'empty'
        assert state['status'] in {'disabled', 'not_ready'} and state['next_run_at'] is None
        source_response = api(database).get('/api/sources/status')
        assert source_response.status_code == 200
        assert source_response.json()['schedule']['status'] == state['status']
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_public_plan_does_not_expose_host_paths_registration_or_private_ledger(tmp_path):
    database = tmp_path / 'candidate.sqlite3'
    initialize_database(database)
    private = 'SECRET-test-host-path-and-token'
    state = {
        'enabled': True, 'status': 'scheduled', 'interval_hours': 6,
        'next_run_at': '2026-10-14T12:00:00+08:00',
        'host_registration': {'id': private}, 'ledger': [{'message': private}],
        'last_execution': {'run_id': 'run-safe', 'business_status': 'partial',
                           'backup': {'status': 'complete', 'receipt': {'private': private}},
                           'host_command': private, 'stdout': private, 'exception': private},
    }
    with patch('backend.services.scheduling.schedule_projection', return_value=state):
        for route in ['/api/sources/status', '/api/refresh/status']:
            response = api(database).get(route)
            assert response.status_code == 200
            assert private not in response.text
            plan = response.json().get('schedule', response.json())
            assert plan['last_execution']['run_id'] == 'run-safe'
            assert plan['last_execution']['business_status'] == 'partial'
            assert plan['last_execution']['backup_status'] == 'complete'
            assert 'ledger' not in plan and 'host_registration' not in plan


@pytest.mark.parametrize('route', ['/api/refresh/status', '/api/sources/status'])
def test_schedule_routes_share_service_boundary_and_refuse_writes(tmp_path, route):
    database = tmp_path / 'candidate.sqlite3'
    initialize_database(database)
    client = api(database, 'service-test-token')
    assert client.get(route).status_code == 401
    assert client.get(route, headers={'Authorization': 'Bearer service-test-token'}).status_code == 200
    assert client.post(route, headers={'Authorization': 'Bearer service-test-token'}).status_code == 405
    assert client.get('/api/scheduler/start', headers={'Authorization': 'Bearer service-test-token'}).status_code == 404


@pytest.mark.parametrize('stored', ['invalid-json', json.dumps({'schema_version': 1, 'enabled': False, 'ledger': [1]})])
def test_malformed_schedule_retains_readable_business_sources_and_no_invented_plan(tmp_path, stored):
    database = tmp_path / 'candidate.sqlite3'
    initialize_database(database)
    with writer_transaction(database) as (connection, _):
        connection.execute("INSERT INTO metadata(key,value) VALUES('operations_schedule',?)", (stored,))
    before = database.read_bytes()
    response = api(database).get('/api/sources/status')
    assert response.status_code == 200
    assert response.json()['schedule']['status'] == 'unknown'
    assert response.json()['schedule']['next_run_at'] is None
    assert response.json()['sources']
    assert database.read_bytes() == before


def test_missing_business_database_is_503_without_implicit_creation(tmp_path):
    missing = tmp_path / 'absent' / 'candidate.sqlite3'
    assert api(missing).get('/api/refresh/status').status_code == 503
    assert not missing.parent.exists()
