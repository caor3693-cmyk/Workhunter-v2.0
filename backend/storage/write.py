"""The shared, bounded write boundary; collection never runs inside it."""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import time

from backend.storage.database import DatabaseUnavailable, _validate


class WriterBusy(RuntimeError):
    """Another process owns the short database write boundary."""


class RefreshBusy(WriterBusy):
    """A refresh is already running for this database."""


@contextmanager
def _file_lock(path: Path, timeout_seconds: float, busy_error):
    # Keep the inode: deleting a lock file while waiters hold it breaks exclusion.
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError) as exc:
                if time.monotonic() >= deadline:
                    raise busy_error("该独立新库已有写入或刷新任务，请稍后重试。") from exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _existing_path(database_path) -> Path:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise DatabaseUnavailable("独立新库不存在，请先显式初始化；写入不会自动建库。")
    return path


@contextmanager
def refresh_lock(database_path):
    """Nonblocking whole-run exclusion, separate from short writer transactions."""
    path = _existing_path(database_path)
    with _file_lock(path.with_name(path.name + ".refresh.lock"), 0, RefreshBusy):
        yield


@contextmanager
def writer_transaction(database_path, *, timeout_seconds=10):
    """Every service shares the cross-process lock and commits one short unit."""
    if not 0 <= timeout_seconds <= 60:
        raise ValueError("写锁等待时间必须在 0 到 60 秒之间。")
    path = _existing_path(database_path)
    with _file_lock(path.with_name(path.name + ".write.lock"), timeout_seconds, WriterBusy):
        connection = None
        try:
            connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=timeout_seconds)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            metadata = _validate(connection)
            yield connection, metadata
            connection.commit()
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
