"""M2 QA exercises frozen production auth/maintenance on disposable local files."""
from contextlib import contextmanager
from datetime import date
import json

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.config import ROOT
from backend.services.auth import verify_password
from backend.sources.transport import Fetcher
from backend.storage.database import initialize_database, read_database
from scripts.prepare_m2_acceptance import (
    DB_NAME, DEFAULT_ORIGIN, HOST_DB_NAME, MANIFEST_NAME, MATERIALS_NAME, M2_IDS,
    PASSWORD_NAME, PRIVATE_NAME, load_bundle, load_private, main, prepare_bundle, settings_for_bundle,
)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    def forbidden_network(*args, **kwargs):
        raise AssertionError('合成验收绝不能抓取官方占位链接。')
    monkeypatch.setattr(Fetcher, 'get', forbidden_network)
    directory = tmp_path / 'm2-bundle'
    manifest = prepare_bundle(directory, date(2026, 10, 12), isolated=True)
    return directory, manifest, settings_for_bundle(directory / MANIFEST_NAME)


def facts(database):
    with read_database(database) as (connection, metadata):
        return {'metadata': dict(metadata), **{table: [dict(row) for row in connection.execute('SELECT * FROM ' + table + ' ORDER BY 1')]
            for table in ('opportunities', 'source_materials', 'opportunity_materials', 'changes', 'write_receipts')}}


@contextmanager
def authenticated(directory, settings):
    with TestClient(create_app(settings), base_url=DEFAULT_ORIGIN, client=('127.0.0.1', 1)) as client:
        before = client.get('/api/admin/session')
        assert before.status_code == 200 and before.json()['authenticated'] is False
        headers = {'Origin': DEFAULT_ORIGIN, 'X-WH-CSRF': before.json()['csrf_token']}
        password = (directory / PASSWORD_NAME).read_text(encoding='utf-8').strip()
        result = client.post('/api/admin/session/login', json={'password': password}, headers=headers)
        assert result.status_code == 200 and result.json()['authenticated'] is True
        headers['X-WH-CSRF'] = result.json()['csrf_token']
        yield client, headers


def binding(preview):
    return {key: preview[key] for key in ('environment', 'operation_id', 'preview_hash', 'input_hash', 'base_version')}


def preview(client, headers, request):
    result = client.post('/api/admin/materials/preview', json=request, headers=headers)
    assert result.status_code == 200, result.json()
    return result.json()


def commit(client, headers, value):
    result = client.post('/api/admin/operations/commit', json=binding(value), headers=headers)
    assert result.status_code == 200, result.json()
    return result.json()


def revert(client, headers, operation_id):
    base = '/api/admin/operations/' + operation_id
    result = client.post(base + '/revert-preview', json={'environment': 'isolated', 'reason': '本机合成验收：撤回指定贡献。'}, headers=headers)
    assert result.status_code == 200, result.json()
    change = client.post(base + '/revert', json=binding(result.json()), headers=headers)
    assert change.status_code == 200, change.json()
    return change.json()


def test_preparation_requires_explicit_fresh_private_directory_and_preserves_existing_files(tmp_path):
    fresh = tmp_path / 'fresh'
    with pytest.raises(ValueError, match='isolated'):
        prepare_bundle(fresh)
    assert not fresh.exists()
    fresh.mkdir(); protected = fresh / 'user-results.json'; protected.write_text('unique user evidence')
    with pytest.raises(ValueError, match='全新'):
        prepare_bundle(fresh, isolated=True)
    assert protected.read_text() == 'unique user evidence' and list(fresh.iterdir()) == [protected]
    with pytest.raises(ValueError, match='runtime'):
        prepare_bundle(ROOT / 'unsafe-m2-credentials', isolated=True)
    with pytest.raises(ValueError, match='HTTPS'):
        prepare_bundle(tmp_path / 'insecure', isolated=True, origin='http://127.0.0.1:8789')
    assert not (tmp_path / 'insecure').exists()


