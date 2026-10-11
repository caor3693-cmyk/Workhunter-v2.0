"""Windows launcher checks use synthetic databases and only test-owned processes."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import httpx
import pytest

from backend.storage.database import initialize_database


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe') or shutil.which('pwsh')
pytestmark = pytest.mark.skipif(os.name != 'nt' or not POWERSHELL, reason='Windows process launcher requires PowerShell')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, encoding='utf-8').strip()


@pytest.fixture
def launcher(tmp_path):
    repo = tmp_path / 'isolated-launcher'
    repo.mkdir()
    shutil.copytree(ROOT / 'backend', repo / 'backend', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (repo / 'scripts').mkdir()
    (repo / 'config').mkdir()
    shutil.copy2(ROOT / 'scripts/start_local_api.ps1', repo / 'scripts/start_local_api.ps1')
    shutil.copy2(ROOT / 'config/schools.json', repo / 'config/schools.json')
    shutil.copy2(ROOT / '.gitignore', repo / '.gitignore')
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Isolated launcher test')
    git(repo, 'config', 'user.email', 'launcher@example.invalid')
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'frozen synthetic launcher')
    database = repo / '.runtime/isolated.sqlite3'
    metadata = initialize_database(database)
    runtime = repo / '.runtime/launch'
    yield repo, database, runtime, metadata
    ready = runtime / 'api.ready.json'
    if ready.exists():
        identity = json.loads(ready.read_text(encoding='utf-8-sig'))
        pid = identity.get('launcher_pid', identity['pid'])
        subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'], capture_output=True, timeout=10)


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def start(launcher, port, timeout=8):
    repo, database, runtime, _ = launcher
    environment = dict(os.environ)
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        environment[name] = 'http://127.0.0.1:1'
    args = [
        POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        str(repo / 'scripts/start_local_api.ps1'), '-Port', str(port), '-Database', str(database),
        '-RuntimeDirectory', str(runtime), '-PythonPath', sys.executable,
        '-ReadinessTimeoutSeconds', str(timeout),
    ]
    runtime.mkdir(parents=True, exist_ok=True)
    output = runtime / 'launcher.stdout.log'
    errors = runtime / 'launcher.stderr.log'
    with output.open('wb') as stdout, errors.open('wb') as stderr:
        process = subprocess.Popen(args, cwd=repo, env=environment, stdout=stdout, stderr=stderr)
        try:
            returncode = process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=10)
            raise
    return subprocess.CompletedProcess(args, returncode, output.read_text(encoding='utf-8', errors='replace'), errors.read_text(encoding='utf-8', errors='replace'))


def test_launcher_waits_for_matching_actual_identity_without_environment_proxy(launcher):
    repo, _, runtime, metadata = launcher
    port = free_port()
    result = start(launcher, port)
    assert result.returncode == 0, 'Isolated API launcher did not reach readiness'
    ready = json.loads((runtime / 'api.ready.json').read_text(encoding='utf-8-sig'))
    assert ready['backend_commit'] == git(repo, 'rev-parse', 'HEAD')
    assert ready['dataset_id'] == metadata['dataset_id']
    assert ready['data_mode'] == 'empty'
    assert ready['project'] == 'Workhunter-v2.0'
    assert ready['port'] == port
    assert ready['pid'] == ready['listener_pid']
    assert ready['launcher_pid'] > 0 and ready['listener_pid'] > 0
    owner = subprocess.check_output([POWERSHELL, '-NoProfile', '-Command',
                                   f'(Get-NetTCPConnection -State Listen -LocalPort {port} | Select-Object -ExpandProperty OwningProcess -Unique)'],
                                   text=True, encoding='utf-8').strip()
    assert int(owner) == ready['listener_pid']
    token = (runtime / 'service-token').read_text(encoding='utf-8').strip()
    safe_output = token not in result.stdout + result.stderr
    assert safe_output, 'Private startup material appeared in output'
    with httpx.Client(trust_env=False, timeout=2, headers={'Authorization': 'Bearer ' + token}) as client:
        health = client.get(f'http://127.0.0.1:{port}/health').json()
        version = client.get(f'http://127.0.0.1:{port}/version').json()
    assert health['status'] == 'ok' and health['database'] == 'readable'
    assert version['backend_commit'] == ready['backend_commit']
    assert version['dataset_id'] == health['dataset_id'] == ready['dataset_id']


def test_port_conflict_does_not_stop_existing_listener_or_write_readiness(launcher):
    _, _, runtime, _ = launcher
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = start(launcher, port)
        assert result.returncode != 0
        assert listener.getsockname()[1] == port
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            pass
    assert not (runtime / 'api.ready.json').exists()
    assert not (runtime / 'api.pid').exists()


def test_unreadable_database_never_reports_ready_or_leaves_new_api_running(launcher):
    _, database, runtime, _ = launcher
    database.write_bytes(b'not a SQLite database')
    port = free_port()
    result = start(launcher, port, timeout=3)
    assert result.returncode != 0
    assert not (runtime / 'api.ready.json').exists()
    assert not (runtime / 'api.pid').exists()
    listeners = subprocess.check_output([POWERSHELL, '-NoProfile', '-Command',
                                       f'@(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue).Count'],
                                       text=True, encoding='utf-8').strip()
    assert int(listeners) == 0
    with pytest.raises((ConnectionRefusedError, TimeoutError)):
        socket.create_connection(('127.0.0.1', port), timeout=1)
