CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE schools (
  school_key TEXT PRIMARY KEY, name TEXT NOT NULL,
  homepage_seed_url TEXT NOT NULL, verification_state TEXT NOT NULL DEFAULT 'pending',
  verified_at TEXT, official_owner_evidence_url TEXT, scope_note TEXT
);
CREATE TABLE campuses (
  id INTEGER PRIMARY KEY, school_key TEXT NOT NULL REFERENCES schools(school_key),
  campus_key TEXT NOT NULL, name TEXT NOT NULL, evidence_url TEXT NOT NULL,
  observed_at TEXT NOT NULL, UNIQUE(school_key, campus_key)
);
CREATE TABLE sources (
  source_key TEXT PRIMARY KEY, school_key TEXT NOT NULL REFERENCES schools(school_key),
  campus_id INTEGER REFERENCES campuses(id), name TEXT NOT NULL,
  channel_key TEXT NOT NULL, official_entry_url TEXT NOT NULL, adapter TEXT NOT NULL,
  scope_json TEXT NOT NULL, verification_state TEXT NOT NULL DEFAULT 'pending',
  status TEXT NOT NULL DEFAULT 'not_checked', last_attempt_at TEXT,
  last_success_at TEXT, public_message TEXT NOT NULL DEFAULT '尚未检查'
);
CREATE TABLE opportunities (
  id INTEGER PRIMARY KEY, school_key TEXT NOT NULL REFERENCES schools(school_key),
  campus_id INTEGER REFERENCES campuses(id), source_key TEXT NOT NULL REFERENCES sources(source_key),
  source_identity TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('campus_talk','job_fair','online_recruitment','announcement')),
  original_kind TEXT,
  date_basis TEXT NOT NULL CHECK(date_basis IN ('event','publication')),
  source_url TEXT NOT NULL, published_date TEXT, event_date TEXT, start_time TEXT, end_time TEXT,
  deadline TEXT, event_venue TEXT, work_locations_json TEXT NOT NULL DEFAULT '[]',
  work_locations_scope TEXT NOT NULL DEFAULT 'this_announcement',
  relevance TEXT NOT NULL DEFAULT 'unknown' CHECK(relevance IN ('related','unknown','unrelated')),
  event_status TEXT NOT NULL DEFAULT 'unknown', recruitment_status TEXT NOT NULL DEFAULT 'unknown',
  field_observations_json TEXT NOT NULL DEFAULT '{}', first_seen_at TEXT NOT NULL,
  content_changed_at TEXT, source_updated_at TEXT, version INTEGER NOT NULL DEFAULT 1,
  roster_fragments_json TEXT NOT NULL DEFAULT '[]', job_fragments_json TEXT NOT NULL DEFAULT '[]',
  attachments_json TEXT NOT NULL DEFAULT '[]', UNIQUE(source_key, source_identity)
);
CREATE INDEX opportunities_school_date ON opportunities(school_key, published_date, id);
CREATE INDEX opportunities_event_date ON opportunities(event_date, id);
CREATE TABLE source_materials (
  id INTEGER PRIMARY KEY, source_key TEXT NOT NULL REFERENCES sources(source_key),
  opportunity_id INTEGER REFERENCES opportunities(id), source_url TEXT NOT NULL,
  official_record_id TEXT, material_hash TEXT, fetched_at TEXT, raw_reference TEXT,
  acquisition_status TEXT NOT NULL DEFAULT 'pending', parsing_status TEXT NOT NULL DEFAULT 'pending',
  parser_version TEXT, scope_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE runs (
  id TEXT PRIMARY KEY, trigger TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, status TEXT NOT NULL, scope_json TEXT NOT NULL,
  completeness TEXT NOT NULL DEFAULT 'unknown', result_json TEXT NOT NULL DEFAULT '{}',
  committed_at TEXT
);
CREATE TABLE processing_tasks (
  id INTEGER PRIMARY KEY, source_key TEXT NOT NULL REFERENCES sources(source_key),
  opportunity_id INTEGER REFERENCES opportunities(id), task_kind TEXT NOT NULL,
  cursor_json TEXT, budget_json TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', run_id TEXT REFERENCES runs(id),
  result_json TEXT, committed_at TEXT, UNIQUE(source_key, opportunity_id, task_kind)
);
CREATE TABLE manual_operations (
  id TEXT PRIMARY KEY, actor TEXT NOT NULL, operation_type TEXT NOT NULL,
  opportunity_id INTEGER REFERENCES opportunities(id), preview_hash TEXT NOT NULL,
  base_version INTEGER, input_json TEXT NOT NULL, difference_json TEXT NOT NULL,
  expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'preview',
  committed_at TEXT, reverts_operation_id TEXT REFERENCES manual_operations(id)
);
CREATE TABLE changes (
  id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  field_name TEXT NOT NULL, before_json TEXT, after_json TEXT,
  change_kind TEXT NOT NULL, material_id INTEGER REFERENCES source_materials(id),
  run_id TEXT REFERENCES runs(id), manual_operation_id TEXT REFERENCES manual_operations(id),
  actor TEXT, committed_at TEXT NOT NULL
);
