"""Adversarial checks execute a frozen base checker in isolated Git repositories."""
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'scripts/check_scope.py'
SCOPES = ROOT / 'scripts/work_package_scopes.json'


def git(cwd, *args):
    return subprocess.check_output(['git', '-C', str(cwd), *args], text=True, encoding='utf-8').strip()


def write(repo, path, content='changed\n'):
    destination = repo / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding='utf-8')


def save(repo, message='candidate changes'):
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', message)
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def scope_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Scope test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'core.autocrlf', 'false')
    write(repo, 'scripts/check_scope.py', CHECKER.read_text(encoding='utf-8'))
    write(repo, 'scripts/work_package_scopes.json', SCOPES.read_text(encoding='utf-8'))
    write(repo, 'AGENTS.md', 'Immutable rules\n')
    base = save(repo, 'independently reviewed target')
    runner = tmp_path / 'frozen-target-checker.py'
    runner.write_bytes(subprocess.check_output(['git', '-C', str(repo), 'show', f'{base}:scripts/check_scope.py']))
    return repo, base, runner


def check(scope_repo, package='W01', issues='7,8', branch='codex/w01-test', extra=()):
    repo, base, runner = scope_repo
    args = [sys.executable, str(runner), '--base', base, '--head', 'HEAD']
    if package is not None:
        args += ['--package', package]
    args += ['--issue', issues, '--branch', branch, *extra]
    return subprocess.run(args, cwd=repo, text=True, capture_output=True, encoding='utf-8')


def test_w01_all_registered_write_dependencies_pass(scope_repo):
    repo, base, _ = scope_repo
    paths = ['backend/sources/scut.py', 'backend/storage/schema.sql', 'backend/storage/migrations.py',
             'backend/version.py', 'backend/cli.py', 'backend/worker.py', 'requirements.txt', 'pyproject.toml',
             'config/schools.json', 'backend/services/ingestion.py', 'docs/deliveries/two-school.md']
    for path in paths:
        write(repo, path)
    head = save(repo)
    result = check(scope_repo)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['base'] == base and report['head'] == head
    assert report['paths'] == sorted(paths) and report['mode'] == 'complete-pr'
    assert report['packages'] == ['W01-R3']


@pytest.mark.parametrize('path', [
    'frontend/pages/app.js', 'frontend/styles/app.css', 'backend/api/app.py',
    'backend/services/queries.py', 'AGENTS.md', 'docs/TASKS.md', 'docs/CONTRACTS.md',
    'scripts/work_package_scopes.json', 'scripts/check_scope.py', '.github/workflows/checks.yml',
    'backend/sources-extra/unrelated.py', 'data/real.db',
    'backend/sources/third_school.py', 'backend/domain/unrelated.py',
    'backend/services/scheduling.py', 'backend/storage/unrelated.py',
])
def test_w01_rejects_business_and_governance_escape(scope_repo, path):
    repo, _, _ = scope_repo
    write(repo, path)
    save(repo)
    result = check(scope_repo)
    assert result.returncode == 1
    assert path in result.stderr


def test_w02_projection_local_style_and_readme_pass(scope_repo):
    repo, _, _ = scope_repo
    for path in ['backend/services/queries.py', 'frontend/styles/app.css', 'README.md']:
        write(repo, path)
    save(repo)
    result = check(scope_repo, 'W02', '9,10', 'codex/w02-test')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('package,error', [(None, 'missing'), ('W00', 'Unknown'), ('W99', 'Unknown')])
def test_missing_and_unknown_package_fail(scope_repo, package, error):
    result = check(scope_repo, package)
    assert result.returncode == 1 and error in result.stderr


@pytest.mark.parametrize('issues', ['22', '7', '7,8,24', '0,7,8', 'seven,eight'])
def test_issue_declaration_must_match_actual_package(scope_repo, issues):
    result = check(scope_repo, issues=issues)
    assert result.returncode == 1 and 'Issue' in result.stderr


def test_business_branch_cannot_claim_governance(scope_repo):
    result = check(scope_repo, 'GOV', '24')
    assert result.returncode == 1 and 'branch' in result.stderr


def test_governance_claim_cannot_include_business_source(scope_repo):
    repo, _, _ = scope_repo
    write(repo, 'backend/sources/scut.py')
    save(repo)
    result = check(scope_repo, 'GOV', '24', 'codex/gov-test')
    assert result.returncode == 1 and 'backend/sources/scut.py' in result.stderr


