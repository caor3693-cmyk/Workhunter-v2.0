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
  reference_key TEXT NOT NULL,
  opportunity_id INTEGER REFERENCES opportunities(id), source_url TEXT NOT NULL,
  official_record_id TEXT, material_hash TEXT, fetched_at TEXT, raw_reference TEXT,
  acquisition_status TEXT NOT NULL DEFAULT 'pending', parsing_status TEXT NOT NULL DEFAULT 'pending',
  parser_version TEXT, scope_json TEXT NOT NULL DEFAULT '{}', UNIQUE(source_key,reference_key)
);
CREATE TABLE runs (
  id TEXT PRIMARY KEY, trigger TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, status TEXT NOT NULL, scope_json TEXT NOT NULL,
  completeness TEXT NOT NULL DEFAULT 'unknown', result_json TEXT NOT NULL DEFAULT '{}',
  committed_at TEXT
);
CREATE TABLE processing_tasks (
  id INTEGER PRIMARY KEY, source_key TEXT NOT NULL REFERENCES sources(source_key),
  task_identity TEXT NOT NULL,
  opportunity_id INTEGER REFERENCES opportunities(id), task_kind TEXT NOT NULL,
  cursor_json TEXT, budget_json TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', run_id TEXT REFERENCES runs(id),
  result_json TEXT, committed_at TEXT, last_attempt_at TEXT, next_eligible_at TEXT,
  queued_at TEXT, UNIQUE(source_key,task_identity,task_kind)
);
CREATE TABLE manual_operations (
  id TEXT PRIMARY KEY, actor TEXT NOT NULL, operation_type TEXT NOT NULL,
  opportunity_id INTEGER REFERENCES opportunities(id), preview_hash TEXT NOT NULL,
  base_version INTEGER, input_json TEXT NOT NULL, difference_json TEXT NOT NULL,
  expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'preview',
  committed_at TEXT, reverts_operation_id TEXT REFERENCES manual_operations(id),
  session_id TEXT, input_hash TEXT, idempotency_key TEXT, receipt_json TEXT,
  expected_version INTEGER, target_source_key TEXT, target_identity TEXT
);
CREATE TABLE changes (
  id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  field_name TEXT NOT NULL, before_json TEXT, after_json TEXT,
  change_kind TEXT NOT NULL, material_id INTEGER REFERENCES source_materials(id),
  run_id TEXT REFERENCES runs(id), manual_operation_id TEXT REFERENCES manual_operations(id),
  actor TEXT, committed_at TEXT NOT NULL, reason TEXT, write_context_key TEXT
);

