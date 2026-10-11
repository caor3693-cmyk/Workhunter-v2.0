"""Check the whole PR with the checker and scope table from its actual base."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


CHECKER_PATH = 'scripts/check_scope.py'
SCOPES_PATH = 'scripts/work_package_scopes.json'


class ScopeError(ValueError):
    """An unavailable trust root or invalid declaration must fail closed."""


def git_bytes(*args):
    result = subprocess.run(['git', *args], capture_output=True)
    if result.returncode:
        raise ScopeError(f'Git cannot read trusted scope input: {args[0]}')
    return result.stdout


def commit(ref):
    if not ref or ref.startswith('-'):
        raise ScopeError('A real base/head commit is required')
    return git_bytes('rev-parse', '--verify', f'{ref}^{{commit}}').decode().strip()


def target_blob(base, path):
    try:
        return git_bytes('show', f'{base}:{path}')
    except ScopeError as error:
        raise ScopeError(f'Trusted target is missing {path}; establish governance first') from error


def trusted_scopes(base):
    checker = target_blob(base, CHECKER_PATH)
    if hashlib.sha256(Path(__file__).read_bytes()).digest() != hashlib.sha256(checker).digest():
        raise ScopeError('Execute scripts/check_scope.py exported from the actual base SHA')
    try:
        scopes = json.loads(target_blob(base, SCOPES_PATH))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ScopeError('Trusted work-package table is not valid JSON') from error
    if not isinstance(scopes, dict) or scopes.get('schema_version') != 1 or not isinstance(scopes.get('packages'), dict):
        raise ScopeError('Trusted work-package table has an unsupported schema')
    management = scopes.get('management_paths', [])
    if not isinstance(management, list) or not all(isinstance(rule, str) for rule in management):
        raise ScopeError('Trusted management paths must be a list of repository paths')
    for name, package in scopes['packages'].items():
        if not isinstance(package, dict) or not package.get('issues') or not package.get('paths') or not package.get('branch_prefixes'):
            raise ScopeError(f'Trusted work package {name} is incomplete')
        for field in ('issues', 'related_issues'):
            values = package.get(field, [])
            if not isinstance(values, list) or not all(type(issue) is int and issue > 0 for issue in values):
                raise ScopeError(f'Trusted work package {name} has invalid Issue mapping')
        for field in ('paths', 'forbidden_paths', 'branch_prefixes'):
            values = package.get(field, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ScopeError(f'Trusted work package {name} has invalid {field}')
        for rule in package['paths'] + package.get('forbidden_paths', []) + management:
            validate_path(rule.rstrip('/'))
    return scopes


def validate_path(path):
    if not path or '\\' in path or path.startswith('/') or ':' in path:
        raise ScopeError(f'Non-repository path in scope input: {path!r}')
    if any(part in ('.', '..') for part in path.split('/')) or str(PurePosixPath(path)) != path:
        raise ScopeError(f'Non-canonical repository path in scope input: {path!r}')


def split_values(values):
    return [item for value in values or [] for item in re.split(r'[\s,]+', value.strip()) if item]


def body_field(body, name, required=True):
    matches = re.findall(rf'^{re.escape(name)}:[ \t]*([^\r\n]*)\r?$', body, re.M)
    if len(matches) != 1 or not matches[0].strip():
        if not required and not matches:
            return None
        raise ScopeError(f'PR needs exactly one non-empty {name}: declaration')
    return matches[0].strip()


def event_declaration(path, event_name):
    try:
        event = json.loads(Path(path).read_text(encoding='utf-8'))
        if event_name == 'pull_request':
            pr = event['pull_request']
            body = pr.get('body') or ''
            return {
                'base': pr['base']['sha'], 'head': pr['head']['sha'], 'branch': pr['head']['ref'],
                'packages': split_values([body_field(body, 'Work-Packages')]),
                'issues': split_values([body_field(body, 'Work-Issues')]),
                'integration': body_field(body, 'Integration', required=False),
            }
        if event_name == 'workflow_dispatch':
            inputs = event['inputs']
            return {
                'base': inputs['base'], 'head': inputs['head'], 'branch': inputs['branch'],
                'packages': split_values([inputs['packages']]), 'issues': split_values([inputs['issues']]),
                'integration': inputs.get('integration') or None,
            }
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ScopeError('Workflow event has no complete actual PR/work-package declaration') from error
    raise ScopeError('Only pull_request and explicit workflow_dispatch scope events are supported')


def checked_packages(scopes, declaration):
    supplied = declaration['packages']
    if not supplied:
        raise ScopeError('Work package declaration is missing')
    aliases = scopes.get('aliases', {})
    packages = [aliases.get(name, name) for name in supplied]
    if len(packages) != len(set(packages)):
        raise ScopeError('Duplicate work packages, including aliases, are not allowed')
    for name in packages:
        if name not in scopes['packages']:
            raise ScopeError(f'Unknown work package: {name}')
    try:
        issues = {int(value.removeprefix('#')) for value in declaration['issues']}
    except ValueError as error:
        raise ScopeError('Work-Issues must contain positive Issue numbers') from error
    if not issues or any(issue <= 0 for issue in issues):
        raise ScopeError('Work-Issues must contain positive Issue numbers')
    required = {issue for name in packages for issue in scopes['packages'][name]['issues']}
    allowed = required | {issue for name in packages for issue in scopes['packages'][name].get('related_issues', [])}
    if not required.issubset(issues) or not issues.issubset(allowed):
        raise ScopeError(f'Issue declaration does not match {", ".join(packages)}; required={sorted(required)}, allowed={sorted(allowed)}')
    integration = declaration.get('integration')
    branch = declaration['branch']
    if len(packages) > 1:
        registered = scopes.get('integrations', {}).get(integration)
        if not registered or set(registered['packages']) != set(packages):
            raise ScopeError('Cross-package PR needs an exact registered Integration declaration')
        prefixes = registered['branch_prefixes']
    else:
        if integration:
            raise ScopeError('Single-package PR must not claim an Integration')
        prefixes = scopes['packages'][packages[0]]['branch_prefixes']
    if not branch or not any(branch.startswith(prefix) and len(branch) > len(prefix) for prefix in prefixes):
        raise ScopeError(f'Actual head branch {branch!r} does not match the declared work package')
    return packages, sorted(issues)


def changed_paths(base, head):
    """NUL-separated status records include both old and new names of a rename."""
    parts = git_bytes('diff', '--name-status', '-z', '--find-renames', base, head, '--').decode('utf-8').split('\0')
    files = []
    index = 0
    while index < len(parts) and parts[index]:
        status = parts[index]
        count = 2 if status.startswith(('R', 'C')) else 1
        paths = parts[index + 1:index + 1 + count]
        if len(paths) != count or not all(paths):
            raise ScopeError('Cannot read complete PR path records')
        files.extend(paths)
        index += count + 1
    return sorted(set(files))


def matches(path, rule):
    return path.startswith(rule) if rule.endswith('/') else path == rule


def rejected(files, scopes, packages):
    management = scopes.get('management_paths', [])
    invalid = []
    for path in files:
        validate_path(path)
        if not any(
            any(matches(path, rule) for rule in scopes['packages'][name]['paths'] + management)
            and not any(matches(path, rule) for rule in scopes['packages'][name].get('forbidden_paths', []))
            for name in packages
        ):
            invalid.append(path)
    return invalid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--package', action='append')
    parser.add_argument('--issue', action='append')
    parser.add_argument('--branch')
    parser.add_argument('--integration')
    parser.add_argument('--event-file')
    parser.add_argument('--event-name', choices=('pull_request', 'workflow_dispatch'))
    parser.add_argument('--paths', nargs='*', help='Diagnostic only; CI always checks the complete PR')
    args = parser.parse_args()
    try:
        declaration = event_declaration(args.event_file, args.event_name) if args.event_file else {
            'base': args.base, 'head': args.head, 'packages': split_values(args.package),
            'issues': split_values(args.issue), 'branch': args.branch, 'integration': args.integration,
        }
        if args.event_file and args.paths is not None:
            raise ScopeError('Workflow checks cannot replace the complete PR diff with --paths')
        base, head = commit(declaration['base']), commit(declaration['head'])
        if args.event_file and args.event_name == 'workflow_dispatch':
            branch = declaration['branch']
            git_bytes('check-ref-format', '--branch', branch)
            remote_head = commit(f'refs/remotes/origin/{branch}')
            if remote_head != head:
                raise ScopeError('workflow_dispatch head does not equal the actual origin branch SHA')
        scopes = trusted_scopes(base)
        packages, issues = checked_packages(scopes, declaration)
        diff_base = git_bytes('merge-base', base, head).decode().strip()
        if not diff_base:
            raise ScopeError('Actual base/head have no common PR diff baseline')
        files = args.paths if args.paths is not None else changed_paths(diff_base, head)
        invalid = rejected(files, scopes, packages)
        report = {
            'base': base, 'head': head, 'diff_base': diff_base, 'branch': declaration['branch'], 'packages': packages,
            'issues': issues, 'integration': declaration.get('integration'),
            'mode': 'diagnostic-paths' if args.paths is not None else 'complete-pr', 'paths': files,
        }
        print(json.dumps(report, ensure_ascii=False))
        if invalid:
            raise ScopeError('Outside trusted work-package scope: ' + ', '.join(invalid))
        print(f'{", ".join(packages)}: {len(files)} paths within actual target scope')
        return 0
    except (ScopeError, OSError, UnicodeDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
