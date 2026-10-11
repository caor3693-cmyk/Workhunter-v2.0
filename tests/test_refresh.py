"""Real process exclusion and rollback around the shared SQLite writer."""

import subprocess
import sys

import pytest

from backend.config import ROOT
from backend.storage.database import DatabaseUnavailable, initialize_database, read_database
from backend.storage.write import RefreshBusy, WriterBusy, refresh_lock, writer_transaction


@pytest.mark.parametrize("lock_name,error", [("writer_transaction", WriterBusy), ("refresh_lock", RefreshBusy)])
def test_write_and_whole_refresh_locks_exclude_other_processes(tmp_path, lock_name, error):
    database = tmp_path / "fixture.sqlite3"
    initialize_database(database, fixture=True)
    code = "from pathlib import Path; import sys; from backend.storage.write import " + lock_name + ";\nwith " + lock_name + "(Path(sys.argv[1])):\n print('locked',flush=True)\n sys.stdin.readline()\n"
    process = subprocess.Popen([sys.executable, "-c", code, str(database)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        lock = writer_transaction(database, timeout_seconds=0.1) if lock_name == "writer_transaction" else refresh_lock(database)
        with pytest.raises(error):
            with lock:
                pytest.fail("a second process entered the exclusive boundary")
    finally:
        process.communicate("release\n", timeout=15)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    assert process.returncode == 0
    with writer_transaction(database, timeout_seconds=0):
        pass
    with refresh_lock(database):
        pass


def test_exception_rolls_back_metadata_and_release_allows_next_writer(tmp_path):
    database = tmp_path / "fixture.sqlite3"
    initial = initialize_database(database, fixture=True)
    with pytest.raises(RuntimeError, match="interrupted"):
        with writer_transaction(database) as (connection, _):
            connection.execute("UPDATE metadata SET value='uncommitted' WHERE key='dataset_id'")
            raise RuntimeError("interrupted")
    with read_database(database) as (_, metadata):
        assert metadata == initial
    with writer_transaction(database, timeout_seconds=0):
        pass


def test_write_and_refresh_never_create_a_missing_database_or_directory(tmp_path):
    missing = tmp_path / "absent" / "business.sqlite3"
    for boundary in (writer_transaction, refresh_lock):
        with pytest.raises(DatabaseUnavailable):
            with boundary(missing):
                pass
    assert not missing.parent.exists()
