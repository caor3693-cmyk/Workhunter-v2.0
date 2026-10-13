"""Clock/OS-independent counterexamples; these fixtures never prove natural operation."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from backend.config import ROOT
from backend.services import scheduling
from backend.services.discovery import refresh_sources
from backend.storage.database import initialize_database, read_database
from backend.storage.write import writer_transaction
from ops.scheduler import collect, run_collector
from test_discovery import Adapter, Transport
from test_ingestion import source

NOW = datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)
POLICY = {'interval_hours': 6, 'source_seconds': 90, 'round_seconds': 1200,
          'page_budget': 2, 'detail_budget': 12, 'max_requests': 48,
          'max_retries': 1, 'timeout_seconds': 15, 'ledger_limit': 50}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'isolated.sqlite3'
    initialize_database(path, fixture=True)
    return path


def registered(database, first=NOW, **policy):
    parameters = {**POLICY, **policy}
    return scheduling.configure(database, first_run_at=first,
        host_registration={'id': 'fixture-host', 'platform': 'windows-task',
            'readback_verified': True, 'enabled': True, 'interval_hours': parameters['interval_hours'],
            'first_run_at': first.isoformat(), 'verified_at': (NOW-timedelta(seconds=1)).isoformat()},
        policy=parameters, current_time=NOW)


def projection(database, now=NOW):
    with read_database(database) as (connection, metadata):
        return scheduling.schedule_projection(connection, metadata, now)


def runner(database, policy, cursor, run_id, trigger):
    with read_database(database) as (_, metadata):
        fixture = metadata['data_mode'] == 'isolated_fixture'
    business = refresh_sources(database, [source()], lambda _: Adapter(database), lambda _: Transport(),
                               fixture=fixture, run_id=run_id, trigger=trigger, detail_budget=0)
    return {'exit_code': 0, 'business': business, 'next_cursor': cursor+1}


def test_no_registration_is_not_ready_and_no_implicit_database_creation(database, tmp_path):
    assert projection(database)['status'] == 'not_ready'
    result = scheduling.configure(database, first_run_at=NOW, policy=POLICY, current_time=NOW)
    assert result['status'] == 'not_ready' and result['next_run_at'] is None
    assert scheduling.tick(database, runner=runner, current_time=NOW)['started'] is False
    missing = tmp_path/'missing'/'never.sqlite3'
    with pytest.raises(Exception):
        scheduling.tick(missing)
    assert not missing.parent.exists()


def test_future_slot_not_due_same_slot_once_and_manual_never_counts_natural(database):
    registered(database, NOW+timedelta(minutes=2))
    result = scheduling.tick(database, trigger='scheduled', registration_id='fixture-host', runner=runner, current_time=NOW)
    assert result['status'] == 'not_due' and not result['started']
    result = scheduling.tick(database, trigger='scheduled', registration_id='fixture-host', runner=runner, current_time=NOW+timedelta(minutes=2))
    assert result['started'] and result['natural'] and result['process_exit_code'] == 0
    duplicate = scheduling.tick(database, trigger='scheduled', registration_id='fixture-host', runner=runner, current_time=NOW+timedelta(minutes=3))
    assert duplicate['status'] == 'duplicate_slot'
    manual = scheduling.tick(database, runner=runner, current_time=NOW+timedelta(minutes=4))
    assert manual['trigger'] == 'manual' and manual['natural'] is False
    current = projection(database, NOW+timedelta(minutes=5))
    assert current['next_run_at'] == (NOW+timedelta(hours=6, minutes=2)).isoformat()
    assert current['natural_run_count'] is None  # synthetic fixtures are no real coverage
    with read_database(database) as (connection, _):
        assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 2
        assert connection.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0] == 1


def test_wrong_registration_disabled_and_reconfigure_do_not_start(database):
    registered(database)
    with pytest.raises(ValueError, match='ID'):
        scheduling.tick(database, trigger='scheduled', registration_id='other', runner=runner, current_time=NOW)
    scheduling.disable(database, NOW)
    assert projection(database)['status'] == 'disabled'
    assert scheduling.tick(database, runner=runner, current_time=NOW)['status'] == 'disabled'


def test_overdue_and_malformed_never_fabricate_future_plan(database):
    registered(database)
    result = projection(database, NOW+timedelta(days=1))
    assert result['status'] == 'overdue' and result['next_run_at'] is None and result['overdue_since'] == NOW.isoformat()
    with writer_transaction(database) as (connection, _):
        connection.execute('UPDATE metadata SET value=? WHERE key=?', ('{broken', scheduling.STATE_KEY))
    result = projection(database)
    assert result['status'] == 'unknown' and result['next_run_at'] is None
    with pytest.raises(Exception):
        scheduling.tick(database, runner=runner)


@pytest.mark.parametrize('hours,state,due,stale', [(0,'current',False,False),(24,'review_due',True,False),(48,'stale',True,True)])
@pytest.mark.parametrize('status', ['success', 'failed', 'restricted'])
def test_freshness_24_48_does_not_replace_actual_status(hours, state, due, stale, status):
    result = scheduling.source_freshness((NOW-timedelta(hours=hours)).isoformat(), status, NOW)
    assert result['status'] == status and result['freshness'] == state
    assert result['review_due24h'] is due and result['stale48h'] is stale


@pytest.mark.parametrize('bad', [None, 'not-a-date', '2026-10-13', (NOW+timedelta(seconds=1)).isoformat()])
def test_missing_malformed_or_future_success_time_is_unknown(bad):
    result = scheduling.source_freshness(bad, 'failed', NOW)
    assert result['freshness'] == 'unknown' and result['review_due24h'] is None and result['age_hours'] is None


def test_process_crash_recovery_retains_commits_and_slot_is_not_replayed(database):
    registered(database)
    code = """
