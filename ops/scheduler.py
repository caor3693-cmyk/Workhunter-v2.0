"""One explicit due tick, launched by an independently registered host timer."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

from backend.config import ROOT
from backend.domain.source_policy import FIXED_SCHOOLS, approved_hosts
from backend.services import scheduling
from backend.services.discovery import refresh_sources
from backend.sources import Fetcher
from backend.storage.database import DatabaseUnavailable, read_database
from backend.storage.write import RefreshBusy, WriterBusy


def registered_configs(database_path, schools_path=None):
    """Use only the fixed reviewed school configs already registered in this DB."""
    document = json.loads((Path(schools_path) if schools_path else ROOT / 'config/schools.json').read_text(encoding='utf-8'))
    schools = document.get('schools')
    if not isinstance(schools, list) or len(schools) != 10 or {s['school_key'] for s in schools} != FIXED_SCHOOLS:
        raise ValueError('调度仅允许已确认的固定十校。')
    configs = []
    with read_database(database_path) as (connection, _):
        for school in schools:
            for raw in school.get('sources', []):
                if raw['school_key'] != school['school_key']:
                    raise ValueError('来源登记不能跨校。')
                row = connection.execute('SELECT school_key,channel_key,official_entry_url FROM sources WHERE source_key=?', (raw['source_key'],)).fetchone()
                if not row:
                    continue
                if (row['school_key'], row['channel_key'], row['official_entry_url']) != (raw['school_key'], raw['channel_key'], raw['official_entry_url']):
                    raise ValueError('持久来源身份与已审配置不同，请先显式核对。')
                configs.append({**raw, 'campuses': school.get('campuses', [])})
    if not configs or len({c['source_key'] for c in configs}) != len(configs):
        raise ValueError('没有非重复的已登记来源，不能把配置数量当作运行成功。')
    return configs


def collect(database_path, policy, cursor, run_id, trigger, *, configs=None, adapters=None, transport=None, monotonic=time.monotonic):
    """The existing discovery service owns one round's refresh lock and commits."""
    configs = registered_configs(database_path) if configs is None else configs
    cursor = cursor % len(configs)
    ordered = configs[cursor:] + configs[:cursor]
    deadline = monotonic() + policy['round_seconds']
    with read_database(database_path) as (_, metadata):
        fixture = metadata['data_mode'] == 'isolated_fixture'

    def bounded_fetcher(config):
        remaining = max(0.001, deadline - monotonic())
        seconds = min(policy['source_seconds'], remaining)
        return Fetcher(material_root=Path(database_path).resolve().parent / 'materials',
                       allowed_hosts=approved_hosts(config['school_key']), school_key=config['school_key'],
                       max_requests=policy['max_requests'], max_seconds=seconds,
                       max_retries=policy['max_retries'], timeout_seconds=min(policy['timeout_seconds'], seconds))

    business = refresh_sources(database_path, ordered, adapters=adapters, transport=transport or bounded_fetcher,
                               school_keys=tuple(dict.fromkeys(c['school_key'] for c in ordered)),
                               page_budget=policy['page_budget'], detail_budget=policy['detail_budget'],
                               fixture=fixture, run_id=run_id, trigger=trigger,
                               skip_restricted=True, round_deadline=deadline, monotonic=monotonic)
    pending = next((index for index, outcome in enumerate(business['sources']) if outcome['status'] == 'skipped_budget'), None)
    # An exhausted round starts with its first unattempted source next time;
    # a complete traversal rotates its starting source as well.
    next_cursor = (cursor + (pending if pending is not None else 1)) % len(configs)
    return {'business': business, 'next_cursor': next_cursor}


def run_collector(database_path, policy, cursor, run_id, trigger, *, backup_directory=None):
    if backup_directory is None:
        raise ValueError('自然运行需要明确的隔离备份目录。')
    arguments = [sys.executable, '-m', 'ops.scheduler', '_collect', '--db', str(database_path),
                 '--cursor', str(cursor), '--run-id', run_id, '--trigger', trigger]
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    child = subprocess.Popen(arguments, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding='utf-8', env=environment,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    failure = None
    try:
        stdout, _ = child.communicate(timeout=policy['round_seconds'] + 20)
    except subprocess.TimeoutExpired:
        child.kill()
        stdout, _ = child.communicate(timeout=15)
        failure = 'collector_round_timeout'
    result = {'exit_code': child.returncode, 'business': None, 'failure_code': failure}
    if failure is None and len(stdout) <= 1_048_576:
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict) and isinstance(payload.get('business'), dict) and payload['business'].get('run_id') == run_id:
                result.update(payload)
            else:
                result['failure_code'] = 'invalid_collector_receipt'
        except (ValueError, TypeError):
            result['failure_code'] = 'invalid_collector_receipt'
    elif failure is None:
        result['failure_code'] = 'collector_receipt_too_large'
    try:
        from ops.backup import create_backup
        receipt = create_backup(database_path, Path(backup_directory).resolve(), retain_count=7,
                                byte_cap=268435456, min_free_bytes=134217728, apply_retention=True, max_seconds=60)
        result['backup'] = {'status': 'complete', 'receipt': receipt}
    except (ValueError, RuntimeError, OSError):
        result['backup'] = {'status': 'failed', 'failure_code': 'consistent_backup_failed'}
    result['scheduler_exit_code'] = (child.returncode if child.returncode not in (None, 0) else
                                     2 if result['business'] is None or result['backup']['status'] != 'complete' else 0)
    return result