def test_branch_local_rule_expansion_has_no_effect(scope_repo):
    repo, _, _ = scope_repo
    scopes = json.loads(SCOPES.read_text(encoding='utf-8'))
    scopes['packages']['W01-R3']['paths'].append('frontend/')
    write(repo, 'scripts/work_package_scopes.json', json.dumps(scopes))
    write(repo, 'frontend/pages/app.js')
    save(repo)
    result = check(scope_repo)
    assert result.returncode == 1
    assert 'scripts/work_package_scopes.json' in result.stderr and 'frontend/pages/app.js' in result.stderr


def test_untrusted_local_checker_cannot_self_authorize(scope_repo):
    _, _, runner = scope_repo
    runner.write_bytes(runner.read_bytes() + b'\n# changed candidate runner\n')
    result = check(scope_repo)
    assert result.returncode == 1 and 'exported from the actual base SHA' in result.stderr


@pytest.mark.parametrize('missing', ['scripts/check_scope.py', 'scripts/work_package_scopes.json'])
def test_target_missing_either_trust_input_fails(scope_repo, missing):
    repo, _, runner = scope_repo
    (repo / missing).unlink()
    base = save(repo, 'target lacking required governance')
    result = check((repo, base, runner))
    assert result.returncode == 1 and f'missing {missing}' in result.stderr


def test_missing_package_in_target_cannot_be_restored_locally(scope_repo):
    repo, _, runner = scope_repo
    scopes = json.loads(SCOPES.read_text(encoding='utf-8'))
    del scopes['packages']['W01-R3']
    write(repo, 'scripts/work_package_scopes.json', json.dumps(scopes))
    base = save(repo, 'target without W01')
    write(repo, 'scripts/work_package_scopes.json', SCOPES.read_text(encoding='utf-8'))
    save(repo)
    result = check((repo, base, runner))
    assert result.returncode == 1 and 'Unknown work package' in result.stderr


def test_check_covers_earlier_commits_not_just_latest(scope_repo):
    repo, _, _ = scope_repo
    write(repo, 'frontend/pages/app.js')
    save(repo, 'earlier forbidden frontend edit')
    write(repo, 'backend/sources/scut.py')
    save(repo, 'latest apparently valid adapter')
    result = check(scope_repo)
    assert result.returncode == 1 and 'frontend/pages/app.js' in result.stderr


def test_target_advance_is_not_a_candidate_deletion(scope_repo):
    repo, initial, runner = scope_repo
    git(repo, 'checkout', '-qb', 'independent-target')
    write(repo, 'frontend/pages/app.js')
    base = save(repo, 'target advances independently')
    git(repo, 'checkout', '-qb', 'source-candidate', initial)
    write(repo, 'backend/sources/scut.py')
    head = save(repo, 'candidate only changes adapter')
    result = check((repo, base, runner))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['base'] == base and report['head'] == head and report['diff_base'] == initial
    assert report['paths'] == ['backend/sources/scut.py']


def test_rename_cannot_hide_forbidden_old_path(scope_repo):
    repo, _, _ = scope_repo
    (repo / 'backend/sources').mkdir(parents=True)
    (repo / 'AGENTS.md').rename(repo / 'backend/sources/scut.py')
    save(repo, 'attempt hidden rule deletion')
    result = check(scope_repo)
    assert result.returncode == 1 and 'AGENTS.md' in result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['paths'] == ['AGENTS.md', 'backend/sources/scut.py']


def test_rename_cannot_hide_forbidden_new_path(scope_repo):
    repo, _, runner = scope_repo
    write(repo, 'backend/sources/scut.py')
    base = save(repo, 'target has adapter')
    (repo / 'frontend/pages').mkdir(parents=True)
    (repo / 'backend/sources/scut.py').rename(repo / 'frontend/pages/app.js')
    save(repo, 'rename into unrelated page')
    result = check((repo, base, runner))
    assert result.returncode == 1 and 'frontend/pages/app.js' in result.stderr


