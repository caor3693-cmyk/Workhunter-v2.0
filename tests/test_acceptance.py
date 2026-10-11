"""Synthetic acceptance inputs use the real write/read service; no official fetches."""
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.config import Settings
from backend.services.ingestion import ingest_page
from backend.storage.database import initialize_database, read_database
from scripts.prepare_acceptance import DB_NAME, _config, _record, load_bundle, prepare_bundle


@pytest.fixture
def bundle(tmp_path):
    directory = tmp_path / 'isolated-acceptance'
    manifest = prepare_bundle(directory, isolated=True)
    database = directory / DB_NAME
    client = TestClient(create_app(Settings(db_path=database, backend_commit='a' * 40)), client=('127.0.0.1', 1))
    return directory, database, manifest, client


def test_explicit_fixture_creation_refuses_existing_or_unapproved_destinations(tmp_path):
    untouched = tmp_path / 'not-approved'
    with pytest.raises(ValueError, match='显式'):
        prepare_bundle(untouched)
    assert not untouched.exists()
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'original.db'
    sentinel.write_bytes(b'user data must survive')
    with pytest.raises(ValueError, match='全新'):
        prepare_bundle(existing, isolated=True)
    assert sentinel.read_bytes() == b'user data must survive'
    assert not (existing / DB_NAME).exists()


def test_fixture_identity_material_hash_ownership_and_original_user_results(bundle):
    directory, database, manifest, client = bundle
    assert manifest['data_mode'] == 'isolated_fixture'
    assert manifest['dataset_id'].startswith('fixture-ds-')
    assert manifest['schema_version'] == '2'
    assert manifest['record_count'] == 29
    assert manifest['source_origin'] == 'generated_locally_never_fetched'
    assert manifest['user_results']['M0']['M0-02'] == '失败'
    assert manifest['user_results']['M0']['M0-03'] == '阻塞'
    assert all(result == '未测' for result in manifest['user_results']['M1'].values())
    assert load_bundle(directory / 'manifest.json')[0] == database
    states = set()
    with read_database(database) as (connection, metadata):
        materials = {row['id']: dict(row) for row in connection.execute('SELECT * FROM source_materials')}
        for material in materials.values():
            raw = Path(material['raw_reference']).read_bytes()
            assert b'ISOLATED_FIXTURE_GENERATED_LOCALLY' in raw
            assert hashlib.sha256(raw).hexdigest() == material['material_hash']
            assert material['opportunity_id'] is not None
        for row in connection.execute('SELECT * FROM opportunities'):
            assert row['title'].startswith('[隔离样例]')
            observations = json.loads(row['field_observations_json'])
            states.update(observation['state'] for observation in observations.values())
            for observation in observations.values():
                for evidence in observation['evidence']:
                    material = materials[evidence['material_id']]
                    assert material['source_key'] == row['source_key']
                    assert material['opportunity_id'] == row['id']
                    assert material['source_url'] == evidence['source_url']
                    assert material['acquisition_status'] == 'success'
                    assert evidence['excerpt'] in Path(material['raw_reference']).read_text(encoding='utf-8')
        assert connection.execute("SELECT COUNT(*) FROM schools WHERE school_key NOT IN ('scut','gdut') AND verification_state='pending'").fetchone()[0] == 8
    assert states >= {'known', 'not_collected', 'pending_extraction', 'parse_failed', 'not_disclosed', 'not_applicable', 'conflict'}
    assert client.get('/health').json()['data_mode'] == 'isolated_fixture'
    assert len(client.get('/api/catalog').json()['schools']) == 10


