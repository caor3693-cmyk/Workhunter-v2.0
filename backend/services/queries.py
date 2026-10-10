"""Read projections share a single database snapshot and never contact sources."""

from dataclasses import dataclass, asdict
from datetime import date, timedelta
import json
import sqlite3

from backend.storage.database import DatabaseUnavailable


@dataclass(frozen=True)
class Filters:
    school_key: str | None = None
    campus_id: int | None = None
    campus_unknown: bool = False
    kind: str | None = None
    keyword: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    view: str = "recent"
    scope: str = "electrical"
    offset: int = 0
    limit: int = 20
    dataset_id: str | None = None


def identity(metadata: dict[str, str]) -> dict:
    return {"dataset_id": metadata["dataset_id"], "data_mode": metadata["data_mode"]}


def source_projection(row: sqlite3.Row) -> dict:
    return {
        "source_key": row["source_key"], "school_key": row["school_key"],
        "school_name": row["school_name"], "name": row["name"],
        "official_entry_url": row["official_entry_url"],
        "verification_state": row["verification_state"], "status": row["status"],
        "last_attempt_at": row["last_attempt_at"], "last_success_at": row["last_success_at"],
        "message": row["public_message"],
    }


def sources(connection: sqlite3.Connection) -> list[dict]:
    return [source_projection(row) for row in connection.execute(
        "SELECT s.*, school.name AS school_name FROM sources s JOIN schools school USING(school_key) ORDER BY school.rowid,s.source_key"
    )]


def catalog(connection: sqlite3.Connection, metadata: dict[str, str]) -> dict:
    all_sources = sources(connection)
    schools = []
    for school in connection.execute("SELECT * FROM schools ORDER BY rowid"):
        school_sources = [source for source in all_sources if source["school_key"] == school["school_key"]]
        count = connection.execute("SELECT COUNT(*) FROM opportunities WHERE school_key=?", (school["school_key"],)).fetchone()[0]
        campuses = [dict(row) for row in connection.execute(
            "SELECT id,campus_key,name,evidence_url FROM campuses WHERE school_key=? ORDER BY id", (school["school_key"],),
        )]
        schools.append({
            "school_key": school["school_key"], "name": school["name"],
            "campuses": campuses, "verification_state": school["verification_state"],
            "availability": "pending", "availability_message": "待核验 · 尚未检查",
            "opportunity_count": count, "sources": school_sources,
        })
    return {**identity(metadata), "schools": schools}


def _decode(value: str, expected_type):
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise DatabaseUnavailable("数据库中的公告字段不可读，请检查数据完整性。") from exc
    if not isinstance(decoded, expected_type):
        raise DatabaseUnavailable("数据库中的公告字段结构无效，请检查数据完整性。")
    return decoded


def card(row: sqlite3.Row) -> dict:
    fields = (
        "id", "school_key", "school_name", "campus_id", "campus_name", "title", "kind",
        "original_kind", "date_basis", "source_url", "published_date", "event_date",
        "start_time", "end_time", "deadline", "event_venue", "work_locations_scope",
        "relevance", "event_status", "recruitment_status",
    )
    return {
        **{field: row[field] for field in fields},
        "work_locations": _decode(row["work_locations_json"], list),
        "field_observations": _decode(row["field_observations_json"], dict),
        "detail_url": f"/opportunities/{row['id']}",
    }


PROJECTION_SQL = """SELECT o.*, s.name AS school_name, c.name AS campus_name
FROM opportunities o JOIN schools s USING(school_key)
LEFT JOIN campuses c ON o.campus_id=c.id"""


def opportunities(connection: sqlite3.Connection, metadata: dict[str, str], filters: Filters, today: date, recent_days: int) -> dict:
    start = today - timedelta(days=recent_days - 1)
    end = today + timedelta(days=recent_days)
    clauses, values = [], []
    for field in ("school_key", "campus_id", "kind"):
        value = getattr(filters, field)
        if value is not None:
            clauses.append(f"o.{field}=?")
            values.append(value)
    if filters.campus_unknown:
        clauses.append("o.campus_id IS NULL")
    if filters.scope == "electrical":
        clauses.append("o.relevance IN ('related','unknown')")
    if filters.keyword:
        clauses.append("o.title LIKE ? ESCAPE '\\'")
        literal = filters.keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.append("%" + literal + "%")
    business_date = "CASE WHEN o.date_basis='event' THEN o.event_date ELSE o.published_date END"
    if filters.view == "recent":
        clauses.append("(o.published_date BETWEEN ? AND ? OR o.event_date BETWEEN ? AND ?)")
        values.extend([start.isoformat(), today.isoformat(), today.isoformat(), end.isoformat()])
    elif filters.view == "upcoming":
        clauses.append("o.date_basis='event' AND o.event_date>=? AND o.event_status!='cancelled'")
        values.append(today.isoformat())
    elif filters.view == "history":
        clauses.append("((o.date_basis='event' AND o.event_date<?) OR (o.date_basis='publication' AND o.published_date<?))")
        values.extend([today.isoformat(), start.isoformat()])
    else:
        clauses.append(f"({business_date}) IS NULL")
    for field, operator in (("date_from", ">="), ("date_to", "<=")):
        value = getattr(filters, field)
        if value:
            clauses.append(f"({business_date}){operator}?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = connection.execute("SELECT COUNT(*) FROM opportunities o" + where, values).fetchone()[0]
    order = "o.event_date ASC, COALESCE(o.start_time,'') ASC, o.id ASC" if filters.view == "upcoming" else "COALESCE(o.published_date,substr(o.first_seen_at,1,10)) DESC,o.id DESC"
    items = [card(row) for row in connection.execute(
        PROJECTION_SQL + where + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*values, filters.limit, filters.offset],
    )]
    applied = asdict(filters)
    for key in ("offset", "limit", "dataset_id"):
        applied.pop(key)
    applied["recent_window"] = {
        "days": recent_days, "published_from": start.isoformat(), "published_to": today.isoformat(),
        "events_from": today.isoformat(), "events_to": end.isoformat(),
    }
    empty_reason = None
    if total == 0:
        if connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0:
            empty_reason = "empty_database"
        elif filters.school_key and connection.execute("SELECT COUNT(*) FROM opportunities WHERE school_key=?", (filters.school_key,)).fetchone()[0] == 0:
            empty_reason = "school_not_collected"
        elif filters.view == "undated":
            empty_reason = "no_undated_matches"
        else:
            empty_reason = "no_matches"
    return {
        **identity(metadata), "items": items, "total": total, "offset": filters.offset,
        "limit": filters.limit, "has_more": filters.offset + len(items) < total,
        "applied_filters": applied, "empty_reason": empty_reason,
    }


def detail(connection: sqlite3.Connection, opportunity_id: int) -> dict | None:
    row = connection.execute(PROJECTION_SQL + " WHERE o.id=?", (opportunity_id,)).fetchone()
    if row is None:
        return None
    return {
        **card(row), "first_seen_at": row["first_seen_at"],
        "content_changed_at": row["content_changed_at"], "source_updated_at": row["source_updated_at"],
        "version": row["version"], "roster_fragments": _decode(row["roster_fragments_json"], list),
        "job_fragments": _decode(row["job_fragments_json"], list),
        "attachments": _decode(row["attachments_json"], list),
        "official_sources": [{"source_key": row["source_key"], "url": row["source_url"]}],
    }
