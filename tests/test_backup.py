"""Backup counterexamples use only temporary isolated stores."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import threading

import pytest

from backend.storage.database import initialize_database, read_database
from ops import backup


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "business" / "isolated.sqlite3"
    initialize_database(path, fixture=True)
    return path


def create(database, tmp_path, **options):
    return backup.create_backup(database, tmp_path / "backups", min_free_bytes=0, **options)


def test_consistent_snapshot_and_new_isolated_restore(database, tmp_path):
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE metadata SET value='real' WHERE key='data_mode'")
    writer.commit()
    writer.execute("UPDATE schools SET name='uncommitted' WHERE school_key='scut'")
    result = create(database, tmp_path)
    writer.rollback()
    writer.close()
    manifest = backup.verify_backup(result["backup"])
    assert manifest["data_mode"] == "real"
    assert manifest["table_counts"]["schools"] == 10
    assert manifest["table_counts"]["opportunities"] == 0
    assert manifest["scope"] == "database_only"
    assert manifest["raw_materials"] == "external_readonly_archive_required"
    isolated = tmp_path / "restore"
    isolated.mkdir()
    restored = backup.restore_backup(result["backup"], isolated / "new.sqlite3", min_free_bytes=0,
                                      expected_dataset_id=manifest["dataset_id"])
    assert restored["sha256"] == manifest["sha256"]
    with read_database(Path(restored["target"])) as (connection, metadata):
        assert metadata["dataset_id"] == manifest["dataset_id"]
        assert connection.execute("SELECT name FROM schools WHERE school_key='scut'").fetchone()[0] != "uncommitted"


def test_retention_only_after_verified_replacement_and_unmanaged_files_untouched(database, tmp_path):
    old = create(database, tmp_path)
    directory = tmp_path / "backups"
    unrelated = directory / "personal.sqlite3"
    unrelated.write_bytes(b"do not delete")
    with pytest.raises(backup.BackupError, match="显式"):
        create(database, tmp_path, retain_count=1)
    assert Path(old["backup"]).exists()
    current = create(database, tmp_path, retain_count=1, apply_retention=True)
    assert current["removed_verified"] == [Path(old["backup"]).name]
    assert not Path(old["backup"]).exists()
    assert unrelated.read_bytes() == b"do not delete"
    assert backup.verify_backup(current["backup"])["sha256"] == current["sha256"]


def test_corrupt_only_copy_is_protected_even_with_retention(database, tmp_path):
    result = create(database, tmp_path)
    saved = Path(result["backup"])
    saved.write_bytes(b"corrupt only copy")
    with pytest.raises(backup.BackupError, match="损坏"):
        create(database, tmp_path, retain_count=1, apply_retention=True)
    assert saved.read_bytes() == b"corrupt only copy"
    assert Path(result["manifest"]).is_file()


def test_low_capacity_does_not_delete_old_copy(database, tmp_path, monkeypatch):
    result = create(database, tmp_path)
    original = Path(result["backup"]).read_bytes()
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(100, 100, 0))
    with pytest.raises(backup.BackupError, match="空闲容量"):
        create(database, tmp_path, retain_count=1, apply_retention=True)
    assert Path(result["backup"]).read_bytes() == original


def test_interrupted_snapshot_preserves_only_valid_copy(database, tmp_path, monkeypatch):
    result = create(database, tmp_path)
    original = backup.read_database
    class Interrupted:
        def backup(self, *args, **kwargs):
            raise KeyboardInterrupt()
    @contextmanager
    def interrupt(path):
        with original(path) as (connection, metadata):
            # First preflight requires SQL; snapshot backup gets this method too.
            class Connection:
                execute = connection.execute
                backup = Interrupted().backup
            yield Connection(), metadata
    monkeypatch.setattr(backup, "read_database", interrupt)
    with pytest.raises(KeyboardInterrupt):
        create(database, tmp_path, retain_count=1, apply_retention=True)
    monkeypatch.setattr(backup, "read_database", original)
    assert backup.verify_backup(result["backup"])
    assert not list((tmp_path / "backups").glob(".partial-*"))


def test_concurrent_backup_directory_lock(database, tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    with backup._directory_lock(directory):
        with pytest.raises(backup.BackupError, match="另一备份"):
            create(database, tmp_path)
    assert create(database, tmp_path)["status"] == "verified"


@pytest.mark.parametrize("field,value", [("project", "old-project"), ("schema_version", "0"),
                                        ("dataset_id", "other-dataset"), ("data_mode", "real"),
                                        ("table_counts", {}), ("sha256", "0" * 64)])
def test_manifest_identity_tampering_rejected(database, tmp_path, field, value):
    result = create(database, tmp_path)
    sidecar = Path(result["manifest"])
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    manifest[field] = value
    sidecar.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.verify_backup(result["backup"])


def test_foreign_key_violation_does_not_publish(database, tmp_path):
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO campuses(school_key,campus_key,name,evidence_url,observed_at) VALUES ('missing','x','x','https://example.com','2026-10-13')")
    with pytest.raises(backup.BackupError, match="外键"):
        create(database, tmp_path)
    assert not list((tmp_path / "backups").glob("whv2-backup-*.sqlite3"))


def test_snapshot_while_writer_commits_related_rows(database, tmp_path):
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    started, stop = threading.Event(), threading.Event()
    failures = []
    def write():
        try:
            with sqlite3.connect(database) as connection:
                index = 0
                while not stop.is_set():
                    index += 1
                    key = f"concurrent-{index}"
                    connection.execute("INSERT INTO runs(id,trigger,started_at,status,scope_json) VALUES (?,'manual','2026-10-13','partial','{}')", (key,))
                    connection.execute("INSERT INTO processing_tasks(source_key,task_identity,task_kind,budget_json,run_id) VALUES ('scut_homepage',?,'detail','{}',?)", (key, key))
                    connection.commit()
                    started.set()
        except BaseException as exc:
            failures.append(exc)
    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert started.wait(5)
        result = create(database, tmp_path)
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and not failures
    manifest = backup.verify_backup(result["backup"])
    assert manifest["table_counts"]["runs"] > 0
    assert manifest["table_counts"]["runs"] == manifest["table_counts"]["processing_tasks"]


def test_restore_refuses_existing_target_wrong_dataset_and_backup_directory(database, tmp_path):
    result = create(database, tmp_path)
    isolated = tmp_path / "restore"
    isolated.mkdir()
    target = isolated / "copy.sqlite3"
    with pytest.raises(backup.BackupError, match="dataset_id"):
        backup.restore_backup(result["backup"], target, expected_dataset_id="incorrect", min_free_bytes=0)
    assert not target.exists()
    with pytest.raises(backup.BackupError, match="隔离目录"):
        backup.restore_backup(result["backup"], tmp_path / "backups" / "copy.sqlite3", min_free_bytes=0)
    backup.restore_backup(result["backup"], target, min_free_bytes=0)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(backup.BackupError, match="不能覆盖"):
        backup.restore_backup(result["backup"], target, min_free_bytes=0)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest


def test_restore_refuses_symlink_targets_or_parents(database, tmp_path):
    result = create(database, tmp_path)
    isolated = tmp_path / "restore"
    isolated.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(isolated, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 账户没有创建 symlink 权限")
    with pytest.raises(backup.BackupError, match="符号链接"):
        backup.restore_backup(result["backup"], link / "copy.sqlite3", min_free_bytes=0)


def test_retained_byte_cap_preflight(database, tmp_path):
    result = create(database, tmp_path)
    with pytest.raises(backup.BackupError, match="新备份超过"):
        create(database, tmp_path, byte_cap=backup.MANIFEST_RESERVE)
    assert backup.verify_backup(result["backup"])


def test_windows_reparse_ancestor_is_rejected_without_link_privilege(tmp_path, monkeypatch):
    from types import SimpleNamespace
    original = Path.lstat
    parent = tmp_path / "junction"
    parent.mkdir()
    def lstat(path):
        if path == parent:
            return SimpleNamespace(st_mode=0o40755, st_file_attributes=0x400)
        return original(path)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(backup.BackupError, match="重解析"):
        backup.safe_path(parent / "restore.sqlite3")


def test_restore_to_vacated_original_business_path_is_rejected(database, tmp_path):
    result = create(database, tmp_path)
    original = database
    moved = database.with_name("preserved-original.sqlite3")
    database.rename(moved)
    assert not original.exists()
    with pytest.raises(backup.BackupError, match="原业务路径"):
        backup.restore_backup(result["backup"], original, min_free_bytes=0)
    assert not original.exists() and moved.is_file()
    assert backup.verify_backup(result["backup"])["source_path_binding"] == backup.path_binding(original)


def test_old_manifest_still_refuses_matching_scheduler_binding(database, tmp_path):
    target = tmp_path / "old-host-bound-path" / "restored.sqlite3"
    target.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO metadata(key,value) VALUES ('operations_schedule',?)", (
            json.dumps({"enabled": True, "database_binding": backup.path_binding(target)}),))
    result = create(database, tmp_path)
    sidecar = Path(result["manifest"])
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    manifest.pop("source_path_binding")
    sidecar.write_text(json.dumps(manifest), encoding="utf-8")
    assert backup.verify_backup(result["backup"])
    with pytest.raises(backup.BackupError, match="宿主调度绑定"):
        backup.restore_backup(result["backup"], target, min_free_bytes=0)
    assert not target.exists()


@pytest.mark.parametrize("malformed", [[], None, "not a manifest", {"format_version": True}])
def test_malformed_manifest_has_explainable_rejection(database, tmp_path, malformed):
    result = create(database, tmp_path)
    Path(result["manifest"]).write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(backup.BackupError, match="校验失败"):
        backup.verify_backup(result["backup"])


def test_orphan_managed_manifest_is_protected_and_counts_towards_cap(database, tmp_path):
    result = create(database, tmp_path)
    Path(result["backup"]).unlink()
    sidecar = Path(result["manifest"])
    contents = sidecar.read_bytes()
    with pytest.raises(backup.BackupError, match="损坏或未验证"):
        create(database, tmp_path, retain_count=1, apply_retention=True)
    assert sidecar.read_bytes() == contents