def test_real_queries_cover_four_views_relevance_unknown_campus_and_date_meaning(bundle):
    _, _, manifest, client = bundle
    ids = manifest['case_ids']
    read = lambda **params: client.get('/api/opportunities', params={'as_of': manifest['as_of'], 'limit': 100, **params}).json()
    rowids = lambda data: {item['id'] for item in data['items']}
    recent = read(view='recent')
    assert recent['total'] > 20
    assert ids['ordinary-six-work-locations'] in rowids(recent)
    assert ids['future-event-different-venue-work'] in rowids(recent)
    assert ids['history-late-ingestion'] not in rowids(recent)
    assert ids['known-unrelated'] not in rowids(recent)
    assert ids['known-unrelated'] in rowids(read(view='recent', scope='all'))
    assert ids['history-late-ingestion'] in rowids(read(view='history'))
    assert ids['history-event'] in rowids(read(view='history'))
    assert ids['undated-parse-failed'] in rowids(read(view='undated'))
    assert ids['future-event-different-venue-work'] in rowids(read(view='upcoming'))
    assert ids['history-event'] not in rowids(read(view='upcoming'))
    assert all(item['campus_id'] is None for item in read(view='recent', campus_unknown='true')['items'])
    assert all(item['campus_id'] == manifest['campus_ids']['scut'] for item in read(view='recent', school_key='scut', campus_id=manifest['campus_ids']['scut'])['items'])
    only_today = read(view='recent', date_from=manifest['as_of'], date_to=manifest['as_of'])
    assert ids['ordinary-six-work-locations'] in rowids(only_today)
    assert ids['future-event-different-venue-work'] not in rowids(only_today)  # event date, not its publication date
    assert read(view='recent', keyword='pagination-')['total'] == 21


def test_real_detail_retains_list_facts_conflict_materials_fragments_and_applicable_attachment(bundle):
    _, _, manifest, client = bundle
    read = lambda key: client.get('/api/opportunities/' + str(manifest['case_ids'][key])).json()
    ordinary = read('ordinary-six-work-locations')
    assert len(ordinary['work_locations']) == 6
    assert ordinary['field_observations']['event_venue']['state'] == 'not_applicable'
    assert ordinary['roster_fragments'][0]['scope'] == 'partial'
    assert ordinary['job_fragments'][0]['scope'] == 'partial'
    assert ordinary['attachments'][0]['scope'] == 'complete_for_material'
    assert all(material['material_hash'] and material['id'] for material in ordinary['materials'])
    assert ordinary['coverage']['coverage'] == 'isolated_fixture'
    failed = read('list-known-detail-failed')
    assert failed['start_time'] == '09:30'
    assert failed['event_venue'] == '[隔离样例] 列表披露会场'
    assert not failed['job_fragments']
    conflict = read('conflicting-retained-venue')
    assert conflict['event_venue'] == '[隔离样例] 旧会场A'
    assert conflict['field_observations']['event_venue']['state'] == 'conflict'
    assert conflict['field_observations']['event_venue']['value'] is None
    assert len({proof['material_id'] for proof in conflict['field_observations']['event_venue']['evidence']}) == 2


def test_real_pagination_freezes_day_and_dataset_change_refuses_old_page(bundle):
    directory, database, manifest, client = bundle
    first = client.get('/api/opportunities', params={'view': 'recent', 'as_of': manifest['as_of']}).json()
    params = {'view': 'recent', 'offset': 20, 'dataset_id': first['dataset_id'], 'as_of': first['as_of']}
    second = client.get('/api/opportunities', params=params).json()
    assert first['as_of'] == second['as_of']
    assert not ({item['id'] for item in first['items']} & {item['id'] for item in second['items']})
    assert client.get('/api/opportunities', params={key: value for key, value in params.items() if key != 'as_of'}).status_code == 422
    candidate, archives = _record(directory, 'version-change-new-record', 'gdut', values={'published_date': manifest['as_of']})
    with read_database(database) as (connection, _):
        run_id = connection.execute('SELECT id FROM runs LIMIT 1').fetchone()[0]
    ingest_page(database, _config('gdut'), [candidate], archives, run_id=run_id, fixture=True)
    changed = client.get('/api/opportunities', params=params)
    assert changed.status_code == 409
    assert changed.json()['detail']['code'] == 'dataset_changed'
    refreshed = client.get('/api/opportunities').json()
    assert refreshed['dataset_id'].startswith('fixture-ds-')
    assert refreshed['dataset_id'] != first['dataset_id']
    assert refreshed['total'] == first['total'] + 1


def test_fixture_materials_cannot_be_written_to_an_empty_real_database(bundle, tmp_path):
    directory, _, manifest, _ = bundle
    real = tmp_path / 'empty-real.sqlite3'
    initialize_database(real)
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    candidate, archives = _record(directory, 'must-not-enter-real-db', 'gdut', values={'published_date': manifest['as_of']})
    with pytest.raises(ValueError, match='隔离样例'):
        ingest_page(real, _config('gdut'), [candidate], archives, run_id='not-real', fixture=True)
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before
    with read_database(real) as (connection, metadata):
        assert metadata['data_mode'] == 'empty'
        assert connection.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0] == 0
