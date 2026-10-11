"""Read-only projections exercise real stored tasks and operation receipts."""
import json

import httpx
import pytest

from backend.services import maintenance
from backend.services.ingestion import ingest_detail, save_task
from backend.services.maintenance_tasks import read_tasks
from backend.storage.database import DatabaseUnavailable, read_database
from backend.storage.write import writer_transaction
from test_ingestion import database, source, material, candidate, run, snapshot
from test_maintenance import maintenance_setup, import_record, commit_request
from test_sources import gdut_detail


def base_record(path):
    config=source();archive=material(config);run_id=run(path)
    ingest_detail(path,config,candidate(config,archive),[archive],run_id=run_id,fixture=True)
    return config


def saved_task(path,config,identity,*,status='failed',opportunity_id=1,result=None,kind='maintenance'):
    with writer_transaction(path) as (connection,_):
        save_task(connection,config,task_kind=kind,task_identity=identity,opportunity_id=opportunity_id,status=status,result=result)
        return connection.execute('SELECT id FROM processing_tasks WHERE source_key=? AND task_identity=? AND task_kind=?',
            (config['source_key'],identity,kind)).fetchone()[0]


def test_repeated_same_task_preserves_identity_and_projection_never_writes(database):
    config=base_record(database);identity='manual-conflict:1:event_date'
    first=saved_task(database,config,identity,status='pending',result={'type':'manual_decision_conflict','field':'event_date'})
    second=saved_task(database,config,identity,status='pending',result={'type':'manual_decision_conflict','field':'event_date','observation_id':2})
    before=snapshot(database);projection=read_tasks(database);repeated=read_tasks(database)
    assert first==second and repeated==projection and snapshot(database)==before
    item=next(item for item in projection['items'] if item['id']==first)
    assert item['attempts']==2 and item['task_key']==config['source_key']+':maintenance:'+identity
    groups=[group for group in projection['groups'] if group['reason']=='manual_conflict']
    assert len(groups)==1 and groups[0]['active_scope_count']==1 and groups[0]['task_ids']==[first]
    assert groups[0]['opportunity_ids']==[1] and groups[0]['fields']==['event_date']


def test_quarantine_hashes_and_stored_task_group_by_same_source_record_field(database):
    config=base_record(database);task_id=saved_task(database,config,'quarantine:1:attachments',status='pending',result={'type':'material_applicability','field':'attachments'})
    with writer_transaction(database) as (connection,_):
        for key in ('old-bad-hash','another-bad-hash'):
            connection.execute("INSERT INTO quarantined_evidence(opportunity_id,field_name,input_hash,original_json,reason,recorded_at) VALUES (1,'attachments',?,'[]','wrong identity','2026-10-12T10:00:00+08:00')",(key,))
    result=read_tasks(database)
    group=next(item for item in result['groups'] if item['reason']=='material_quarantine')
    assert group['active_scope_count']==1 and group['opportunity_count']==1 and group['task_ids']==[task_id]
    assert group['basis']==['quarantined_evidence','stored_task']
    with writer_transaction(database) as (connection,_):connection.execute("UPDATE processing_tasks SET status='resolved' WHERE id=?",(task_id,))
    result=read_tasks(database)
    group=next(item for item in result['groups'] if item['reason']=='material_quarantine')
    assert group['active_scope_count']==0 and group['resolved_scope_count']==1
    assert not any(item['reason']=='material_quarantine' for item in read_tasks(database,include_resolved=False)['groups'])


def test_restriction_has_one_stable_source_reason_group_and_no_retry_or_invented_schedule(database):
    config=base_record(database)
    task_id=saved_task(database,config,'restricted-list',kind='list',status='restricted',opportunity_id=None,result={'reason':'restricted'})
    with writer_transaction(database) as (connection,_):
        connection.execute("UPDATE sources SET status='restricted',public_message='公开入口拒绝访问' WHERE source_key=?",(config['source_key'],))
    result=read_tasks(database);item=next(item for item in result['items'] if item['id']==task_id)
    group=next(item for item in result['groups'] if item['reason']=='public_restriction')
    assert group['active_scope_count']==1 and group['basis']==['source_status','stored_task']
    assert item['retry_supported'] is False and item['next_eligible_at'] is None
    assert 'next_run_at' not in result and 'next_run_at' not in item and 'continuous_days' not in result


def test_pending_field_gaps_are_derived_without_creating_retry_ids(database):
    base_record(database);before=snapshot(database);result=read_tasks(database)
    group=next(item for item in result['groups'] if item['reason']=='field_pending')
    assert group['fields']==['deadline','relevance','work_locations']
    assert group['opportunity_ids']==[1] and group['task_ids']==[] and result['items']==[]
    assert snapshot(database)==before


