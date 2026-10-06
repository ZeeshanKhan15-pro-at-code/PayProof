-- One private local SQLite database; immutable snapshots and explicit head pointers.
BEGIN IMMEDIATE;
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
INSERT INTO schema_migrations VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
CREATE TABLE trusted_contacts (
 contact_id TEXT NOT NULL, revision_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(contact_id, revision_id)
);
CREATE TABLE vendor_revisions (
 vendor_id TEXT NOT NULL, revision_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
 recorded_at TEXT NOT NULL, operator_id TEXT NOT NULL,
 PRIMARY KEY(vendor_id, revision_id)
);
CREATE TABLE vendor_heads (
 vendor_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL,
 FOREIGN KEY(vendor_id, revision_id) REFERENCES vendor_revisions(vendor_id, revision_id)
);
CREATE TABLE sources (source_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE extraction_attempts (attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE case_revisions (
 case_id TEXT NOT NULL, revision_id TEXT NOT NULL UNIQUE, version INTEGER NOT NULL CHECK(version > 0),
 vendor_id TEXT NOT NULL, vendor_revision_id TEXT, payload TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL, engine_fingerprint TEXT,
 PRIMARY KEY(case_id, revision_id), UNIQUE(case_id, version),
 FOREIGN KEY(vendor_id, vendor_revision_id) REFERENCES vendor_revisions(vendor_id, revision_id)
);
CREATE TABLE case_heads (
 case_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL,
 FOREIGN KEY(case_id, revision_id) REFERENCES case_revisions(case_id, revision_id)
);
CREATE TABLE workflow_events (
 event_id TEXT PRIMARY KEY, case_id TEXT, revision_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('VENDOR_RECORDED','CASE_CREATED','INPUT_REPLACED','SOURCE_REVIEWED','COMPARED','INDEPENDENT_CHECK')),
 operator_id TEXT NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL,
 FOREIGN KEY(case_id, revision_id) REFERENCES case_revisions(case_id, revision_id)
);
CREATE TABLE verification_attempts (
 event_id TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE,
 case_id TEXT NOT NULL, source_revision_id TEXT NOT NULL, resulting_revision_id TEXT NOT NULL,
 comparison_id TEXT NOT NULL, action_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
 FOREIGN KEY(event_id) REFERENCES workflow_events(event_id),
 FOREIGN KEY(case_id, source_revision_id) REFERENCES case_revisions(case_id, revision_id),
 FOREIGN KEY(case_id, resulting_revision_id) REFERENCES case_revisions(case_id, revision_id)
);
CREATE TABLE human_confirmations (
 comparison_id TEXT PRIMARY KEY, verification_id TEXT NOT NULL UNIQUE,
 event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
 FOREIGN KEY(event_id) REFERENCES verification_attempts(event_id)
);
CREATE TRIGGER immutable_contacts_update BEFORE UPDATE ON trusted_contacts BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_contacts_delete BEFORE DELETE ON trusted_contacts BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_vendors_update BEFORE UPDATE ON vendor_revisions BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_vendors_delete BEFORE DELETE ON vendor_revisions BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_sources_update BEFORE UPDATE ON sources BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_sources_delete BEFORE DELETE ON sources BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_extractions_update BEFORE UPDATE ON extraction_attempts BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_extractions_delete BEFORE DELETE ON extraction_attempts BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_cases_update BEFORE UPDATE ON case_revisions BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_cases_delete BEFORE DELETE ON case_revisions BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_events_update BEFORE UPDATE ON workflow_events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER immutable_events_delete BEFORE DELETE ON workflow_events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER immutable_attempts_update BEFORE UPDATE ON verification_attempts BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER immutable_attempts_delete BEFORE DELETE ON verification_attempts BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER immutable_confirmations_update BEFORE UPDATE ON human_confirmations BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER immutable_confirmations_delete BEFORE DELETE ON human_confirmations BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER forward_case_head BEFORE UPDATE ON case_heads WHEN
 (SELECT version FROM case_revisions WHERE revision_id=NEW.revision_id) <=
 (SELECT version FROM case_revisions WHERE revision_id=OLD.revision_id)
 BEGIN SELECT RAISE(ABORT,'case head cannot move backwards'); END;
PRAGMA user_version=1;
COMMIT;
