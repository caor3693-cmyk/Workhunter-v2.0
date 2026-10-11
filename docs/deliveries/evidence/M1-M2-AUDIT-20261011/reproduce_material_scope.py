"""Isolated audit only: same-source materials from another announcement.

Uses the existing production ingestion/query functions and a temporary fixture DB.
Never touches a running database or official site.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from backend.domain.candidates import CORE_FIELDS
from backend.services.ingestion import ingest_detail, now
from backend.services.queries import detail
from backend.storage.database import initialize_database, read_database, DatabaseUnavailable
from backend.storage.write import writer_transaction

config = {'source_key': 'gdut_homepage', 'school_key': 'gdut', 'channel_key': 'homepage'}

def material(identity):
    return {'source_key': config['source_key'], 'reference_key': identity,
        'source_url': 'https://career.gdut.edu.cn/notice/' + identity,
        'official_record_id': identity, 'material_hash': hashlib.sha256(identity.encode()).hexdigest(),
        'fetched_at': '2026-10-11T17:00:00+08:00', 'raw_reference': 'isolated_fixture/' + identity,
        'acquisition_status': 'success', 'parsing_status': 'success', 'parser_version': 'audit-only',
        'scope': {'opportunity_identity': identity}}

def evidence(archive):
    return {'material_ref': archive['reference_key'], 'source_url': archive['source_url'],
        'excerpt': '本材料明确只属于 ' + archive['official_record_id'], 'locator': 'article a[href]',
        'scope': {'opportunity_identity': archive['official_record_id']},
        'observed_at': archive['fetched_at'], 'parser_version': 'audit-only'}

def candidate(archive):
    item = {**config, 'source_identity': archive['official_record_id'], 'title': '隔离公告 ' + archive['official_record_id'],
        'kind': 'announcement', 'date_basis': 'publication', 'source_url': archive['source_url'],
        'published_date': '2026-10-11', 'work_locations': [], 'field_observations': {},
        'roster_fragments': [], 'job_fragments': [], 'attachments': []}
    for field in CORE_FIELDS:
        value = item.get(field)
        item['field_observations'][field] = {'state': 'known' if value else 'not_collected',
            'value': value if value else None, 'evidence': [evidence(archive)] if value else []}
    return item

with TemporaryDirectory(prefix='workhunter-m2-scope-') as scratch:
    db = Path(scratch) / 'isolated.sqlite3'
    initialize_database(db, fixture=True)
    with writer_transaction(db) as (conn, _):
        conn.execute("INSERT INTO runs(id,trigger,started_at,status,scope_json) VALUES ('audit','test',?,'running','{}')", (now(),))
    archive_a, archive_b = material('announcement-A'), material('announcement-B')
    a = candidate(archive_a)
    a['attachments'] = [{'label': '公告 B 的附件', 'url': 'https://career.gdut.edu.cn/uploads/B.pdf',
        'scope': {'opportunity_identity': 'announcement-B'}, 'evidence': [evidence(archive_b)]}]
    outcome = ingest_detail(db, config, a, [archive_a, archive_b], run_id='audit', fixture=True)
    a_id = outcome['opportunity_ids'][0]
    with read_database(db) as (conn, _):
        projected = detail(conn, a_id)
        attachment = projected['attachments'][0]
        early = {'ingest_result': outcome, 'public_attachment': attachment,
            'material_B_bound_opportunity': conn.execute("SELECT opportunity_id FROM source_materials WHERE reference_key='announcement-B'").fetchone()[0]}
    b_outcome = ingest_detail(db, config, candidate(archive_b), [archive_b], run_id='audit', fixture=True)
    with read_database(db) as (conn, _):
        try:
            detail(conn, a_id)
            after = 'unexpectedly still accepted'
        except DatabaseUnavailable as error:
            after = {'exception': type(error).__name__, 'message': str(error)}
    print(json.dumps({'audit': 'isolated_fixture_only', 'before_B_is_ingested': early,
        'B_ingest_result': b_outcome, 'A_detail_after_B_is_ingested': after}, ensure_ascii=False, indent=2))
