"""Summary assertions use production writers on synthetic isolated databases."""
from copy import deepcopy
from datetime import date
import json

import pytest

from backend.services import maintenance
from backend.services.ingestion import ingest_detail, ingest_page, save_task
from backend.services.updates import read_updates
from backend.storage.database import DatabaseUnavailable, read_database
from backend.storage.write import writer_transaction
from test_ingestion import database, source, material, candidate, run, snapshot
from test_maintenance import maintenance_setup, request, commit_request, import_record, correction, revert


TODAY=date(2026,10,12)
STAMP='2026-10-12T10:00:00+08:00'


def pin_commits(path,stamp=STAMP):
    with writer_transaction(path) as (connection,_):
        connection.execute('UPDATE changes SET committed_at=?',(stamp,))


def finish_automatic(path,config,*,status='success',stamp=STAMP):
    with writer_transaction(path) as (connection,_):
        connection.execute("UPDATE runs SET started_at='2026-10-12T09:00:00+08:00',finished_at=?,committed_at=?,status='complete',scope_json=?",
            (stamp,stamp,json.dumps({'school_keys':[config['school_key']],'source_keys':[config['source_key']],'page_budget':1,'detail_budget':2,'fixture':True,'internal':'excluded'})))
        connection.execute('UPDATE sources SET last_attempt_at=?,last_success_at=?,status=? WHERE source_key=?',
            (stamp,stamp,status,config['source_key']))


def set_date(item,field,value):
    item[field]=value
    observation=item['field_observations'][field]
    observation.update(state='known' if value else 'not_collected',value=value,evidence=observation['evidence'] if value else [])
    return item


def test_midnight_uses_commit_day_in_shanghai_not_run_start_or_utc(database):
    config=source();archive=material(config);item=candidate(config,archive);run_id=run(database)
    ingest_page(database,config,[item],[archive],run_id=run_id,fixture=True)
    stamp='2026-10-11T16:05:00+00:00';pin_commits(database,stamp);finish_automatic(database,config,stamp=stamp)
    with writer_transaction(database) as (connection,_):
        connection.execute("UPDATE runs SET started_at='2026-10-11T15:55:00+00:00'")
    summary=read_updates(database,TODAY)
    assert summary['today']['timezone']=='Asia/Shanghai' and summary['today']['newly_collected']==1
    assert summary['automatic']['run_count']==1 and summary['scope']['page_budget']==1
    assert 'internal' not in summary['scope']
    assert read_updates(database,date(2026,10,11))['committed_counts']['newly_collected']==0


def test_new_classes_distinct_ids_can_overlap_and_are_not_additive(database):
    config=source();run_id=run(database);items=[];archives=[]
    # Recent publication plus past event belongs to both current and history.
    values=[('overlap','2026-10-12','2026-10-10'),('history','2026-08-01','2026-09-01'),
        ('undated','2026-08-01',None),('other','2026-08-01','2027-02-01')]
    for identity,published,event in values:
        archive=material(config,identity);item=candidate(config,archive,identity=identity)
        set_date(item,'published_date',published);set_date(item,'event_date',event)
        archives.append(archive);items.append(item)
    ingest_page(database,config,items,archives,run_id=run_id,fixture=True)
    pin_commits(database);finish_automatic(database,config)
    summary=read_updates(database,TODAY);counts=summary['committed_counts']
    assert counts['newly_collected']==4 and counts['current_new']==1 and counts['historical_backfill']==2
    assert counts['undated_new']==1 and counts['other_dated_new']==1 and summary['categories_overlap'] is True
    assert summary['opportunity_sets']['current_new']==[1] and summary['opportunity_sets']['historical_backfill']==[1,2]
    assert counts['current_new']+counts['historical_backfill']+counts['undated_new']+counts['other_dated_new']>counts['newly_collected']


def test_multiple_fields_and_categories_count_each_opportunity_once(database):
    config=source();first=material(config);item=candidate(config,first);run_id=run(database)
    ingest_page(database,config,[item],[first],run_id=run_id,fixture=True)
    pin_commits(database,'2026-10-11T10:00:00+08:00')
    archive=material(config,'changed');revised=candidate(config,archive)
    set_date(revised,'event_date','2026-10-21');set_date(revised,'published_date','2026-10-11')
    revised['deadline']='2026-10-30';revised['field_observations']['deadline']=deepcopy(revised['field_observations']['event_date'])
    revised['field_observations']['deadline']['value']=revised['deadline']
    ingest_detail(database,config,revised,[archive],run_id=run_id,fixture=True)
    with writer_transaction(database) as (connection,_):
        connection.execute('UPDATE changes SET committed_at=? WHERE field_name!=?',(STAMP,'__record__'))
    finish_automatic(database,config)
    summary=read_updates(database,TODAY)
    assert summary['today']['newly_collected']==0 and summary['today']['modified']==1
    assert summary['today']['official_changes']==1 and summary['today']['parser_improvements']==1
    assert summary['automatic']['changed']==1 and summary['automatic']['source_checks'][0]['status'] in ('not_checked','checked_with_changes')
    before=snapshot(database)
    ingest_detail(database,config,revised,[archive],run_id=run_id,fixture=True)
    assert snapshot(database)==before and read_updates(database,TODAY)['opportunity_sets']==summary['opportunity_sets']