def test_manifest_keeps_all_numbered_human_history_and_never_contains_credentials(bundle):
    directory, manifest, settings = bundle
    project = json.loads((ROOT / 'config/project.json').read_text(encoding='utf-8'))
    assert manifest['schema_version'] == '3' and manifest['data_mode'] == 'isolated_fixture'
    assert manifest['user_history']['snapshots']['manual_review_history'] == project['manual_review_history']
    assert manifest['user_results']['M0'] == project['manual_review']['outcomes']
    assert manifest['user_results']['M1'] == project['m1_manual_review']['outcomes']
    assert manifest['user_history']['original_bundle_results']['M0']['M0-02'] == '失败'
    assert manifest['user_results']['M2'] == dict.fromkeys(M2_IDS, '未测')
    assert set(manifest['checks']) == set(M2_IDS) and len(set(manifest['fixed_schools'])) == 10
    assert all(value['user_result'] == '未测' and value['engineering_status'] == 'not_run' for value in manifest['checks'].values())
    assert manifest['gate']['M2'] == 'awaiting_user_after_M1'
    password = (directory / PASSWORD_NAME).read_text(encoding='utf-8').strip()
    public = (directory / MANIFEST_NAME).read_text(encoding='utf-8')
    assert password not in public and '$scrypt$' not in public and 'maintenance_password_hash' not in public
    assert str(directory) not in public and 'csrf_token' not in public
    assert verify_password(password, settings.maintenance_password_hash)
    assert not verify_password(password + 'x', settings.maintenance_password_hash)
    assert settings.db_path != settings.acceptance_db_path
    assert settings.db_path.name == HOST_DB_NAME and settings.acceptance_db_path.name == DB_NAME
    materials = json.loads((directory / MATERIALS_NAME).read_text(encoding='utf-8'))
    for key in ('supplement', 'correction', 'later_correction'):
        assert '/__isolated_fixture__/' in materials[key]['url']
        assert materials[key]['environment'] == 'isolated' and '本机合成' in materials[key]['public_text']


def test_loader_refuses_fixture_real_substitution_and_manifest_path_injection(bundle, tmp_path):
    directory, manifest, settings = bundle
    other = tmp_path / 'external-empty.sqlite3'; initialize_database(other)
    external = settings_for_bundle(directory / MANIFEST_NAME, real_database=other)
    assert external.db_path == other and external.acceptance_db_path == settings.acceptance_db_path
    assert facts(other)['opportunities'] == []
    with pytest.raises(ValueError, match='不能'):
        settings_for_bundle(directory / MANIFEST_NAME, real_database=settings.acceptance_db_path)
    broken = directory / 'bad-manifest.json'
    broken.write_text(json.dumps({**manifest, 'db': '../real.sqlite3'}), encoding='utf-8')
    with pytest.raises(ValueError, match='完整固定'):
        load_bundle(broken)
    private = directory / PRIVATE_NAME
    saved = private.read_text(encoding='utf-8')
    private.write_text(json.dumps({'maintenance_password_hash': 'unbounded'}), encoding='utf-8')
    with pytest.raises(ValueError, match='格式'):
        load_private(directory / MANIFEST_NAME)
    private.write_text(saved, encoding='utf-8')


def test_live_auth_denials_logout_and_audit_reads_preserve_business_facts(bundle):
    directory, _, settings = bundle
    before = facts(settings.acceptance_db_path)
    with TestClient(create_app(settings), base_url=DEFAULT_ORIGIN, client=('127.0.0.1', 1)) as anonymous:
        assert anonymous.get('/api/admin/operations?environment=isolated').status_code == 401
        assert anonymous.post('/api/admin/materials/preview', json={}, headers={'Origin': DEFAULT_ORIGIN}).status_code == 401
        assert anonymous.get('/api/opportunities').json()['total'] == 0
    with authenticated(directory, settings) as (client, headers):
        material = json.loads((directory / MATERIALS_NAME).read_text(encoding='utf-8'))['supplement']
        assert client.post('/api/admin/materials/preview', json=material, headers={'Origin': DEFAULT_ORIGIN}).status_code == 403
        assert client.post('/api/admin/materials/preview', json=material, headers={**headers, 'Origin': 'https://other.example'}).status_code == 403
        for route in ('operations', 'tasks'):
            assert client.get('/api/admin/' + route + '?environment=isolated').status_code == 200
        assert facts(settings.acceptance_db_path) == before
        logout = client.post('/api/admin/session/logout', headers=headers)
        assert logout.status_code == 200
        assert client.get('/api/admin/operations?environment=isolated').status_code == 401
        assert client.post('/api/admin/materials/preview', json=material, headers=headers).status_code == 401
    assert facts(settings.acceptance_db_path) == before


