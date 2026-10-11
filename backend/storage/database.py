"""No implicit creation, repair or migration on any read path."""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.config import ROOT
from backend.version import PROJECT, SCHEMA_VERSION


class DatabaseUnavailable(RuntimeError):
    pass


REQUIRED_COLUMNS = {
    "metadata": "key value",
    "schools": "school_key name homepage_seed_url verification_state verified_at official_owner_evidence_url scope_note",
    "campuses": "id school_key campus_key name evidence_url observed_at",
    "sources": "source_key school_key campus_id name channel_key official_entry_url adapter scope_json verification_state status last_attempt_at last_success_at public_message",
    "opportunities": "id school_key campus_id source_key source_identity title kind original_kind date_basis source_url published_date event_date start_time end_time deadline event_venue work_locations_json work_locations_scope relevance event_status recruitment_status field_observations_json first_seen_at content_changed_at source_updated_at version roster_fragments_json job_fragments_json attachments_json",
    "source_materials": "id source_key opportunity_id source_url official_record_id material_hash fetched_at raw_reference acquisition_status parsing_status parser_version scope_json",
    "runs": "id trigger started_at finished_at status scope_json completeness result_json committed_at",
    "processing_tasks": "id source_key opportunity_id task_kind cursor_json budget_json attempts status run_id result_json committed_at",
    "manual_operations": "id actor operation_type opportunity_id preview_hash base_version input_json difference_json expires_at status committed_at reverts_operation_id",
    "changes": "id opportunity_id field_name before_json after_json change_kind material_id run_id manual_operation_id actor committed_at",
}


def _validate(connection: sqlite3.Connection) -> dict[str, str]:
    for table, columns in REQUIRED_COLUMNS.items():
        present = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not set(columns.split()).issubset(present):
            raise DatabaseUnavailable("新库结构不完整或版本不兼容，请检查配置并显式初始化正确的新库。")
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    if metadata.get("project") != PROJECT or metadata.get("schema_version") != SCHEMA_VERSION:
        raise DatabaseUnavailable("数据库项目或结构版本不匹配，请连接 Workhunter v2 独立新库。")
    if not metadata.get("dataset_id") or metadata.get("data_mode") not in {"empty", "real"}:
        raise DatabaseUnavailable("数据库的数据集标识缺失或无效。")
    if connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
        raise DatabaseUnavailable("数据库损坏或不可读，请使用经过核验的隔离备份恢复。")
    return metadata


@contextmanager
def read_database(db_path: Path):
    """One consistent snapshot, opened with SQLite's enforceable read-only mode."""
    path = Path(db_path).resolve()
    connection = None
    if not path.is_file():
        raise DatabaseUnavailable("独立新库不存在或路径不可读，请先显式初始化；读取不会自动建库。")
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        metadata = _validate(connection)
        yield connection, metadata
    except sqlite3.Error as exc:
        raise DatabaseUnavailable("数据库损坏、不可读或正在恢复，请稍后重试并检查独立新库。") from exc
    finally:
        if connection is not None:
            connection.close()


def initialize_database(db_path: Path, schools_path: Path | None = None) -> dict[str, str]:
    """Explicit, idempotent creation. Existing unknown databases are never repaired."""
    path = Path(db_path).resolve()
    if path.exists():
        with read_database(path) as (_, metadata):
            return metadata
    seeds = json.loads((schools_path or ROOT / "config" / "schools.json").read_text(encoding="utf-8"))
    schools = seeds["schools"]
    keys = {school["school_key"] for school in schools}
    if len(schools) != 10 or keys != {"scut", "gdut", "ncepu", "shiep", "neepu", "csust", "ctgu", "gzhu", "hnu", "csu"}:
        raise ValueError("学校种子必须保持已确认的固定十校。")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation prevents accidental replacement if another process races init.
    with path.open("xb"):
        pass
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
        connection.execute("PRAGMA foreign_keys=ON")
        schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        connection.executescript("BEGIN IMMEDIATE;\n" + schema)
        metadata = {
            "project": PROJECT, "schema_version": SCHEMA_VERSION,
            "dataset_id": "ds-" + str(uuid4()), "data_mode": "empty",
            "initialized_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }
        connection.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", metadata.items())
        for school in schools:
            connection.execute(
                "INSERT INTO schools(school_key,name,homepage_seed_url,verification_state,scope_note) VALUES (?,?,?,'pending',?)",
                (school["school_key"], school["name"], school["homepage_seed_url"], school.get("scope_note")),
            )
            connection.execute(
                "INSERT INTO sources(source_key,school_key,name,channel_key,official_entry_url,adapter,scope_json) VALUES (?,?,?,?,?,?,?)",
                (school["school_key"] + "_homepage", school["school_key"], "官方就业入口种子", "homepage", school["homepage_seed_url"], "unimplemented", json.dumps({"verified": False, "coverage": "unverified_seed"})),
            )
        connection.commit()
        return metadata
    except BaseException:
        if connection is not None:
            connection.close()
            connection = None
        # Only the file exclusively created by this invocation may be removed.
        path.unlink(missing_ok=True)
        raise
    finally:
        if connection is not None:
            connection.close()
