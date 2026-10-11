"""Only synthetic legacy files; no project dataset is used by these tests."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from backend.services.ingestion import ingest_page
from backend.storage.database import initialize_database, read_database, DatabaseUnavailable
from backend.storage.migrations import migrate_database, NEW_TABLES
from backend.storage.write import writer_transaction
from test_ingestion import source, material, candidate, run


def legacy_database(tmp_path,version='2',optional_bad=False,core_bad=False):
    current=tmp_path/'current.synthetic.sqlite3';initialize_database(current,fixture=True)
    config=source();archive=material(config);item=candidate(config,archive)
    ingest_page(current,config,[item],[archive],run_id=run(current),fixture=True)
    schema=(Path(__file__).parents[1]/'backend/storage/schema.sql').read_text(encoding='utf-8').split('-- Schema 3 additions')[0]
    schema=schema.replace(', last_attempt_at TEXT, next_eligible_at TEXT,\n  queued_at TEXT','')
    schema=schema.replace(',\n  session_id TEXT, input_hash TEXT, idempotency_key TEXT, receipt_json TEXT,\n  expected_version INTEGER, target_source_key TEXT, target_identity TEXT','')
    schema=schema.replace(', reason TEXT, write_context_key TEXT','')
    if version=='1':
        schema=schema.replace('  reference_key TEXT NOT NULL,\n','').replace(', UNIQUE(source_key,reference_key)','')
        schema=schema.replace('  task_identity TEXT NOT NULL,\n','').replace(', UNIQUE(source_key,task_identity,task_kind)','')
    legacy=tmp_path/('legacy'+version+'.synthetic.sqlite3')
    with sqlite3.connect(current) as original,sqlite3.connect(legacy) as target:
        original.row_factory=sqlite3.Row
        target.executescript(schema)
        for table in ('metadata','schools','campuses','sources','opportunities','source_materials','runs','processing_tasks','manual_operations','changes'):
            columns=[row[1] for row in target.execute('PRAGMA table_info('+table+')')]
            for row in original.execute('SELECT * FROM '+table):
                values=[row[c] for c in columns]
                if table=='opportunities':
                    index=columns.index('field_observations_json'); observations=json.loads(values[index])
                    for observation in observations.values():
                        for proof in observation.get('evidence',[]):
                            proof.pop('source_identity',None);proof.pop('association_id',None)
                    if core_bad:observations['event_date']['evidence'][0]['locator']='record:unrelated/event_date'
                    values[index]=json.dumps(observations,ensure_ascii=False)
                    if optional_bad:
                        values[columns.index('attachments_json')]=json.dumps([{'label':'旧附件','url':'https://jyzx.scut.edu.cn/attachment/a.pdf','scope':'this_announcement','evidence':observations['published_date']['evidence']}],ensure_ascii=False)
                target.execute('INSERT INTO '+table+'('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',values)
        target.execute("UPDATE metadata SET value=? WHERE key='schema_version'",(version,))
    return legacy


@pytest.mark.parametrize('version',['1','2'])
def test_explicit_legacy_path_preserves_identity_facts_history_mode_and_dataset(tmp_path,version):
    database=legacy_database(tmp_path,version)
    with sqlite3.connect(database) as connection:
        before_metadata=dict(connection.execute('SELECT key,value FROM metadata'))
        before=connection.execute('SELECT id,title,event_date,version,first_seen_at FROM opportunities').fetchall()
        history=connection.execute('SELECT id,opportunity_id,field_name,change_kind,run_id FROM changes').fetchall()
    with pytest.raises(DatabaseUnavailable):
        with read_database(database):pass
    result=migrate_database(database)
    assert Path(result['backup']).is_file()
    with sqlite3.connect(result['backup']) as backup:
        assert dict(backup.execute('SELECT key,value FROM metadata'))==before_metadata
    assert result['schema_version']=='3' and result['revised_opportunities']==0
    with read_database(database) as (connection,metadata):
        assert metadata['dataset_id']==before_metadata['dataset_id'] and metadata['data_mode']=='isolated_fixture'
        assert [tuple(r) for r in connection.execute('SELECT id,title,event_date,version,first_seen_at FROM opportunities')]==before
        assert [tuple(r) for r in connection.execute('SELECT id,opportunity_id,field_name,change_kind,run_id FROM changes')]==history
        assert connection.execute('SELECT COUNT(*) FROM opportunity_materials').fetchone()[0]>0
        assert connection.execute('PRAGMA foreign_key_check').fetchone() is None
    before=database.read_bytes()
    assert migrate_database(database)['migration']=='already_current'
    assert database.read_bytes()==before


def test_failure_after_ddl_rolls_back_every_change_and_leaves_consistent_backup(tmp_path,monkeypatch):
    database=legacy_database(tmp_path)
    before=database.read_bytes()
    import backend.storage.migrations as migration
    def fail(*args):raise RuntimeError('synthetic fault after schema changes')
    monkeypatch.setattr(migration,'_migrate_evidence',fail)
    with pytest.raises(RuntimeError,match='synthetic fault'):migrate_database(database)
    assert database.read_bytes()==before
    backups=list(tmp_path.glob(database.name+'.schema2-*.sqlite3'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='2'


def test_missing_identity_locator_in_legacy_core_rolls_back_instead_of_trusting_null(tmp_path):
    database=legacy_database(tmp_path,core_bad=True);before=database.read_bytes()
    with pytest.raises(DatabaseUnavailable,match='不可核实'):migrate_database(database)
    assert database.read_bytes()==before
    assert len(list(tmp_path.glob(database.name+'.schema2-*.sqlite3')))==1


def test_optional_unverified_legacy_attachment_is_quarantined_with_operation_history(tmp_path):
    database=legacy_database(tmp_path,optional_bad=True)
    with sqlite3.connect(database) as connection:
        before=dict(connection.execute('SELECT key,value FROM metadata'))
    result=migrate_database(database)
    assert result['revised_opportunities']==1 and result['dataset_id']!=before['dataset_id']
    from backend.services.queries import detail
    with read_database(database) as (connection,metadata):
        record=detail(connection,1)
        assert record['event_date']=='2026-10-20' and record['attachments']==[] and record['version']==2
        assert connection.execute('SELECT COUNT(*) FROM quarantined_evidence').fetchone()[0]==1
        assert connection.execute("SELECT COUNT(*) FROM processing_tasks WHERE task_kind='maintenance'").fetchone()[0]==1
        history=connection.execute("SELECT * FROM changes WHERE change_kind='migration_revision'").fetchone()
        assert history['manual_operation_id'] and history['run_id'] is None and history['reason']
        assert metadata['data_mode']=='isolated_fixture'


def legacy_attachment(database, name):
    with sqlite3.connect(database) as connection:
        identity,observations=connection.execute('SELECT source_identity,field_observations_json FROM opportunities WHERE id=1').fetchone()
    proof=deepcopy(json.loads(observations)['published_date']['evidence'][0])
    proof['locator']='record:'+identity+'/attachment:'+name
    proof['excerpt']='本条公告附件链接'
    url='https://jyzx.scut.edu.cn/attachment/'+name+'.pdf'
    return {'label':'招聘附件','url':url,'scope':'this_announcement','evidence':[proof],
            'link_chain':{**deepcopy(proof),'target_url':url}}


def set_legacy_attachments(database, attachments):
    with sqlite3.connect(database) as connection:
        connection.execute('UPDATE opportunities SET attachments_json=? WHERE id=1',(json.dumps(attachments,ensure_ascii=False),))


def test_valid_legacy_attachment_only_rebuilds_relation_without_business_revision(tmp_path):
    database=legacy_database(tmp_path);valid=legacy_attachment(database,'valid')
    set_legacy_attachments(database,[valid])
    with sqlite3.connect(database) as connection:
        dataset=connection.execute("SELECT value FROM metadata WHERE key='dataset_id'").fetchone()[0]
    result=migrate_database(database)
    assert result['revised_opportunities']==0 and result['dataset_id']==dataset
    from backend.services.queries import detail
    with read_database(database) as (connection,_):
        record=detail(connection,1)
        assert record['version']==1 and record['supplemental_status']=='verified'
        assert [attachment['url'] for attachment in record['attachments']]==[valid['url']]
        assert connection.execute('SELECT COUNT(*) FROM quarantined_evidence').fetchone()[0]==0


@pytest.mark.parametrize('damage',['unsafe_url','empty_scope','numeric_scope','blank_label','long_label','numeric_label','partial_binding'])
def test_bad_attachment_metadata_and_partial_binding_are_isolated_without_verified_residue(tmp_path,damage):
    database=legacy_database(tmp_path)
    valid=legacy_attachment(database,'valid');bad=legacy_attachment(database,'bad')
    if damage=='unsafe_url':bad['url']=bad['link_chain']['target_url']='javascript:bad'
    elif damage=='empty_scope':bad['scope']=''
    elif damage=='numeric_scope':bad['scope']=12
    elif damage=='blank_label':bad['label']='   '
    elif damage=='long_label':bad['label']='x'*501
    elif damage=='numeric_label':bad['label']=12
    else:
        missing=deepcopy(bad['evidence'][0]);missing['material_id']=999999
        bad['evidence'].append(missing)
    set_legacy_attachments(database,[valid,bad])
    with sqlite3.connect(database) as connection:
        before=dict(connection.execute('SELECT key,value FROM metadata'))
    result=migrate_database(database)
    assert result['revised_opportunities']==1 and result['dataset_id']!=before['dataset_id']
    from backend.services.queries import detail
    with read_database(database) as (connection,metadata):
        record=detail(connection,1)
        assert record['event_date']=='2026-10-20' and record['version']==2
        assert [attachment['url'] for attachment in record['attachments']]==[valid['url']]
        assert record['supplemental_status']=='pending_verification'
        assert connection.execute('SELECT COUNT(*) FROM opportunity_materials WHERE locator=?',(bad['evidence'][0]['locator'],)).fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM opportunity_materials WHERE locator=?',(valid['evidence'][0]['locator'],)).fetchone()[0]==1
        quarantined=connection.execute('SELECT original_json FROM quarantined_evidence').fetchall()
        assert len(quarantined)==1 and json.loads(quarantined[0][0])==bad
        assert connection.execute("SELECT COUNT(*) FROM processing_tasks WHERE task_kind='maintenance'").fetchone()[0]==1
        history=connection.execute("SELECT * FROM changes WHERE change_kind='migration_revision'").fetchone()
        assert history['manual_operation_id'] and history['run_id'] is None and history['reason']
        assert metadata['data_mode']=='isolated_fixture'
    with sqlite3.connect(result['backup']) as backup:
        assert json.loads(backup.execute('SELECT attachments_json FROM opportunities WHERE id=1').fetchone()[0])==[valid,bad]
    stable=database.read_bytes()
    assert migrate_database(database)['migration']=='already_current' and database.read_bytes()==stable


def test_excess_legacy_attachments_are_quarantined_as_original_collection(tmp_path):
    database=legacy_database(tmp_path)
    attachments=[legacy_attachment(database,str(index)) for index in range(9)]
    set_legacy_attachments(database,attachments)
    assert migrate_database(database)['revised_opportunities']==1
    from backend.services.queries import detail
    with read_database(database) as (connection,_):
        record=detail(connection,1)
        assert record['event_date']=='2026-10-20' and record['attachments']==[]
        assert connection.execute("SELECT COUNT(*) FROM opportunity_materials WHERE relation_kind='attachment_link'").fetchone()[0]==0
        original=json.loads(connection.execute('SELECT original_json FROM quarantined_evidence').fetchone()[0])
        assert json.loads(original['_unreadable'])==attachments


def test_failure_after_optional_quarantine_rolls_back_relations_history_and_facts(tmp_path,monkeypatch):
    database=legacy_database(tmp_path)
    bad=legacy_attachment(database,'bad');bad['url']=bad['link_chain']['target_url']='javascript:bad'
    set_legacy_attachments(database,[bad])
    before=database.read_bytes()
    import backend.storage.migrations as migration
    def fail(*args):raise RuntimeError('synthetic fault after quarantine')
    monkeypatch.setattr(migration,'_validate',fail)
    with pytest.raises(RuntimeError,match='after quarantine'):migrate_database(database)
    assert database.read_bytes()==before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='2'
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='quarantined_evidence'").fetchone()[0]==0
        assert json.loads(connection.execute('SELECT attachments_json FROM opportunities WHERE id=1').fetchone()[0])==[bad]
    backups=list(tmp_path.glob(database.name+'.schema2-*.sqlite3'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute('PRAGMA quick_check').fetchone()[0]=='ok'
