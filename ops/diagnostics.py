"""Private diagnostics project fixed operational fields; never raw log JSON."""

from datetime import datetime
import re

from backend.services import queries


RUN_STATUSES = {"running", "complete", "partial", "failed", "interrupted", "skipped", "busy"}
RUN_TRIGGERS = {"manual", "scheduled", "fixture", "resume", "natural", "scheduler"}
COMPLETENESS = {"unknown", "partial", "complete_for_selected_channels"}
TASK_STATUSES = {"pending", "queued", "running", "failed", "restricted", "partial", "committed", "complete", "resolved", "superseded"}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def run_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"(?:run-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value) else None


def runs_projection(connection, *, limit=20, offset=0):
    if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 100000:
        raise ValueError("诊断分页范围无效。")
    rows = connection.execute(
        "SELECT id,trigger,started_at,finished_at,status,completeness,committed_at FROM runs ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    items = [{"run_id": run_id(row["id"]),
              "trigger": row["trigger"] if row["trigger"] in RUN_TRIGGERS else "unknown",
              "status": row["status"] if row["status"] in RUN_STATUSES else "unknown",
              "completeness": row["completeness"] if row["completeness"] in COMPLETENESS else "unknown",
              **{key: timestamp(row[key]) for key in ("started_at", "finished_at", "committed_at")}} for row in rows]
    total = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    return {"items": items, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(items) < total}


def diagnostics_projection(connection, metadata, *, limit=20, offset=0):
    statuses = {key: 0 for key in sorted(TASK_STATUSES | {"unknown"})}
    # Case normalizes every non-allowlisted value before grouping; no arbitrary value leaves SQL.
    placeholders = ",".join("?" for _ in TASK_STATUSES)
    for row in connection.execute(
        f"SELECT CASE WHEN status IN ({placeholders}) THEN status ELSE 'unknown' END AS category,COUNT(*) AS count FROM processing_tasks GROUP BY category",
        tuple(TASK_STATUSES),
    ):
        statuses[row["category"]] = row["count"]
    return {**queries.identity(metadata), "runs": runs_projection(connection, limit=limit, offset=offset),
            "processing_task_counts": statuses, "redaction": "fixed_fields_only"}


def refresh_projection(connection, metadata):
    from backend.services.scheduling import schedule_projection
    schedule = schedule_projection(connection, metadata)
    status = schedule.get("status")
    allowed = {"disabled", "not_ready", "scheduled", "running", "overdue", "unknown"}
    last = schedule.get("last_execution")
    safe_last = None
    if isinstance(last, dict):
        execution_status = last.get("status")
        safe_last = {"status": execution_status if execution_status in RUN_STATUSES | {"finished"} else "unknown",
                     "trigger": last.get("trigger") if last.get("trigger") in RUN_TRIGGERS else "unknown",
                     "business_status": last.get("business_status") if last.get("business_status") in RUN_STATUSES else "unknown",
                     "run_ids": [value for value in (run_id(item) for item in last.get("run_ids", [])[:10]) if value],
                     "process_exit_code": last.get("process_exit_code") if type(last.get("process_exit_code")) is int else None,
                     "host_task_exit_code": last.get("host_task_exit_code") if type(last.get("host_task_exit_code")) is int else None,
                     **{key: timestamp(last.get(key)) for key in ("triggered_at", "slot_at", "finished_at")}}
    return {**queries.identity(metadata), "enabled": schedule.get("enabled") is True,
            "status": status if status in allowed else "unknown",
            "next_run_at": timestamp(schedule.get("next_run_at")),
            "overdue_since": timestamp(schedule.get("overdue_since")),
            "interval_hours": schedule.get("interval_hours") if type(schedule.get("interval_hours")) is int else None,
            "last_execution": safe_last, "latest_runs": runs_projection(connection, limit=5),
            "natural_run_count": schedule.get("natural_run_count") if type(schedule.get("natural_run_count")) is int else None,
            "continuous_days": schedule.get("continuous_days") if type(schedule.get("continuous_days")) in {int, float} else None}