def verify_host_invocation(registration_id):
    """Read the host's live running task; a caller-supplied flag is insufficient."""
    if os.name == 'nt':
        prefix = 'windows-task:'
        if not registration_id or not registration_id.startswith(prefix):
            raise ValueError('当前宿主缺少 Windows 任务登记。')
        task_name = registration_id[len(prefix):]
        if not re.fullmatch(r'WorkhunterV2-M3-[A-Za-z0-9_-]+', task_name):
            raise ValueError('任务不属于隔离调度命名空间。')
        script = "$ErrorActionPreference='Stop'; $task=Get-ScheduledTask -TaskName $env:WH_VERIFY_TASK_NAME; $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; $taskSid=if($task.Principal.UserId -match '^S-\\d-'){$task.Principal.UserId}else{([Security.Principal.NTAccount]::new($task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value}; if([int]$task.State -ne 4 -or $taskSid -ne $sid -or [int]$task.Principal.RunLevel -ne 0){exit 2}; Write-Output 'verified'"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, timeout=15,
                                env={**os.environ, 'WH_VERIFY_TASK_NAME': task_name},
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0 or result.stdout.strip() != 'verified':
            raise ValueError('宿主没有回读到当前用户正在运行的已登记有限权限任务。')
    else:
        if registration_id != 'systemd:workhunter-v2-refresh.timer' or not re.fullmatch(r'[a-f0-9]{32}', os.environ.get('INVOCATION_ID', '')):
            raise ValueError('当前进程没有 systemd 自然调用身份。')
        result = subprocess.run(['systemctl', '--user', 'show', 'workhunter-v2-refresh.service',
                                 '--property=MainPID', '--value'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0 or result.stdout.strip() != str(os.getpid()):
            raise ValueError('systemd 当前运行进程与本次 tick 不同。')


def exact_backend_commit(value):
    if not re.fullmatch(r'[0-9a-fA-F]{40}', value):
        raise argparse.ArgumentTypeError('backend-commit 必须是已核对的完整40位十六进制提交。')
    return value.lower()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Workhunter v2 隔离宿主调度；不安装任务或创建业务库')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('configure', 'tick', 'status', 'disable', '_collect'):
        command = commands.add_parser(name)
        command.add_argument('--db', type=Path, required=True)
        if name == 'configure':
            command.add_argument('--first-run', required=True)
            command.add_argument('--host-registration', type=Path)
        elif name == 'tick':
            command.add_argument('--trigger', choices=('scheduled', 'manual'), default='manual')
            command.add_argument('--registration-id')
            command.add_argument('--backup-directory', type=Path, required=True)
            command.add_argument('--backend-commit', type=exact_backend_commit,
                                 help='安装时从干净源码核对的完整提交；通过本进程环境传给采集子进程')
            command.add_argument('--source-dns-mode', choices=('system', 'cloudflare-doh'),
                                 help='固定公开来源 DNS 模式；省略时保留已登记宿主环境')
        elif name == '_collect':
            command.add_argument('--cursor', type=int, required=True)
            command.add_argument('--run-id', required=True)
            command.add_argument('--trigger', choices=('scheduled', 'manual'), required=True)
    options = parser.parse_args(argv)
    try:
        if options.command == 'configure':
            host = json.loads(options.host_registration.read_text(encoding='utf-8-sig')) if options.host_registration else None
            result = scheduling.configure(options.db, first_run_at=options.first_run, host_registration=host)
        elif options.command == 'disable':
            result = scheduling.disable(options.db)
        elif options.command == 'status':
            with read_database(options.db) as (connection, metadata):
                result = scheduling.schedule_projection(connection, metadata)
        elif options.command == 'tick':
            if options.backend_commit:
                os.environ['WH_BACKEND_COMMIT'] = options.backend_commit
            if options.source_dns_mode:
                os.environ['WH_SOURCE_DNS_MODE'] = options.source_dns_mode
            if options.trigger == 'scheduled':
                verify_host_invocation(options.registration_id)
            result = scheduling.tick(options.db, trigger=options.trigger, registration_id=options.registration_id,
                                     backup_directory=options.backup_directory)
        else:
            with read_database(options.db) as (_, metadata):
                state = scheduling._state(metadata)
            if not state or not state.get('active_execution') or options.run_id not in state['active_execution']['run_ids']:
                raise ValueError('采集子进程必须绑定当前已登记的执行身份。')
            result = collect(options.db, state['policy'], options.cursor, options.run_id, options.trigger)
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=False))
        if options.command == '_collect':
            return 1 if result['business']['status'] == 'failed' else 0
        return result.get('scheduler_exit_code', 0) if options.command == 'tick' else 0
    except (DatabaseUnavailable, RefreshBusy, WriterBusy, ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        # Never print arbitrary exception text, secret arguments or private paths.
        if sys.stderr:
            print('隔离调度未完成，请通过受保护诊断核对宿主、登记、锁与备份状态。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
