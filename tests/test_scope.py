"""Adversarial scope checks use a separate temporary Git repository."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'scripts' / 'check_scope.py'


def git(cwd, *args):
    return subprocess.check_output(['git', '-C', str(cwd), *args], text=True, encoding='utf-8').strip()


def test_rename_cannot_hide_forbidden_source_deletion(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Scope test')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/TASKS.md').write_text((ROOT / 'docs/TASKS.md').read_text(encoding='utf-8'), encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('Immutable rules\n', encoding='utf-8')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'trusted baseline')
    base = git(tmp_path, 'rev-parse', 'HEAD')
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'AGENTS.md').rename(tmp_path / 'backend/AGENTS.md')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'attempt hidden deletion')
    # Demonstrate why default rename detection is insufficient.
    assert git(tmp_path, 'diff', '--name-only', base, 'HEAD') == 'backend/AGENTS.md'
    result = subprocess.run([sys.executable, str(CHECKER), '--base', base, '--package', 'W00'], cwd=tmp_path, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 1
    assert 'AGENTS.md' in result.stderr
