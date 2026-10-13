"""Verified SQLite snapshots and non-overwriting isolated restores.

Retention is a plan by default. ``--apply-retention`` only removes verified
pairs carrying this tool's manifest, after the replacement is verified.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import time
from uuid import uuid4

from backend.storage.database import DatabaseUnavailable, REQUIRED_COLUMNS, read_database
from backend.version import PROJECT, SCHEMA_VERSION


MANAGED_BY = "workhunter-v2-backup-v1"
NAME = re.compile(r"whv2-backup-\d{8}T\d{12}Z-[0-9a-f]{32}\.sqlite3\Z")
BUSINESS_TABLES = tuple(REQUIRED_COLUMNS)
MANIFEST_RESERVE = 16384


class BackupError(RuntimeError):
    pass


def safe_path(value) -> Path:
    """Check before resolve, including Windows directory junctions."""
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BackupError("路径包含符号链接或重解析点，已拒绝。")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def path_binding(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).casefold().encode()).hexdigest()


def _snapshot_identity(path: Path) -> dict:
    with read_database(path) as (connection, metadata):
        if connection.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok":
            raise BackupError("备份未通过完整性校验。")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("备份未通过外键校验。")
        return {"project": metadata["project"], "schema_version": metadata["schema_version"],
                "dataset_id": metadata["dataset_id"], "data_mode": metadata["data_mode"],
                "table_counts": {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                                 for table in BUSINESS_TABLES}}


def verify_backup(database_path, manifest_path=None) -> dict:
    path = safe_path(database_path)
    sidecar = safe_path(manifest_path or path.with_suffix(".manifest.json"))
    if not path.is_file() or not sidecar.is_file() or not NAME.fullmatch(path.name):
        raise BackupError("缺少有效的受管理备份及 manifest。")
    try:
        if sidecar.stat().st_size > MANIFEST_RESERVE:
            raise ValueError()
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError()
        if (manifest.get("managed_by") != MANAGED_BY or type(manifest.get("format_version")) is not int
                or manifest["format_version"] != 1
                or manifest.get("database_file") != path.name
                or manifest.get("backup_id") != path.stem
                or manifest.get("project") != PROJECT or manifest.get("schema_version") != SCHEMA_VERSION
                or (manifest.get("source_path_binding") is not None
                    and not re.fullmatch(r"[0-9a-f]{64}", str(manifest["source_path_binding"])))
                or type(manifest.get("size_bytes")) is not int or manifest["size_bytes"] != path.stat().st_size
                or not isinstance(manifest.get("sha256"), str) or len(manifest["sha256"]) != 64):
            raise ValueError()
        counts = manifest.get("table_counts")
        if not isinstance(counts, dict) or set(counts) != set(BUSINESS_TABLES) or any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError()
        initial_hash = sha256(path)
        if initial_hash != manifest["sha256"]:
            raise ValueError()
        identity = _snapshot_identity(path)
        if any(manifest.get(key) != value for key, value in identity.items()) or sha256(path) != initial_hash:
            raise ValueError()
        return manifest
    except (ValueError, TypeError, KeyError, OSError, DatabaseUnavailable, sqlite3.Error) as exc:
        raise BackupError("备份校验失败：SHA、身份、计数或数据库完整性不匹配。") from exc


@contextmanager
def _directory_lock(directory: Path):
    lock = safe_path(directory / ".whv2-backup.lock")
    try:
        with lock.open("xb") as stream:
            stream.write(b"0")
    except FileExistsError:
        if not lock.is_file():
            raise BackupError("备份目录锁无效。")
    stream = lock.open("r+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except OSError as exc:
        if not acquired:
            raise BackupError("另一备份正在使用该目录，请稍后重试。") from exc
        raise
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _inventory(directory: Path) -> list[dict]:
    result = []
    paths = set(directory.glob("whv2-backup-*.sqlite3"))
    paths.update(path.with_name(path.name.removesuffix(".manifest.json") + ".sqlite3")
                 for path in directory.glob("whv2-backup-*.manifest.json"))
    for path in sorted(paths):
        if not NAME.fullmatch(path.name):
            continue
        sidecar = path.with_suffix(".manifest.json")
        try:
            safe_path(path)
            safe_path(sidecar)
            manifest = verify_backup(path)
            valid = True
        except (BackupError, OSError):
            manifest, valid = {}, False
        # Invalid pairs are protected and count against the managed capacity.
        size = sum(item.lstat().st_size for item in (path, sidecar) if item.exists() or item.is_symlink())
        result.append({"path": path, "sidecar": sidecar, "bytes": size, "valid": valid,
                       "created_at": manifest.get("created_at", "")})
    return result


def _plan(entries: list[dict], new_bytes: int, retain_count: int, byte_cap: int) -> list[dict]:
    if new_bytes > byte_cap:
        raise BackupError("新备份超过受管理容量上限，未删除任何副本。")
    count, total, removable = len(entries) + 1, sum(item["bytes"] for item in entries) + new_bytes, []
    for entry in sorted((item for item in entries if item["valid"]), key=lambda item: (item["created_at"], item["path"].name)):
        if count <= retain_count and total <= byte_cap:
            break
        removable.append(entry)
        count -= 1
        total -= entry["bytes"]
    if count > retain_count or total > byte_cap:
        raise BackupError("受管理容量不足；损坏或未验证副本受保护，未删除任何文件。")
    return removable


def create_backup(database_path, backup_directory, *, retain_count=7, byte_cap=1024 * 1024 * 1024,
                  min_free_bytes=16 * 1024 * 1024, apply_retention=False, max_seconds=60) -> dict:
    if (type(retain_count) is not int or not 1 <= retain_count <= 1000 or type(byte_cap) is not int
            or byte_cap < MANIFEST_RESERVE or type(min_free_bytes) is not int or min_free_bytes < 0
            or not 0 < max_seconds <= 600):
        raise BackupError("备份容量、数量或时间预算无效。")
    source, directory = safe_path(database_path), safe_path(backup_directory)
    with read_database(source) as (connection, _):
        estimated = connection.execute("PRAGMA page_count").fetchone()[0] * connection.execute("PRAGMA page_size").fetchone()[0]
    directory.mkdir(parents=True, exist_ok=True)
    safe_path(directory)
    if source.parent == directory:
        raise BackupError("备份目录必须与业务数据库目录隔离。")
    with _directory_lock(directory):
        entries = _inventory(directory)
        plan = _plan(entries, estimated + MANIFEST_RESERVE, retain_count, byte_cap)
        if plan and not apply_retention:
            raise BackupError("达到受管理数量或容量上限；需显式启用已验证副本轮转，当前未删除文件。")
        if shutil.disk_usage(directory).free < estimated + MANIFEST_RESERVE + min_free_bytes:
            raise BackupError("磁盘空闲容量不足，已保留全部现有副本。")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = directory / f"whv2-backup-{stamp}-{uuid4().hex}.sqlite3"
        temporary = directory / (".partial-" + uuid4().hex + ".sqlite3")
        temporary_manifest = directory / (".partial-" + uuid4().hex + ".json")
        sidecar = target.with_suffix(".manifest.json")
        published = False
        committed = False
        destination = None
        try:
            with temporary.open("xb"):
                pass
            destination = sqlite3.connect(temporary)
            deadline = time.monotonic() + max_seconds
            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise BackupError("备份超出时间预算，现有副本保持不变。")
            # SQLite backup copies a transaction-consistent snapshot, including committed WAL pages.
            with read_database(source) as (connection, _):
                connection.backup(destination, pages=128, progress=progress, sleep=0.02)
            destination.close()
            destination = None
            identity = _snapshot_identity(temporary)
            manifest = {"format_version": 1, "managed_by": MANAGED_BY, "backup_id": target.stem,
                        "database_file": target.name, "created_at": datetime.now(timezone.utc).isoformat(),
                        "scope": "database_only", "raw_materials": "external_readonly_archive_required",
                        "source_path_binding": path_binding(source),
                        **identity, "size_bytes": temporary.stat().st_size, "sha256": sha256(temporary)}
            with temporary_manifest.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            if shutil.disk_usage(directory).free < min_free_bytes:
                raise BackupError("备份后剩余容量不足，未轮转旧副本。")
            plan = _plan(entries, temporary.stat().st_size + temporary_manifest.stat().st_size, retain_count, byte_cap)
            if plan and not apply_retention:
                raise BackupError("备份实际容量达到上限，现有副本保持不变。")
            # Hard links publish exclusive names without ever replacing an existing file.
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.link(temporary, target)
            published = True
            os.link(temporary_manifest, sidecar)
            verify_backup(target)
            committed = True
            removed = []
            for entry in plan:
                # Recheck both the replacement and the candidate immediately before deletion.
                verify_backup(target)
                verify_backup(entry["path"])
                entry["path"].unlink()
                entry["sidecar"].unlink()
                removed.append(entry["path"].name)
            return {"status": "verified", "backup": str(target), "manifest": str(sidecar),
                    "identity": identity, "sha256": manifest["sha256"], "removed_verified": removed,
                    "retained_count": len(_inventory(directory))}
        finally:
            if destination is not None:
                destination.close()
            temporary.unlink(missing_ok=True)
            temporary_manifest.unlink(missing_ok=True)
            if published and not committed:
                target.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)


def restore_backup(database_path, target_path, *, expected_dataset_id=None, min_free_bytes=16 * 1024 * 1024) -> dict:
    source, target = safe_path(database_path), safe_path(target_path)
    if target.exists() or target.is_symlink():
        raise BackupError("恢复只允许不存在的新隔离目标，不能覆盖或重复恢复。")
    if type(min_free_bytes) is not int or min_free_bytes < 0:
        raise BackupError("容量预算无效。")
    manifest = verify_backup(source)
    target_binding = path_binding(target)
    if manifest.get("source_path_binding") == target_binding:
        raise BackupError("恢复目标与原业务路径相同；必须使用新隔离路径。")
    # Old manifests can lack source binding. A stored scheduler binding still
    # cannot be reactivated by restoring to the original host-registered path.
    with read_database(source) as (_, metadata):
        try:
            schedule = json.loads(metadata.get("operations_schedule", "null"))
        except (TypeError, ValueError) as exc:
            raise BackupError("备份中的调度绑定不可读，不能安全恢复。") from exc
        if isinstance(schedule, dict) and schedule.get("database_binding") == target_binding:
            raise BackupError("恢复目标匹配已有宿主调度绑定；必须使用新隔离路径。")
    if expected_dataset_id is not None and manifest["dataset_id"] != expected_dataset_id:
        raise BackupError("备份 dataset_id 与预期不匹配。")
    if not target.parent.is_dir() or target.parent == source.parent:
        raise BackupError("恢复目标必须位于已存在的新隔离目录中。")
    if shutil.disk_usage(target.parent).free < manifest["size_bytes"] + min_free_bytes:
        raise BackupError("恢复目标空闲容量不足。")
    temporary = target.parent / (".restore-partial-" + uuid4().hex + ".sqlite3")
    try:
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        identity = _snapshot_identity(temporary)
        if sha256(temporary) != manifest["sha256"] or any(identity[key] != manifest[key] for key in identity):
            raise BackupError("恢复副本身份或 SHA 校验失败。")
        verify_backup(source)
        safe_path(target)
        os.link(temporary, target)
        return {"status": "verified", "target": str(target), "sha256": manifest["sha256"], "identity": identity}
    except FileExistsError as exc:
        raise BackupError("恢复目标被其他进程占用，未覆盖文件。") from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Workhunter v2 已验证备份与隔离恢复")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--db", type=Path, required=True)
    backup.add_argument("--directory", type=Path, required=True)
    backup.add_argument("--retain-count", type=int, default=7)
    backup.add_argument("--byte-cap", type=int, default=1024 * 1024 * 1024)
    backup.add_argument("--min-free-bytes", type=int, default=16 * 1024 * 1024)
    backup.add_argument("--apply-retention", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--expected-dataset-id")
    verify = commands.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        if options.command == "backup":
            result = create_backup(options.db, options.directory, retain_count=options.retain_count,
                                   byte_cap=options.byte_cap, min_free_bytes=options.min_free_bytes,
                                   apply_retention=options.apply_retention)
        elif options.command == "restore":
            result = restore_backup(options.backup, options.target, expected_dataset_id=options.expected_dataset_id)
        else:
            result = verify_backup(options.backup)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (BackupError, DatabaseUnavailable, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
