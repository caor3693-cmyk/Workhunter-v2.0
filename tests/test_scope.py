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


M2_PACKAGES = {
    'GOV-M2': ('32', 'codex/gov-m2-test', ['scripts/work_package_scopes.json', 'tests/test_scope.py']),
    'DOC-M2': ('32', 'codex/doc-m2-test', ['docs/CONTRACTS.md', 'docs/TASKS.md']),
    'CORE-M2': ('33,34,35', 'codex/core-m2-test', [
        'backend/domain/source_policy.py', 'backend/sources/registry.py', 'backend/services/semantic_revision.py',
        'backend/storage/migrations.py', 'tests/test_core_m2.py', 'tests/test_semantic_revision.py']),
    'M1-UI': ('29,30', 'codex/m1-ui-test', [
        'frontend/components/cards.js', 'frontend/pages/shared.js', 'ops/preview/worker.mjs', 'scripts/measure_m1.mjs']),
    'M1-SOURCES': ('31', 'codex/m1-sources-test', [
        'backend/sources/scut.py', 'backend/sources/gdut.py', 'tests/fixtures/scut/current_electrical.html']),
    'W03': ('12', 'codex/w03-test', [
        'backend/sources/ncepu.py', 'backend/sources/csu.py', 'tests/fixtures/hnu/list.html', 'config/schools.json']),
    'W04-A': ('13', 'codex/w04-a-test', [
        'backend/api/auth.py', 'backend/api/maintenance.py', 'backend/services/maintenance.py',
        'frontend/pages/maintenance.html', 'frontend/api/maintenance.js', 'ops/preview/worker.mjs']),
    'W04-B': ('14', 'codex/w04-b-test', [
        'backend/services/updates.py', 'backend/services/maintenance_tasks.py', 'frontend/components/updates.js']),
    'QA-M1': ('2', 'codex/qa-m1-test', [
        'frontend/pages/review.js', 'scripts/measure_m1.mjs', 'docs/MANUAL_QA.md', 'scripts/build_site.mjs']),
    'QA-M2': ('3', 'codex/qa-m2-test', [
        'scripts/verify_m2.mjs', 'scripts/prepare_m2_acceptance.py', 'tests/test_m2_acceptance.py', 'docs/MANUAL_QA.md']),
}
REPAIR_PACKAGES = 'CORE-M2,M1-UI,M1-SOURCES,QA-M1'
REPAIR_ISSUES = '33,34,35,29,30,31,2'
FULL_PACKAGES = REPAIR_PACKAGES + ',W03,W04-A,W04-B,QA-M2'
FULL_ISSUES = REPAIR_ISSUES + ',12,13,14,3'


def test_new_scope_registry_is_precise_and_retains_legacy_governance():
    scopes = json.loads(SCOPES.read_text(encoding='utf-8'))
    for name, (issues, _, _) in M2_PACKAGES.items():
        package = scopes['packages'][name]
        assert package['issues'] == [int(issue) for issue in issues.split(',')]
        assert not any(path.endswith('/') for path in package['paths'] if not path.startswith('tests/fixtures/'))
        assert not any(path in {'backend/', 'frontend/', 'tests/', 'config/', 'ops/', 'scripts/'} for path in package['paths'])
    assert scopes['packages']['GOV']['issues'] == [24]
    assert scopes['packages']['GOV']['paths'] == [
        '.github/workflows/checks.yml', 'scripts/check_scope.py', 'scripts/work_package_scopes.json', 'tests/test_scope.py']
    assert scopes['integrations']['M1-REPAIR']['packages'] == REPAIR_PACKAGES.split(',')
    assert scopes['integrations']['M1-M2']['packages'] == FULL_PACKAGES.split(',')
    assert scopes['integrations']['M1-REPAIR']['branch_prefixes'] == ['codex/m1-m2-integration-']
    assert scopes['integrations']['M1-M2']['branch_prefixes'] == ['codex/m1-m2-integration-']


@pytest.mark.parametrize('package', list(M2_PACKAGES))
def test_new_packages_accept_only_their_registered_declaration_and_files(scope_repo, package):
    repo, _, _ = scope_repo
    issues, branch, paths = M2_PACKAGES[package]
    for path in paths:
        if path == 'scripts/work_package_scopes.json':
            write(repo, path, SCOPES.read_text(encoding='utf-8') + '\n')
        else:
            write(repo, path)
    save(repo)
    result = check(scope_repo, package, issues, branch)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['mode'] == 'complete-pr' and report['packages'] == [package]
    assert report['paths'] == sorted(paths)