def test_cross_package_requires_explicit_exact_registered_integration(scope_repo):
    result = check(scope_repo, 'R1,R2', '22,21,23', 'codex/m0-m1-integration-test')
    assert result.returncode == 1 and 'Integration' in result.stderr
    result = check(scope_repo, 'R1,R2', '22,21,23', 'codex/m0-m1-integration-test', ('--integration', 'M0'))
    assert result.returncode == 0, result.stderr
    result = check(scope_repo, 'R1,W01', '22,7,8', 'codex/m0-m1-integration-test', ('--integration', 'M0'))
    assert result.returncode == 1 and 'exact registered' in result.stderr


def test_governance_and_doc_are_separate_from_business(scope_repo):
    repo, _, _ = scope_repo
    write(repo, 'docs/TASKS.md')
    write(repo, 'docs/CONTRACTS.md')
    save(repo)
    result = check(scope_repo, 'DOC', '24,10', 'codex/doc-test')
    assert result.returncode == 0, result.stderr
    result = check(scope_repo, 'GOV', '24', 'codex/gov-test')
    assert result.returncode == 1 and 'docs/TASKS.md' in result.stderr
    result = check(scope_repo, 'DOC,W01', '24,7,8', 'codex/m0-m1-integration-test', ('--integration', 'M0-M1'))
    assert result.returncode == 1 and 'exact registered' in result.stderr


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_pr_event_uses_actual_base_head_branch_and_declaration(scope_repo, tmp_path, newline):
    repo, base, runner = scope_repo
    write(repo, 'backend/services/queries.py')
    head = save(repo)
    event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': head, 'ref': 'codex/w02-test'},
                             'body': newline.join(['Work-Packages: W02', 'Work-Issues: 9,10', '', 'Refs #9, Refs #10'])}}
    path = tmp_path / 'event.json'
    path.write_text(json.dumps(event), encoding='utf-8')
    args = [sys.executable, str(runner), '--event-file', str(path), '--event-name', 'pull_request']
    result = subprocess.run(args, cwd=repo, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['base'] == base and report['head'] == head and report['branch'] == 'codex/w02-test'
    result = subprocess.run([*args, '--paths', 'README.md'], cwd=repo, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 1 and 'complete PR diff' in result.stderr


@pytest.mark.parametrize('body', ['', 'Work-Packages: W01\n', 'Work-Packages: W01\nWork-Packages: W02\nWork-Issues: 7,8'])
def test_missing_or_ambiguous_pr_declaration_fails(scope_repo, tmp_path, body):
    repo, base, runner = scope_repo
    event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': base, 'ref': 'codex/w01-test'}, 'body': body}}
    path = tmp_path / 'event.json'
    path.write_text(json.dumps(event), encoding='utf-8')
    result = subprocess.run([sys.executable, str(runner), '--event-file', str(path), '--event-name', 'pull_request'],
                            cwd=repo, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 1 and 'exactly one non-empty' in result.stderr


@pytest.mark.parametrize('contents', ['not-json', '[]', '{"schema_version": 2, "packages": {}}'])
def test_invalid_trusted_table_fails_explicitly(scope_repo, contents):
    repo, _, runner = scope_repo
    write(repo, 'scripts/work_package_scopes.json', contents)
    base = save(repo, 'invalid target governance')
    result = check((repo, base, runner))
    assert result.returncode == 1 and 'Trusted work-package table' in result.stderr


def test_dispatch_rejects_forged_branch_identity(scope_repo, tmp_path):
    repo, base, runner = scope_repo
    write(repo, 'backend/sources/scut.py')
    head = save(repo)
    branch = 'codex/w01-test'
    git(repo, 'update-ref', f'refs/remotes/origin/{branch}', head)
    event = {'inputs': {'base': base, 'head': head, 'branch': branch, 'packages': 'W01', 'issues': '7,8'}}
    path = tmp_path / 'dispatch.json'
    path.write_text(json.dumps(event), encoding='utf-8')
    args = [sys.executable, str(runner), '--event-file', str(path), '--event-name', 'workflow_dispatch']
    result = subprocess.run(args, cwd=repo, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    event['inputs']['head'] = base
    path.write_text(json.dumps(event), encoding='utf-8')
    result = subprocess.run(args, cwd=repo, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 1 and 'actual origin branch SHA' in result.stderr
    event['inputs']['branch'] = 'codex/w01-missing'
    path.write_text(json.dumps(event), encoding='utf-8')
    result = subprocess.run(args, cwd=repo, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 1 and 'Git cannot read trusted scope input' in result.stderr