def test_manual_only_new_correction_revert_and_withdraw_are_visible_without_fake_run(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    changed=correction(settings,principal,'2026-10-21');revert(settings,principal,changed['operation_id'])
    revert(settings,principal,created['operation_id']);pin_commits(settings.acceptance_db_path)
    summary=read_updates(settings.acceptance_db_path,TODAY)
    assert summary['check_status']=='not_checked' and summary['automatic']['run_count'] is None
    assert summary['automatic']['newly_collected'] is None and summary['automatic']['changed'] is None
    assert summary['today']['manual_supplements']==1 and summary['today']['manual_corrections']==1
    assert summary['today']['manual_reverts']==1 and summary['today']['manual_withdrawals']==1
    assert summary['today']['newly_collected']==1 and summary['today']['modified']==1
    assert summary['last_success_at'] is None and summary['today']['official_changes'] is None
    with read_database(settings.acceptance_db_path) as (connection,_):assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0


def test_manual_noop_and_receipt_replay_do_not_repeat_business_counts(maintenance_setup):
    settings,principal=maintenance_setup;preview=maintenance.preview_materials(settings,principal,request())
    receipt=maintenance.commit_operation(settings,principal,commit_request(preview));pin_commits(settings.acceptance_db_path)
    before=read_updates(settings.acceptance_db_path,TODAY)
    assert maintenance.commit_operation(settings,principal,commit_request(preview))['replayed'] is True
    noop=correction(settings,principal,'2026-10-20');assert noop['modified']==0
    assert read_updates(settings.acceptance_db_path,TODAY)['committed_counts']==before['committed_counts']
    assert receipt['new']==1


@pytest.mark.parametrize('status,reason,expected',[('failed','list_parse_failed','failed'),('restricted','restricted','restricted'),('partial','partial','partial')])
def test_failed_partial_restricted_checks_keep_unknown_counts_and_old_success(database,status,reason,expected):
    config=source();run_id=run(database);archive=material(config)
    ingest_page(database,config,[candidate(config,archive)],[archive],run_id=run_id,fixture=True)
    pin_commits(database,'2026-10-10T10:00:00+08:00')
    with writer_transaction(database) as (connection,_):
        connection.execute("UPDATE sources SET status=?,last_attempt_at=?,last_success_at='2026-10-10T10:00:00+08:00' WHERE source_key=?",(status,STAMP,config['source_key']))
        connection.execute('UPDATE runs SET status=?,started_at=?,finished_at=?',(status,STAMP,STAMP))
        save_task(connection,config,task_kind='list',task_identity='failed-list',run_id=run_id,status=status,result={'reason':reason})
    summary=read_updates(database,TODAY)
    assert summary['check_status']==expected and summary['last_success_at']=='2026-10-10T10:00:00+08:00'
    assert summary['today']['newly_collected'] is None and summary['automatic']['changed'] is None
    assert summary['committed_counts']['newly_collected']==0
    observed=next(item for item in summary['automatic']['source_checks'] if item['source_key']==config['source_key'])
    assert observed['status']==('parse_failed' if reason=='list_parse_failed' else status)


def test_verified_finite_check_can_report_zero_without_claiming_all_school_coverage(database):
    config=source();archive=material(config);run_id=run(database)
    ingest_page(database,config,[candidate(config,archive)],[archive],run_id=run_id,fixture=True)
    pin_commits(database,'2026-10-10T10:00:00+08:00');finish_automatic(database,config)
    summary=read_updates(database,TODAY)
    assert summary['check_status']=='complete' and summary['automatic']['newly_collected']==0
    assert summary['today']['newly_collected']==0 and summary['today']['modified']==0
    assert summary['scope']['school_keys']==['scut']
    assert any(item['status']=='not_checked' for item in summary['automatic']['source_checks'])


def test_pure_evidence_revision_is_audit_only_and_reading_changes_nothing(database):
    config=source();archive=material(config);run_id=run(database)
    ingest_page(database,config,[candidate(config,archive)],[archive],run_id=run_id,fixture=True)
    pin_commits(database,'2026-10-10T10:00:00+08:00')
    with writer_transaction(database) as (connection,_):
        connection.execute("INSERT INTO changes(opportunity_id,field_name,before_json,after_json,change_kind,committed_at) VALUES (1,'__evidence__:event_date','{\"locator\":\"old\"}','{\"locator\":\"new\"}','semantic_revision',?)",(STAMP,))
    original=snapshot(database);first=read_updates(database,TODAY);second=read_updates(database,TODAY)
    assert first==second and snapshot(database)==original
    assert all(value==0 for value in first['committed_counts'].values())
    assert first['today']['manual_corrections']==0 and first['automatic']['changed'] is None


def test_invalid_committed_timezone_fails_closed_instead_of_wrong_day(database):
    config=source();archive=material(config);run_id=run(database)
    ingest_page(database,config,[candidate(config,archive)],[archive],run_id=run_id,fixture=True)
    pin_commits(database,'2026-10-12T10:00:00')
    with pytest.raises(DatabaseUnavailable,match='时区'):read_updates(database,TODAY)


@pytest.mark.parametrize('today,days',[(TODAY,0),(TODAY,367),('2026-10-12',30),(TODAY,True)])
def test_invalid_summary_window_rejected(database,today,days):
    with pytest.raises(ValueError):read_updates(database,today,recent_days=days)