-- Schema 3 additions (installed explicitly on identified schema 1/2 databases).
CREATE TABLE opportunity_materials (
  id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  material_id INTEGER NOT NULL REFERENCES source_materials(id),
  school_key TEXT NOT NULL REFERENCES schools(school_key), source_key TEXT NOT NULL REFERENCES sources(source_key),
  source_identity TEXT NOT NULL, relation_kind TEXT NOT NULL CHECK(relation_kind IN ('list','body','attachment_link')),
  locator TEXT NOT NULL, scope_json TEXT NOT NULL, basis_json TEXT NOT NULL,
  link_chain_json TEXT NOT NULL DEFAULT '{}', verified_at TEXT NOT NULL,
  UNIQUE(opportunity_id,material_id,locator)
);
CREATE TABLE write_receipts (
  context_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, actor TEXT NOT NULL,
  run_id TEXT REFERENCES runs(id), operation_id TEXT REFERENCES manual_operations(id),
  reason TEXT NOT NULL, change_kind TEXT NOT NULL, receipt_json TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  CHECK((run_id IS NULL) <> (operation_id IS NULL))
);
CREATE TABLE field_decisions (
  opportunity_id INTEGER NOT NULL REFERENCES opportunities(id), field_name TEXT NOT NULL,
  operation_id TEXT NOT NULL REFERENCES manual_operations(id), value_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL, base_version INTEGER NOT NULL, committed_at TEXT NOT NULL,
  PRIMARY KEY(opportunity_id,field_name)
);
CREATE TABLE official_observations (
  id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  field_name TEXT NOT NULL, material_id INTEGER NOT NULL REFERENCES source_materials(id),
  association_id INTEGER NOT NULL REFERENCES opportunity_materials(id),
  value_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL, parser_version TEXT NOT NULL,
  observed_at TEXT NOT NULL, committed_at TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id),
  actor TEXT NOT NULL, write_context_key TEXT NOT NULL,
  UNIQUE(opportunity_id,field_name,material_id,parser_version,value_hash)
);
CREATE TABLE maintenance_sessions (
  session_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, actor TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE maintenance_login_failures (
  identifier_hash TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
  window_started_at TEXT NOT NULL, last_attempt_at TEXT NOT NULL, blocked_until TEXT
);
CREATE TABLE quarantined_evidence (
  id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
  field_name TEXT NOT NULL, input_hash TEXT NOT NULL, original_json TEXT NOT NULL,
  reason TEXT NOT NULL, recorded_at TEXT NOT NULL,
  UNIQUE(opportunity_id,field_name,input_hash)
);

-- Ownership constraints (also applied by explicit schema migration).
CREATE TRIGGER opportunity_materials_insert BEFORE INSERT ON opportunity_materials
WHEN NOT EXISTS (SELECT 1 FROM opportunities o JOIN source_materials m ON m.id=NEW.material_id
 WHERE o.id=NEW.opportunity_id AND o.source_key=m.source_key AND o.source_identity=NEW.source_identity
 AND NEW.school_key=o.school_key AND NEW.source_key=o.source_key
 AND m.acquisition_status='success' AND (m.official_record_id IS NULL OR m.official_record_id=o.source_identity))
BEGIN SELECT RAISE(ABORT, 'material announcement applicability mismatch'); END;
CREATE TRIGGER opportunity_materials_update BEFORE UPDATE ON opportunity_materials
WHEN NOT EXISTS (SELECT 1 FROM opportunities o JOIN source_materials m ON m.id=NEW.material_id
 WHERE o.id=NEW.opportunity_id AND o.source_key=m.source_key AND o.source_identity=NEW.source_identity
 AND NEW.school_key=o.school_key AND NEW.source_key=o.source_key
 AND m.acquisition_status='success' AND (m.official_record_id IS NULL OR m.official_record_id=o.source_identity))
BEGIN SELECT RAISE(ABORT, 'material announcement applicability mismatch'); END;
CREATE TRIGGER materials_applicability_update BEFORE UPDATE OF source_key,official_record_id,opportunity_id ON source_materials
WHEN EXISTS (SELECT 1 FROM opportunity_materials a JOIN opportunities o ON o.id=a.opportunity_id
 WHERE a.material_id=OLD.id AND (o.source_key<>NEW.source_key OR (NEW.official_record_id IS NOT NULL AND NEW.official_record_id<>o.source_identity)
 OR (NEW.opportunity_id IS NOT NULL AND NEW.opportunity_id<>o.id)))
BEGIN SELECT RAISE(ABORT, 'material owner would invalidate verified applicability'); END;
CREATE TRIGGER changes_context_insert BEFORE INSERT ON changes
WHEN NEW.write_context_key IS NOT NULL AND ((NEW.run_id IS NULL)=(NEW.manual_operation_id IS NULL) OR NEW.actor IS NULL OR NEW.reason IS NULL)
BEGIN SELECT RAISE(ABORT, 'fact change requires one write context'); END;
CREATE TRIGGER official_observations_insert BEFORE INSERT ON official_observations
WHEN NOT EXISTS (SELECT 1 FROM opportunity_materials a WHERE a.id=NEW.association_id
 AND a.opportunity_id=NEW.opportunity_id AND a.material_id=NEW.material_id)
BEGIN SELECT RAISE(ABORT, 'official observation requires verified applicability'); END;
CREATE TRIGGER campuses_parent_ownership BEFORE UPDATE OF school_key ON campuses
WHEN EXISTS (SELECT 1 FROM opportunities WHERE campus_id=OLD.id AND school_key<>NEW.school_key)
OR EXISTS (SELECT 1 FROM sources WHERE campus_id=OLD.id AND school_key<>NEW.school_key)
BEGIN SELECT RAISE(ABORT, 'campus owner would invalidate existing references'); END;
CREATE TRIGGER sources_parent_ownership BEFORE UPDATE OF school_key ON sources
WHEN EXISTS (SELECT 1 FROM opportunities WHERE source_key=OLD.source_key AND school_key<>NEW.school_key)
BEGIN SELECT RAISE(ABORT, 'source owner would invalidate existing opportunities'); END;
CREATE TRIGGER opportunities_material_ownership BEFORE UPDATE OF source_key ON opportunities
WHEN EXISTS (SELECT 1 FROM source_materials WHERE opportunity_id=OLD.id AND source_key<>NEW.source_key)
OR EXISTS (SELECT 1 FROM processing_tasks WHERE opportunity_id=OLD.id AND source_key<>NEW.source_key)
OR EXISTS (SELECT 1 FROM changes c JOIN source_materials m ON m.id=c.material_id WHERE c.opportunity_id=OLD.id AND m.source_key<>NEW.source_key)
BEGIN SELECT RAISE(ABORT, 'opportunity source would invalidate existing evidence'); END;
CREATE TRIGGER materials_change_ownership BEFORE UPDATE OF source_key ON source_materials
WHEN EXISTS (SELECT 1 FROM changes c JOIN opportunities o ON o.id=c.opportunity_id WHERE c.material_id=OLD.id AND o.source_key<>NEW.source_key)
BEGIN SELECT RAISE(ABORT, 'material source would invalidate existing changes'); END;
CREATE TRIGGER sources_ownership_insert BEFORE INSERT ON sources
WHEN NEW.campus_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM campuses c WHERE c.id=NEW.campus_id AND c.school_key=NEW.school_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER sources_ownership_update BEFORE UPDATE ON sources
WHEN NEW.campus_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM campuses c WHERE c.id=NEW.campus_id AND c.school_key=NEW.school_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER opportunities_ownership_insert BEFORE INSERT ON opportunities
WHEN NOT EXISTS (SELECT 1 FROM sources s WHERE s.source_key=NEW.source_key AND s.school_key=NEW.school_key) OR (NEW.campus_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM campuses c WHERE c.id=NEW.campus_id AND c.school_key=NEW.school_key))
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER opportunities_ownership_update BEFORE UPDATE ON opportunities
WHEN NOT EXISTS (SELECT 1 FROM sources s WHERE s.source_key=NEW.source_key AND s.school_key=NEW.school_key) OR (NEW.campus_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM campuses c WHERE c.id=NEW.campus_id AND c.school_key=NEW.school_key))
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER source_materials_ownership_insert BEFORE INSERT ON source_materials
WHEN NEW.opportunity_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM opportunities o WHERE o.id=NEW.opportunity_id AND o.source_key=NEW.source_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER source_materials_ownership_update BEFORE UPDATE ON source_materials
WHEN NEW.opportunity_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM opportunities o WHERE o.id=NEW.opportunity_id AND o.source_key=NEW.source_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER processing_tasks_ownership_insert BEFORE INSERT ON processing_tasks
WHEN NEW.opportunity_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM opportunities o WHERE o.id=NEW.opportunity_id AND o.source_key=NEW.source_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER processing_tasks_ownership_update BEFORE UPDATE ON processing_tasks
WHEN NEW.opportunity_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM opportunities o WHERE o.id=NEW.opportunity_id AND o.source_key=NEW.source_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER changes_ownership_insert BEFORE INSERT ON changes
WHEN NEW.material_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM source_materials m JOIN opportunities o ON o.id=NEW.opportunity_id WHERE m.id=NEW.material_id AND m.source_key=o.source_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
CREATE TRIGGER changes_ownership_update BEFORE UPDATE ON changes
WHEN NEW.material_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM source_materials m JOIN opportunities o ON o.id=NEW.opportunity_id WHERE m.id=NEW.material_id AND m.source_key=o.source_key)
BEGIN SELECT RAISE(ABORT, 'school/source/campus/material ownership mismatch'); END;
