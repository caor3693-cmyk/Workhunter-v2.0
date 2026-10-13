"""Explicit isolated scheduling state; projections never start a task or write."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from backend.config import ROOT
from backend.storage.database import DatabaseUnavailable, read_database
from backend.storage.write import _file_lock, RefreshBusy, refresh_lock, writer_transaction

STATE_KEY = 'operations_schedule'
UTC = timezone.utc
LIMITS = {'interval_hours': (1, 168), 'source_seconds': (1, 600),
          'round_seconds': (1, 3600), 'page_budget': (1, 10), 'detail_budget': (0, 100),
          'max_requests': (1, 300), 'max_retries': (0, 2), 'timeout_seconds': (1, 60),
          'ledger_limit': (1, 50)}


def _time(value=None):
    if value is None:
        return datetime.now(UTC)
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError('调度时间必须有明确时区。')
    return stamp.astimezone(UTC)


def _stamp(value=None):
    return _time(value).isoformat()


def source_freshness(last_success_at, status, current_time=None):
    result = {'status': status, 'last_success_at': last_success_at,
              'freshness': 'unknown', 'age_hours': None,
              'review_due24h': None, 'stale48h': None, 'review_due': None, 'stale': None}
    try:
        if last_success_at is None:
            return result
        age = (_time(current_time) - _time(last_success_at)).total_seconds() / 3600
        if age < 0:
            return result
    except (ValueError, TypeError, OverflowError):
        return result
    result.update(age_hours=round(age, 3), review_due24h=age >= 24, stale48h=age >= 48,
                  review_due=age >= 24, stale=age >= 48,
                  freshness='stale' if age >= 48 else 'review_due' if age >= 24 else 'current')
    # Freshness supplements the actual failure/restriction; it never replaces it.
    return result


def read_policy(path=None):
    policy = json.loads((Path(path) if path else ROOT / 'config/operations.json').read_text(encoding='utf-8'))
    if not isinstance(policy, dict) or set(policy) != set(LIMITS):
        raise ValueError('运行配置缺失或包含未登记参数。')
    for key, (minimum, maximum) in LIMITS.items():
        value = policy[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('运行配置超出有界范围：' + key)
    return policy


def _binding(connection):
    path = connection.execute('PRAGMA database_list').fetchone()[2]
    return hashlib.sha256(str(Path(path).resolve()).casefold().encode()).hexdigest()


def _state(metadata):
    raw = metadata.get(STATE_KEY)
    if raw is None:
        return None
    try:
        state = json.loads(raw)
        if (not isinstance(state, dict) or state.get('schema_version') != 1
                or not isinstance(state.get('ledger'), list) or len(state['ledger']) > 50
                or any(not isinstance(item, dict) or not isinstance(item.get('execution_id'), str) for item in state['ledger'])
                or type(state.get('enabled')) is not bool or state.get('configured') is not True
                or not isinstance(state.get('policy'), dict) or set(state['policy']) != set(LIMITS)
                or any(type(state['policy'][k]) is not int or not lo <= state['policy'][k] <= hi for k, (lo, hi) in LIMITS.items())
                or type(state.get('rotation_cursor')) is not int or state['rotation_cursor'] < 0
                or type(state.get('interval_hours')) is not int or state.get('interval_hours') != state['policy']['interval_hours']
                or not isinstance(state.get('database_binding'), str)
                or not state.get('first_run_at')):
            raise ValueError()
        _time(state['first_run_at'])
        if state.get('last_slot_at'):
            _time(state['last_slot_at'])
        if state.get('active_execution') is not None and not isinstance(state['active_execution'], dict):
            raise ValueError()
        host = state.get('host_registration')
        if host is not None:
            if (not isinstance(host, dict) or not isinstance(host.get('id'), str)
                    or host.get('platform') not in {'windows-task', 'systemd'}
                    or host.get('readback_verified') is not True or host.get('enabled') is not True
                    or host.get('interval_hours') != state['interval_hours']
                    or not host.get('first_run_at') or not host.get('verified_at')):
                raise ValueError()
            if _time(host['first_run_at']) != _time(state['first_run_at']):
                raise ValueError()
            _time(host['verified_at'])
        if state['enabled'] and host is None:
            raise ValueError()
        for item in state['ledger']:
            if not item.get('triggered_at'):
                raise ValueError()
            _time(item['triggered_at'])
            if item.get('backup') is not None and not isinstance(item['backup'], dict):
                raise ValueError()
            if type(item.get('natural')) is not bool:
                raise ValueError()
        active = state.get('active_execution')
        if active is not None:
            if (not isinstance(active.get('execution_id'), str)
                    or active['execution_id'] not in {item['execution_id'] for item in state['ledger']}
                    or not isinstance(active.get('run_ids'), list) or not 1 <= len(active['run_ids']) <= 1
                    or any(not isinstance(key, str) or not key.startswith('run-') for key in active['run_ids'])):
                raise ValueError()
            if not active.get('triggered_at'):
                raise ValueError()
            _time(active['triggered_at'])
        return state
    except (ValueError, TypeError, KeyError) as error:
        raise DatabaseUnavailable('调度状态无法可靠读取，请显式核对隔离宿主登记。') from error


def _save(connection, state):
    connection.execute('INSERT INTO metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (STATE_KEY, json.dumps(state, ensure_ascii=False, sort_keys=True)))


def _registration(value, first_run, interval, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get('platform') not in {'windows-task', 'systemd'}
            or not isinstance(value.get('id'), str) or not 1 <= len(value['id']) <= 180
            or any(ord(char) < 32 for char in value['id'])
            or value.get('readback_verified') is not True
            or value.get('interval_hours') != interval or not value.get('first_run_at')
            or _time(value.get('first_run_at')) != first_run
            or value.get('enabled') is not True
            or not value.get('verified_at') or _time(value['verified_at']) > now):
        raise ValueError('宿主任务必须具有本次注册、周期、首个计划和启用状态的真实回读。')
    # Paths, arguments, credentials and arbitrary host output never enter the ledger.
    return {key: value[key] for key in ('id', 'platform', 'readback_verified', 'interval_hours',
                                      'first_run_at', 'verified_at', 'enabled')}


@contextmanager
def scheduler_lock(database_path):
    path = Path(database_path).resolve()
    if not path.is_file():
        raise DatabaseUnavailable('调度不创建业务库，请先显式初始化独立新库。')
    with _file_lock(path.with_name(path.name + '.scheduler.lock'), 0, RefreshBusy):
        yield


def configure(database_path, *, first_run_at, host_registration=None, policy=None, current_time=None):
    now = _time(current_time)
    first_run = _time(first_run_at)
    parameters = read_policy() if policy is None else deepcopy(policy)
    # Validate supplied policy with the same strict bounds, without writing a file.
    if set(parameters) != set(LIMITS) or any(type(parameters[k]) is not int or not lo <= parameters[k] <= hi for k, (lo, hi) in LIMITS.items()):
        raise ValueError('运行配置超出登记范围。')
    registration = _registration(host_registration, first_run, parameters['interval_hours'], now)
    with scheduler_lock(database_path), writer_transaction(database_path) as (connection, metadata):
        prior = _state(metadata)
        if prior and prior.get('active_execution'):
            raise ValueError('存在未核对的运行，先通过 tick 恢复中断登记，再重配。')
        if prior and prior.get('enabled') and registration != prior.get('host_registration'):
            raise ValueError('已有宿主登记不会被覆盖；先显式停用并核对旧任务。')
        state = {'schema_version': 1, 'configured': True, 'enabled': bool(registration),
                 'policy': parameters, 'interval_hours': parameters['interval_hours'],
                 'first_run_at': first_run.isoformat(), 'host_registration': registration,
                 'next_run_at': first_run.isoformat() if registration else None,
                 'last_slot_at': prior.get('last_slot_at') if prior else None,
                 'rotation_cursor': prior.get('rotation_cursor', 0) if prior else 0,
                 'active_execution': None, 'ledger': prior.get('ledger', []) if prior else [],
                 'database_binding': _binding(connection), 'configured_dataset_id': metadata['dataset_id'],
                 'configured_at': now.isoformat()}
        state['ledger'] = state['ledger'][-parameters['ledger_limit']:]
        _save(connection, state)
        return schedule_projection(connection, {**metadata, STATE_KEY: json.dumps(state)}, now)


def disable(database_path, current_time=None):
    with scheduler_lock(database_path), writer_transaction(database_path) as (connection, metadata):
        state = _state(metadata)
        if not state:
            return {'status': 'not_ready', 'enabled': False, 'next_run_at': None}
        state.update(enabled=False, disabled_at=_stamp(current_time), next_run_at=None)
        _save(connection, state)
        return schedule_projection(connection, {**metadata, STATE_KEY: json.dumps(state)}, current_time)


def schedule_projection(connection, metadata, current_time=None):
    now = _time(current_time)
    result = {'dataset_id': metadata['dataset_id'], 'data_mode': metadata['data_mode'],
              'enabled': False, 'status': 'not_ready', 'next_run_at': None,
              'overdue_since': None, 'last_execution': None, 'ledger': [],
              'interval_hours': None, 'natural_run_count': None, 'continuous_days': None}
    try:
        state = _state(metadata)
    except DatabaseUnavailable:
        result.update(status='unknown', reason='invalid_schedule_state')
        return result
    if state is None:
        return result
    result.update(interval_hours=state.get('interval_hours'), ledger=deepcopy(state['ledger']),
                  last_execution=deepcopy(state['ledger'][-1]) if state['ledger'] else None,
                  first_run_at=state.get('first_run_at'),
                  host_registration=deepcopy(state.get('host_registration')))
    natural = [item for item in state['ledger'] if item.get('natural') and item.get('data_mode') == 'real']
    result['natural_run_count'] = len(natural) if natural else None
    result['successful_natural_runs'] = sum(item.get('business_status') == 'complete' and item.get('process_exit_code') == 0
        and (item.get('backup') or {}).get('status') == 'complete' for item in natural) if natural else None
    result['ledger_window'] = {'retained_executions': len(state['ledger']), 'limit': state.get('policy', {}).get('ledger_limit', 50),
                               'statistics_scope': 'retained_ledger', 'is_lifetime_total': False}
    # Actual observed calendar days, not an asserted consecutive healthy period.
    result['observed_natural_days'] = len({_time(item['triggered_at']).astimezone(timezone(timedelta(hours=8))).date() for item in natural}) if natural else None
    if state.get('database_binding') != _binding(connection):
        result.update(status='not_ready', reason='restored_path_requires_host_registration')
        return result
    if not state['enabled']:
        result['status'] = 'disabled' if state.get('disabled_at') else 'not_ready'
        return result
    if not state.get('host_registration', {}).get('readback_verified'):
        return result
    result['enabled'] = True
    if state.get('active_execution'):
        result.update(status='running', active_execution=deepcopy(state['active_execution']))
        return result
    try:
        next_run = _time(state['next_run_at']) if state.get('next_run_at') else None
    except (ValueError, TypeError):
        next_run = None
    if next_run is None:
        result['status'] = 'unknown'
    elif next_run < now:
        result.update(status='overdue', overdue_since=state['next_run_at'])
    else:
        result.update(status='scheduled', next_run_at=state['next_run_at'])
    return result


def _recover(connection, state, now):
    active = state.get('active_execution')
    if not active:
        return
    for item in state['ledger']:
        if item['execution_id'] == active['execution_id']:
            item.update(status='interrupted', business_status='interrupted', recovered_at=now.isoformat(),
                        finished_at=now.isoformat(), process_exit_code=None)
    for run_id in active.get('run_ids', []):
        connection.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE id=? AND status='running'", (now.isoformat(), run_id))
    state['active_execution'] = None


def tick(database_path, *, trigger='manual', registration_id=None, current_time=None, runner=None, backup_directory=None):
    """Claim one due slot, run a bounded child, then record actual child exit separately.

    The scheduler lock spans the process; SQLite writer locks span only the two
    bookkeeping transactions. The collector owns the existing refresh lock.
    """
    if trigger not in {'manual', 'scheduled'}:
        raise ValueError('触发类型仅接受 manual 或 scheduled。')
    now = _time(current_time)
    with scheduler_lock(database_path):
        # A previous scheduler may have died while its collector stayed alive.
        # Never declare that writer interrupted while it still owns refresh_lock.
        with refresh_lock(database_path), writer_transaction(database_path) as (connection, metadata):
            state = _state(metadata)
            if not state or not state['configured']:
                return {'status': 'not_ready', 'started': False}
            _recover(connection, state, now)
            if state.get('database_binding') != _binding(connection):
                _save(connection, state)
                return {'status': 'not_ready', 'started': False, 'reason': 'restored_path_requires_host_registration'}
            if not state['enabled']:
                _save(connection, state)
                return {'status': 'disabled', 'started': False}
            natural = trigger == 'scheduled'
            host = state.get('host_registration') or {}
            if natural and (not host.get('readback_verified') or not registration_id or registration_id != host.get('id')):
                raise ValueError('自然调度必须匹配已真实回读的宿主登记 ID。')
            first = _time(state['first_run_at'])
            if natural and now < first:
                _save(connection, state)
                return {'status': 'not_due', 'started': False, 'next_run_at': state['next_run_at']}
            slot = (first + timedelta(hours=state['interval_hours'] * int((now-first).total_seconds() // (state['interval_hours']*3600)))) if natural else now
            if natural and state.get('last_slot_at') and slot <= _time(state['last_slot_at']):
                _save(connection, state)
                return {'status': 'duplicate_slot', 'started': False, 'slot_at': slot.isoformat()}
            execution_id = 'execution-' + str(uuid4())
            run_id = 'run-' + str(uuid4())
            from backend.config import Settings
            from backend.version import PROJECT, VERSION, STAGE
            execution = {'execution_id': execution_id, 'trigger': trigger, 'natural': natural,
                         'project': PROJECT, 'version': VERSION, 'stage': STAGE,
                         'backend_commit': Settings.from_env(Path(database_path)).backend_commit,
                         'host_registration_id': host.get('id') if natural else None,
                         'slot_at': slot.isoformat(), 'triggered_at': now.isoformat(),
                         'status': 'running', 'business_status': None, 'business_completeness': None,
                         'process_exit_code': None, 'run_ids': [run_id], 'dataset_before': metadata['dataset_id'],
                         'dataset_after': None, 'data_mode': metadata['data_mode'], 'finished_at': None}
            state['ledger'].append(execution)
            state['ledger'] = state['ledger'][-state['policy']['ledger_limit']:]
            state['active_execution'] = deepcopy(execution)
            if natural:
                state['last_slot_at'] = slot.isoformat()
                # This is the verified repeating host's actual next planned slot.
                state['next_run_at'] = (slot + timedelta(hours=state['interval_hours'])).isoformat()
            _save(connection, state)
            policy = deepcopy(state['policy'])
            cursor = state['rotation_cursor']
        try:
            if runner is None:
                from ops.scheduler import run_collector
                runner = lambda db, policy, cursor, run_id, trigger: run_collector(db, policy, cursor, run_id, trigger, backup_directory=backup_directory)
            result = runner(Path(database_path).resolve(), policy, cursor, run_id, trigger)
        except BaseException:
            with refresh_lock(database_path), writer_transaction(database_path) as (connection, metadata):
                latest = _state(metadata)
                _recover(connection, latest, _time(current_time))
                _save(connection, latest)
            raise
        with writer_transaction(database_path) as (connection, metadata):
            latest = _state(metadata)
            entry = next(item for item in latest['ledger'] if item['execution_id'] == execution_id)
            business = result.get('business')
            exit_code = result.get('exit_code')
            if business is not None and business.get('run_id') != run_id:
                business = None
            entry.update(status='finished' if business else 'interrupted', finished_at=_stamp(current_time),
                         process_exit_code=exit_code, process_exit_scope='collector_child',
                         host_task_exit_code=None, business_status=business.get('status') if business else 'interrupted',
                         business_completeness='complete_for_selected_channels' if business and business.get('status') == 'complete' else 'partial' if business else None,
                         dataset_after=metadata['dataset_id'],
                         data_mode=metadata['data_mode'],
                         source_results=deepcopy(business.get('sources', [])) if business else [],
                         commits=deepcopy(business.get('commits')) if business else None,
                         failure_code=result.get('failure_code'), backup=deepcopy(result.get('backup')),
                         scheduler_exit_code=result.get('scheduler_exit_code', exit_code if exit_code is not None else 2))
            if not business:
                for key in entry['run_ids']:
                    connection.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE id=? AND status='running'", (entry['finished_at'], key))
            latest.update(active_execution=None, rotation_cursor=result.get('next_cursor', cursor + 1))
            _save(connection, latest)
            return {'started': True, **deepcopy(entry)}