def test_hidden_record_does_not_create_visitor_field_gap_but_stored_audit_remains(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    config=maintenance._config('gdut','gdut_teachin')
    task_id=saved_task(settings.acceptance_db_path,config,'quarantine:1:attachments',status='resolved',result={'field':'attachments'})
    preview=maintenance.preview_revert(settings,principal,created['operation_id'],{'environment':'isolated','reason':'合成待办隐藏记录核验'})
    maintenance.commit_operation(settings,principal,commit_request(preview),expected_revert=created['operation_id'])
    result=read_tasks(settings.acceptance_db_path)
    assert not any(item['reason']=='field_pending' for item in result['groups'])
    assert any(item['id']==task_id for item in result['items'])


@pytest.mark.parametrize('kind,identity',[('maintenance','synthetic-retry:1'),('detail','detail:1212')])
def test_real_retry_receipt_history_survives_reopened_task(maintenance_setup,kind,identity):
    settings,principal=maintenance_setup;import_record(settings,principal)
    config=maintenance._config('gdut','gdut_teachin')
    task_id=saved_task(settings.acceptance_db_path,config,identity,kind=kind,result={'field':'event_date'})
    def fetcher_factory(**kwargs):
        client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,
            text=gdut_detail(date='2026-10-24'),headers={'content-type':'text/html; charset=utf-8'})))
        return maintenance.Fetcher(**kwargs,client=client)
    preview=maintenance.retry_task_preview(settings,principal,task_id,{'environment':'isolated','reason':'合成公开材料重试历史'},fetcher_factory=fetcher_factory)
    receipt=maintenance.commit_operation(settings,principal,commit_request(preview))
    resolved=next(item for item in read_tasks(settings.acceptance_db_path)['items'] if item['id']==task_id)
    assert resolved['status']=='resolved' and not resolved['retry_supported']
    assert resolved['reason']=='source_failure'
    assert resolved['resolution_history'][0]['operation_id']==receipt['operation_id']
    assert resolved['resolution_history'][0]['receipt']['modified']==1
    assert resolved['resolution_history'][0]['previous_status']=='failed'
    assert resolved['resolution_history'][0]['target']['opportunity_id']==1
    assert not any(item['id']==task_id for item in read_tasks(settings.acceptance_db_path,include_resolved=False)['items'])
    reopened=saved_task(settings.acceptance_db_path,config,identity,kind=kind,result={'field':'event_date'})
    current=next(item for item in read_tasks(settings.acceptance_db_path)['items'] if item['id']==task_id)
    assert reopened==task_id and current['status']=='failed' and current['attempts']==2
    assert current['resolution_history']==resolved['resolution_history'] and current['retry_supported'] is True


def test_resolved_conflict_reason_does_not_disappear_when_receipt_replaces_result(database):
    config=base_record(database)
    task_id=saved_task(database,config,'manual-conflict:1:event_date',status='resolved',result={'operation_id':'synthetic-resolution'})
    item=next(item for item in read_tasks(database)['items'] if item['id']==task_id)
    assert item['reason']=='manual_conflict' and item['retry_supported'] is False
    group=next(group for group in read_tasks(database)['groups'] if group['reason']=='manual_conflict')
    assert group['fields']==['event_date'] and group['resolved_scope_count']==1


def test_pagination_keeps_real_ids_source_filter_and_resolved_records(database):
    config=base_record(database)
    ids=[saved_task(database,config,'synthetic:'+str(index),status='resolved' if index==1 else 'pending',result={'field':'event_date'}) for index in range(3)]
    first=read_tasks(database,limit=2,source_key=config['source_key'])
    second=read_tasks(database,limit=2,before=first['next_cursor'],source_key=config['source_key'])
    assert [item['id'] for item in first['items']]==list(reversed(ids[1:])) and first['has_more']
    assert [item['id'] for item in second['items']]==ids[:1] and second['next_cursor'] is None
    assert [item['id'] for item in read_tasks(database,include_resolved=False)['items']]==[ids[2],ids[0]]
    assert read_tasks(database,source_key='gdut_homepage')['items']==[]


def test_corrupt_task_payload_returns_unavailable_without_partial_false_projection(database):
    config=base_record(database);task_id=saved_task(database,config,'bad-payload',result={'field':'event_date'})
    with writer_transaction(database) as (connection,_):connection.execute("UPDATE processing_tasks SET result_json='broken-json' WHERE id=?",(task_id,))
    before=snapshot(database)
    with pytest.raises(DatabaseUnavailable,match='待办'):read_tasks(database)
    assert snapshot(database)==before


@pytest.mark.parametrize('kwargs',[{'limit':0},{'limit':101},{'limit':True},{'before':0},{'before':'2'},
    {'include_resolved':'false'},{'source_key':''},{'source_key':'not-registered'}])
def test_invalid_task_filter_or_cursor_is_rejected(database,kwargs):
    with pytest.raises(ValueError):read_tasks(database,**kwargs)