@pytest.mark.parametrize('package,path', [
    ('GOV-M2', 'docs/CONTRACTS.md'), ('GOV-M2', 'backend/services/ingestion.py'),
    ('DOC-M2', 'scripts/work_package_scopes.json'), ('DOC-M2', 'backend/domain/source_policy.py'),
    ('CORE-M2', 'backend/sources/ncepu.py'), ('CORE-M2', 'frontend/pages/home.js'),
    ('CORE-M2', 'backend/services/unregistered.py'), ('M1-UI', 'backend/storage/schema.sql'),
    ('M1-UI', 'frontend/pages/unrelated.js'), ('M1-SOURCES', 'backend/services/queries.py'),
    ('M1-SOURCES', 'backend/sources/shiep.py'), ('W03', 'backend/domain/source_policy.py'),
    ('W03', 'backend/storage/write.py'), ('W03', 'backend/sources/eleventh_school.py'),
    ('W03', 'tests/fixtures/not_fixed_school/list.html'), ('W04-A', 'backend/services/scheduler.py'),
    ('W04-A', 'backend/sources/gdut.py'), ('W04-B', 'backend/services/auth.py'),
    ('QA-M1', 'backend/api/app.py'), ('QA-M2', 'backend/storage/schema.sql'),
])
def test_new_packages_reject_neighboring_business_or_rule_paths(scope_repo, package, path):
    repo, _, _ = scope_repo
    issues, branch, _ = M2_PACKAGES[package]
    write(repo, path)
    save(repo)
    result = check(scope_repo, package, issues, branch)
    assert result.returncode == 1 and path in result.stderr


@pytest.mark.parametrize('issues', ['33,34', '33,35', '34,35', '33,34,35,24', '32', '33,34,99'])
def test_core_m2_requires_all_real_issues_and_no_unrelated_number(scope_repo, issues):
    result = check(scope_repo, 'CORE-M2', issues, 'codex/core-m2-test')
    assert result.returncode == 1 and 'Issue declaration' in result.stderr


@pytest.mark.parametrize('package,issues', [('W02', '9,10,29,30'), ('W01', '7,8,31'), ('GOV-M2', '24'), ('DOC-M2', '24')])
def test_new_issue_numbers_cannot_reuse_legacy_package_identity(scope_repo, package, issues):
    branch = 'codex/w02-test' if package == 'W02' else 'codex/w01-test' if package == 'W01' else M2_PACKAGES[package][1]
    result = check(scope_repo, package, issues, branch)
    assert result.returncode == 1 and 'Issue declaration' in result.stderr


@pytest.mark.parametrize('integration,packages,issues,paths', [
    ('M1-REPAIR', REPAIR_PACKAGES, REPAIR_ISSUES, [
        'backend/domain/source_policy.py', 'frontend/components/cards.js', 'backend/sources/scut.py', 'scripts/measure_m1.mjs']),
    ('M1-M2', FULL_PACKAGES, FULL_ISSUES, [
        'backend/sources/ncepu.py', 'backend/api/maintenance.py', 'backend/services/updates.py', 'scripts/verify_m2.mjs']),
])
def test_registered_m1_m2_integration_accepts_complete_diff(scope_repo, integration, packages, issues, paths):
    repo, _, _ = scope_repo
    for path in paths:
        write(repo, path)
    save(repo)
    result = check(scope_repo, packages, issues, 'codex/m1-m2-integration-test', ('--integration', integration))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['integration'] == integration and report['mode'] == 'complete-pr'
    assert report['paths'] == sorted(paths)