def test_real_preview_idempotent_save_correction_withdrawal_and_hidden_history(bundle):
    directory, _, settings = bundle
    materials = json.loads((directory / MATERIALS_NAME).read_text(encoding='utf-8'))
    initial = facts(settings.acceptance_db_path)
    with authenticated(directory, settings) as (client, headers):
        new = preview(client, headers, materials['supplement'])
        assert new['candidate']['deadline'] == materials['original_deadline']
        assert facts(settings.acceptance_db_path) == initial
        first = commit(client, headers, new)
        target = first['opportunity_ids'][0]
        assert first['new'] == 1 and first['environment'] == 'isolated'
        after = facts(settings.acceptance_db_path)
        assert commit(client, headers, new) == {**first, 'replayed': True}
        assert facts(settings.acceptance_db_path) == after
        corrected = preview(client, headers, {**materials['correction'], 'opportunity_id': target})
        assert corrected['differences']['deadline']['before'] == materials['original_deadline']
        assert facts(settings.acceptance_db_path) == after
        second = commit(client, headers, corrected)
        assert client.get(f'/api/admin/opportunities/{target}?environment=isolated').json()['deadline'] == materials['corrected_deadline']
        reverted = revert(client, headers, second['operation_id'])
        assert reverted['visible'] is True
        assert client.get(f'/api/admin/opportunities/{target}?environment=isolated').json()['deadline'] == materials['original_deadline']
        hidden = revert(client, headers, first['operation_id'])
        assert hidden['visible'] is False
        history = client.get(f'/api/admin/opportunities/{target}/history?environment=isolated')
        assert history.status_code == 200 and history.json()['history']
        final = facts(settings.acceptance_db_path)
        assert len(final['opportunities']) == len(initial['opportunities']) + 1
        assert len(final['source_materials']) > len(initial['source_materials'])
        assert all(row['run_id'] is None for row in final['changes'] if row['opportunity_id'] == target)
        assert client.get('/api/opportunities').json()['total'] == 0
        assert client.get('/api/opportunities/' + str(target)).status_code == 404
        assert load_bundle(directory / MANIFEST_NAME)[0] == settings.acceptance_db_path
    assert facts(settings.db_path)['opportunities'] == []


def test_old_preview_conflict_later_contribution_retained_and_unsafe_tasks_rejected(bundle):
    directory, manifest, settings = bundle
    materials = json.loads((directory / MATERIALS_NAME).read_text(encoding='utf-8'))
    with authenticated(directory, settings) as (client, headers):
        first = commit(client, headers, preview(client, headers, materials['supplement']))
        target = first['opportunity_ids'][0]
        old = preview(client, headers, {**materials['correction'], 'opportunity_id': target})
        fresh = preview(client, headers, {**materials['later_correction'], 'opportunity_id': target})
        third = commit(client, headers, fresh)
        after = facts(settings.acceptance_db_path)
        conflict = client.post('/api/admin/operations/commit', json=binding(old), headers=headers)
        assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'maintenance_conflict'
        assert facts(settings.acceptance_db_path) == after
        revert(client, headers, first['operation_id'])
        current = client.get(f'/api/admin/opportunities/{target}?environment=isolated').json()
        assert current['deadline'] == materials['later_deadline']
        assert third['version'] > first['version']
        for task in manifest['task_ids']:
            response = client.post(f'/api/admin/tasks/{task}/retry-preview', json={'environment': 'isolated', 'reason': '核验合成待办拒绝边界。'}, headers=headers)
            assert response.status_code == 422
            assert response.json()['detail']['code'] in {'maintenance_task_target', 'maintenance_restricted'}
        assert client.get('/api/opportunities').json()['total'] == 0


def test_cli_public_output_does_not_reveal_random_password_or_server_hash(tmp_path, capsys):
    directory = tmp_path / 'cli-m2'
    assert main(['prepare', '--output', str(directory), '--isolated']) == 0
    output = capsys.readouterr().out
    assert (directory / PASSWORD_NAME).read_text(encoding='utf-8').strip() not in output
    assert '$scrypt$' not in output and 'not_assessed' in output
