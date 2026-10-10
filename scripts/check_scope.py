"""Check against TASKS.md from the target commit, never branch-local rules."""
import argparse
import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(['git', *args], text=True, encoding='utf-8').strip()


def allowed_paths(base, package):
    contract = git('show', f'{base}:docs/TASKS.md')
    section = re.search(rf'### {re.escape(package)} .*?(?=\n### |\n## |\Z)', contract, re.S)
    if not section:
        raise ValueError('Work package absent from trusted target TASKS.md')
    declaration = re.search(r'\*\*允许路径：\*\*(.*)', section.group())
    paths = re.findall(r'`([^`]+)`', declaration.group(1))
    if package == 'W00':
        paths += ['README.md', '.gitignore', '.openai/hosting.json', 'pyproject.toml', 'requirements.txt', 'requirements-dev.txt', 'package.json']
    paths += ['docs/STATUS.md', 'docs/BOARD.md', 'docs/ROADMAP.md', 'docs/PROJECT_SETUP.md', 'docs/deliveries/', 'config/project.json']
    return paths


def rejected(files, allowed):
    return [p for p in files if not any(p.startswith(rule) if rule.endswith('/') else p == rule for rule in allowed)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--package', required=True)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--paths', nargs='*')
    args = parser.parse_args()
    allowed = allowed_paths(args.base, args.package)
    files = args.paths if args.paths is not None else git('diff', '--no-renames', '--name-only', args.base, args.head).splitlines()
    invalid = rejected(files, allowed)
    if invalid:
        print('Outside trusted work-package scope: ' + ', '.join(invalid), file=sys.stderr)
        return 1
    print(f'{args.package}: {len(files)} paths within target-branch scope')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