from pathlib import Path
import os
from backend.services.scheduling import tick
from backend.services.discovery import refresh_sources
from test_discovery import Adapter, Transport
from test_ingestion import source
def crash(db,policy,cursor,run_id,trigger):
    refresh_sources(db,[source()],lambda _:Adapter(db),lambda _:Transport(),fixture=True,run_id=run_id,detail_budget=0)
    os._exit(7)
tick(Path(__import__('sys').argv[1]),trigger='scheduled',registration_id='fixture-host',current_time='2026-10-13T02:00:00+00:00',runner=crash)
"""
    environment = {**__import__('os').environ, 'PYTHONPATH': str(ROOT/'tests')}
    process = subprocess.run([sys.executable,'-c',code,str(database)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=20)
    assert process.returncode == 7, process.stderr
    assert projection(database)['status'] == 'running'
    result = scheduling.tick(database, trigger='scheduled', registration_id='fixture-host', current_time=NOW+timedelta(minutes=1), runner=runner)
    assert result['status'] == 'duplicate_slot'
    prior = projection(database, NOW+timedelta(minutes=1))['last_execution']
    assert prior['status'] == 'interrupted' and prior['process_exit_code'] is None
    with read_database(database) as (connection,_):
        assert connection.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 1
    fresh = scheduling.tick(database, trigger='scheduled', registration_id='fixture-host', current_time=NOW+timedelta(hours=6), runner=runner)
    assert fresh['started'] and fresh['commits']['new'] == 0


def test_consistent_restore_to_another_path_disables_old_host_plan(database, tmp_path):
    registered(database)
    restored = tmp_path/'restored.sqlite3'
    with sqlite3.connect(database) as original, sqlite3.connect(restored) as copy:
        original.backup(copy)
    result = projection(restored)
    assert result['status'] == 'not_ready' and result['next_run_at'] is None
    assert scheduling.tick(restored, trigger='scheduled', registration_id='fixture-host', runner=runner, current_time=NOW)['started'] is False


def test_round_budget_rotates_to_unattempted_source_and_skips_known_restrictions(database):
    configs = [source('scut'), source('gdut')]
    clock = [0]
    class Slow(Adapter):
        def discover(self, config, fetcher, cursor=None):
            result = super().discover(config, fetcher, cursor)
            clock[0] += 2
            return result
    result = collect(database,{**POLICY,'round_seconds':1,'detail_budget':0},0,'run-budget','scheduled',
                     configs=configs,adapters=lambda _:Slow(database),transport=lambda _:Transport(),monotonic=lambda:clock[0])
    assert result['business']['sources'][1]['status'] == 'skipped_budget'
    assert result['next_cursor'] == 1
    clock[0]=0
    later = collect(database,{**POLICY,'round_seconds':1,'detail_budget':0},result['next_cursor'],'run-next','scheduled',
                    configs=configs,adapters=lambda _:Slow(database),transport=lambda _:Transport(),monotonic=lambda:clock[0])
    assert later['business']['sources'][0]['source_key'] == 'gdut_homepage'
    with writer_transaction(database) as (connection,_):
        connection.execute("UPDATE sources SET status='restricted',last_attempt_at='2026-10-11T01:00:00+00:00' WHERE source_key='scut_homepage'")
    visited=[]
    def adapter(config):
        visited.append(config['source_key'])
        return Adapter(database)
    result=collect(database,POLICY,0,'run-known-restricted','scheduled',configs=configs,adapters=adapter,transport=lambda _:Transport())
    assert result['business']['sources'][0]['status'] == 'skipped_restricted'
    assert visited == ['gdut_homepage']
    with read_database(database) as (connection,_):
        row=connection.execute("SELECT status,last_attempt_at FROM sources WHERE source_key='scut_homepage'").fetchone()
        assert tuple(row)==('restricted','2026-10-11T01:00:00+00:00')


def test_single_source_failure_isolated_os_zero_not_complete_and_history_bounded(database):
    registered(database, ledger_limit=2)
    def partial(db,policy,cursor,run_id,trigger):
        failed=Adapter(db,fail_list=True);good=Adapter(db)
        business=refresh_sources(db,[source(),source('gdut')],lambda config:failed if config['school_key']=='scut' else good,lambda _:Transport(),fixture=True,run_id=run_id,detail_budget=1)
        return {'exit_code':0,'business':business,'next_cursor':cursor+1,
                'backup':{'status':'failed'},'scheduler_exit_code':2}
    for minutes in (0,1,2):
        result=scheduling.tick(database,runner=partial,current_time=NOW+timedelta(minutes=minutes))
    assert result['process_exit_code']==0 and result['business_status']=='partial'
    assert result['business_completeness']=='partial' and result['scheduler_exit_code']==2
    assert result['source_results'][1]['status']=='complete'
    assert len(projection(database,NOW+timedelta(minutes=3))['ledger'])==2


def test_os_registration_is_not_accepted_without_true_readback(database):
    registration={'id':'pretended','platform':'windows-task','readback_verified':False,
        'enabled':True,'interval_hours':6,'first_run_at':NOW.isoformat(),'verified_at':NOW.isoformat()}
    with pytest.raises(ValueError,match='回读'):
        scheduling.configure(database,first_run_at=NOW,host_registration=registration,policy=POLICY,current_time=NOW)


def test_ledger_statistics_include_failed_real_triggers_but_are_not_lifetime_totals(database):
    registered(database)
    with writer_transaction(database) as (connection,metadata):
        state=scheduling._state(metadata)
        state['ledger']=[{'execution_id':'isolated-recorded-trigger','natural':True,'data_mode':'real',
            'triggered_at':NOW.isoformat(),'finished_at':NOW.isoformat(),'business_status':'failed',
            'process_exit_code':1,'backup':{'status':'complete'}}]
        scheduling._save(connection,state)
    result=projection(database)
    assert result['natural_run_count']==1 and result['successful_natural_runs']==0
    assert result['ledger_window']['is_lifetime_total'] is False and result['continuous_days'] is None


@pytest.mark.parametrize('damage', [
    {'ledger':[1]}, {'ledger':[{'execution_id':'broken','natural':True,'triggered_at':None}]},
    {'host_registration':1}, {'active_execution':{'execution_id':'missing-ledger'}}, {'interval_hours':'6'},
])
def test_structurally_malformed_schedule_keeps_source_projection_readable(database, damage):
    registered(database)
    with writer_transaction(database) as (connection,metadata):
        state=scheduling._state(metadata)
        state.update(damage)
        scheduling._save(connection,state)
    result=projection(database)
    assert result['status']=='unknown' and result['next_run_at'] is None
    with read_database(database) as (connection,_):
        assert connection.execute('SELECT COUNT(*) FROM sources').fetchone()[0]==10
    with pytest.raises(Exception):
        scheduling.tick(database,runner=runner,current_time=NOW)


@pytest.mark.parametrize('backup_failed', [False, True])
def test_collector_uses_bounded_managed_retention_and_keeps_backup_failure_separate(database, tmp_path, monkeypatch, backup_failed):
    observed={}
    class Child:
        returncode=0
        def communicate(self, timeout=None):
            return json.dumps({'business':{'run_id':'run-backup-contract','status':'partial','sources':[]},'next_cursor':1}), ''
    def spawn(arguments, **kwargs):
        observed['env']=kwargs['env']
        return Child()
    def backup(db,directory,**kwargs):
        observed['backup']=kwargs
        if backup_failed:
            raise RuntimeError('protected capacity exceeded')
        return {'status':'verified','retained_count':7,'removed_verified':[]}
    monkeypatch.setenv('WH_SOURCE_DNS_MODE','system')
    monkeypatch.setattr('ops.scheduler.subprocess.Popen',spawn)
    monkeypatch.setattr('ops.backup.create_backup',backup)
    result=run_collector(database,POLICY,0,'run-backup-contract','manual',backup_directory=tmp_path/'managed')
    assert observed['backup']=={'retain_count':7,'byte_cap':268435456,'min_free_bytes':134217728,'apply_retention':True,'max_seconds':60}
    assert observed['env']['WH_SOURCE_DNS_MODE']=='system'
    assert result['exit_code']==0 and result['business']['status']=='partial'
    assert result['backup']['status']==('failed' if backup_failed else 'complete')
    assert result['scheduler_exit_code']==(2 if backup_failed else 0)