@pytest.mark.parametrize('packages,issues,integration', [
    (REPAIR_PACKAGES, REPAIR_ISSUES, 'M0-M1'),
    (REPAIR_PACKAGES, REPAIR_ISSUES, 'M1-M2'),
    (FULL_PACKAGES, FULL_ISSUES, 'M1-REPAIR'),
    (REPAIR_PACKAGES + ',GOV-M2', REPAIR_ISSUES + ',32', 'M1-REPAIR'),
    (FULL_PACKAGES + ',DOC-M2', FULL_ISSUES + ',32', 'M1-M2'),
    ('CORE-M2,M1-UI,M1-SOURCES', '33,34,35,29,30,31', 'M1-REPAIR'),
])
def test_m1_m2_integrations_reject_missing_extra_or_wrong_combinations(scope_repo, packages, issues, integration):
    result = check(scope_repo, packages, issues, 'codex/m1-m2-integration-test', ('--integration', integration))
    assert result.returncode == 1 and 'exact registered Integration' in result.stderr


@pytest.mark.parametrize('issues', ['33,34,35,29,30,31', REPAIR_ISSUES + ',24'])
def test_integration_also_rejects_missing_gate_or_unrelated_issue(scope_repo, issues):
    result = check(scope_repo, REPAIR_PACKAGES, issues, 'codex/m1-m2-integration-test', ('--integration', 'M1-REPAIR'))
    assert result.returncode == 1 and 'Issue declaration' in result.stderr


def test_m1_m2_integration_cannot_use_historical_m0_m1_branch(scope_repo):
    result = check(scope_repo, FULL_PACKAGES, FULL_ISSUES, 'codex/m0-m1-integration-test', ('--integration', 'M1-M2'))
    assert result.returncode == 1 and 'branch' in result.stderr


@pytest.mark.parametrize('source,destination', [
    ('AGENTS.md', 'backend/sources/ncepu.py'), ('backend/sources/ncepu.py', 'backend/services/queries.py'),
])
def test_m2_rename_checks_old_and_new_path(scope_repo, source, destination):
    repo, base, runner = scope_repo
    if source != 'AGENTS.md':
        write(repo, source)
        base = save(repo, 'target with rename source')
    target = repo / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    (repo / source).rename(target)
    save(repo, 'out of scope rename')
    result = check((repo, base, runner), 'W03', '12', 'codex/w03-test')
    assert result.returncode == 1
    report = json.loads(result.stdout.splitlines()[0])
    assert report['paths'] == sorted([source, destination])
    assert ('AGENTS.md' if source == 'AGENTS.md' else destination) in result.stderr


def test_new_registry_cannot_authorize_itself_against_legacy_target(scope_repo):
    repo, _, runner = scope_repo
    current = json.loads(SCOPES.read_text(encoding='utf-8'))
    legacy = json.loads(json.dumps(current))
    for package in M2_PACKAGES:
        del legacy['packages'][package]
    for integration in ['M1-REPAIR', 'M1-M2']:
        del legacy['integrations'][integration]
    write(repo, 'scripts/work_package_scopes.json', json.dumps(legacy))
    base = save(repo, 'old independently trusted target')
    write(repo, 'scripts/work_package_scopes.json', SCOPES.read_text(encoding='utf-8'))
    write(repo, 'tests/test_scope.py')
    save(repo, 'independent governance candidate')
    result = check((repo, base, runner), 'GOV', '24', 'codex/gov-m1-m2-test')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report['paths'] == ['scripts/work_package_scopes.json', 'tests/test_scope.py']
    result = check((repo, base, runner), 'GOV-M2', '32', 'codex/gov-m2-test')
    assert result.returncode == 1 and 'Unknown work package: GOV-M2' in result.stderr
    write(repo, 'backend/domain/source_policy.py')
    save(repo, 'business hidden in governance')
    result = check((repo, base, runner), 'GOV', '24', 'codex/gov-m1-m2-test')
    assert result.returncode == 1 and 'backend/domain/source_policy.py' in result.stderr


def test_new_business_candidate_cannot_expand_own_scope_or_checker(scope_repo):
    repo, _, _ = scope_repo
    scopes = json.loads(SCOPES.read_text(encoding='utf-8'))
    scopes['packages']['W03']['paths'].append('backend/')
    write(repo, 'scripts/work_package_scopes.json', json.dumps(scopes))
    write(repo, 'scripts/check_scope.py', 'raise SystemExit(0)\n')
    write(repo, 'backend/services/queries.py')
    save(repo, 'untrusted candidate tries self-authorization')
    result = check(scope_repo, 'W03', '12', 'codex/w03-test')
    assert result.returncode == 1
    for path in ['scripts/work_package_scopes.json', 'scripts/check_scope.py', 'backend/services/queries.py']:
        assert path in result.stderr
