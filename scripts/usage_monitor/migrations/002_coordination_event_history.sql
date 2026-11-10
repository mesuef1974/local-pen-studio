CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

ALTER TABLE coordination_events ADD COLUMN stage_code TEXT;
ALTER TABLE coordination_events ADD COLUMN previous_status TEXT;
ALTER TABLE coordination_events ADD COLUMN next_status TEXT;
ALTER TABLE coordination_events ADD COLUMN owner_actor_id TEXT REFERENCES coordination_actors(actor_id);
ALTER TABLE coordination_events ADD COLUMN reason_code TEXT;
ALTER TABLE coordination_events ADD COLUMN reason_resolution TEXT
    CHECK (reason_resolution IS NULL OR reason_resolution IN ('confirmed','unresolved'));
ALTER TABLE coordination_events ADD COLUMN source_type TEXT;
ALTER TABLE coordination_events ADD COLUMN source_id TEXT;
ALTER TABLE coordination_events ADD COLUMN related_event_id INTEGER REFERENCES coordination_events(event_id);
ALTER TABLE coordination_events ADD COLUMN correlation_id TEXT;
ALTER TABLE coordination_events ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'operational'
    CHECK (sensitivity IN ('public','internal','confidential'));
ALTER TABLE coordination_events ADD COLUMN definition_version INTEGER NOT NULL DEFAULT 1
    CHECK (definition_version > 0);

CREATE TABLE IF NOT EXISTS coordination_assignments (
    assignment_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    assigned_actor_id TEXT NOT NULL REFERENCES coordination_actors(actor_id),
    assigned_by_actor_id TEXT REFERENCES coordination_actors(actor_id),
    reason_code TEXT,
    assigned_at TEXT NOT NULL,
    ended_at TEXT,
    source_event_id INTEGER REFERENCES coordination_events(event_id),
    CHECK (ended_at IS NULL OR ended_at >= assigned_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_coord_one_active_assignment
    ON coordination_assignments(card_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_coord_assignments_actor_time
    ON coordination_assignments(assigned_actor_id, assigned_at);

CREATE TABLE IF NOT EXISTS coordination_card_dependencies (
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    depends_on_card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    relation TEXT NOT NULL DEFAULT 'blocks' CHECK (relation IN ('blocks','related')),
    created_at TEXT NOT NULL,
    source_event_id INTEGER REFERENCES coordination_events(event_id),
    PRIMARY KEY (card_id, depends_on_card_id),
    CHECK (card_id <> depends_on_card_id)
);

CREATE TABLE IF NOT EXISTS coordination_delivery_attempts (
    attempt_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    submitted_by_actor_id TEXT REFERENCES coordination_actors(actor_id),
    submitted_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('submitted','accepted','returned','blocked','failed')),
    summary TEXT NOT NULL DEFAULT '',
    source_event_id INTEGER REFERENCES coordination_events(event_id),
    UNIQUE (card_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_coord_delivery_card_time
    ON coordination_delivery_attempts(card_id, submitted_at);

CREATE TABLE IF NOT EXISTS coordination_validation_results (
    validation_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    attempt_id INTEGER REFERENCES coordination_delivery_attempts(attempt_id),
    validator_actor_id TEXT REFERENCES coordination_actors(actor_id),
    outcome TEXT NOT NULL CHECK (outcome IN ('pass','conditional','fail')),
    criterion TEXT NOT NULL,
    evidence_ref TEXT,
    recorded_at TEXT NOT NULL,
    source_event_id INTEGER REFERENCES coordination_events(event_id)
);
CREATE INDEX IF NOT EXISTS idx_coord_validation_card_time
    ON coordination_validation_results(card_id, recorded_at);

CREATE TABLE IF NOT EXISTS coordination_issues (
    issue_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    event_id INTEGER NOT NULL REFERENCES coordination_events(event_id),
    stage_code TEXT NOT NULL,
    cause_code TEXT,
    cause_resolution TEXT NOT NULL CHECK (cause_resolution IN ('confirmed','unresolved')),
    impact_summary TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_issues_card_time
    ON coordination_issues(card_id, observed_at);

CREATE TABLE IF NOT EXISTS owner_decision_history (
    decision_history_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    axis TEXT NOT NULL,
    decision TEXT NOT NULL,
    previous_decision TEXT,
    decided_by_actor_id TEXT REFERENCES coordination_actors(actor_id),
    decided_at TEXT NOT NULL,
    source_event_id INTEGER REFERENCES coordination_events(event_id)
);
CREATE TABLE IF NOT EXISTS coordination_opinion_history (
    opinion_history_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    actor_id TEXT NOT NULL REFERENCES coordination_actors(actor_id),
    opinion TEXT NOT NULL,
    recommendation TEXT,
    recorded_at TEXT NOT NULL,
    source_event_id INTEGER REFERENCES coordination_events(event_id)
);

CREATE TABLE IF NOT EXISTS workflow_status_definitions (
    status_code TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    display_name TEXT NOT NULL,
    terminal INTEGER NOT NULL DEFAULT 0 CHECK (terminal IN (0,1)),
    effective_at TEXT NOT NULL,
    retired_at TEXT,
    PRIMARY KEY (status_code, version)
);
CREATE TABLE IF NOT EXISTS workflow_reason_definitions (
    reason_code TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    category TEXT NOT NULL,
    display_name TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    retired_at TEXT,
    PRIMARY KEY (reason_code, version)
);

CREATE INDEX IF NOT EXISTS idx_coord_events_status_time
    ON coordination_events(card_id, recorded_at, previous_status, next_status);
CREATE INDEX IF NOT EXISTS idx_coord_events_stage_reason
    ON coordination_events(stage_code, reason_code, recorded_at);
CREATE INDEX IF NOT EXISTS idx_coord_events_correlation
    ON coordination_events(correlation_id) WHERE correlation_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_coord_events_immutable_update
BEFORE UPDATE ON coordination_events
BEGIN SELECT RAISE(ABORT, 'coordination_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_coord_events_immutable_delete
BEFORE DELETE ON coordination_events
BEGIN SELECT RAISE(ABORT, 'coordination_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_owner_decision_history_immutable_update
BEFORE UPDATE ON owner_decision_history
BEGIN SELECT RAISE(ABORT, 'owner_decision_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_owner_decision_history_immutable_delete
BEFORE DELETE ON owner_decision_history
BEGIN SELECT RAISE(ABORT, 'owner_decision_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_opinion_history_immutable_update
BEFORE UPDATE ON coordination_opinion_history
BEGIN SELECT RAISE(ABORT, 'coordination_opinion_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_opinion_history_immutable_delete
BEFORE DELETE ON coordination_opinion_history
BEGIN SELECT RAISE(ABORT, 'coordination_opinion_history is append-only'); END;

INSERT OR IGNORE INTO workflow_status_definitions
(status_code,version,display_name,terminal,effective_at) VALUES
('draft',1,'مسودة',0,'2026-10-28T00:00:00Z'),
('accepted',1,'مستلمة',0,'2026-10-28T00:00:00Z'),
('in_progress',1,'قيد التنفيذ',0,'2026-10-28T00:00:00Z'),
('needs_clarification',1,'بانتظار توضيح',0,'2026-10-28T00:00:00Z'),
('reassignment_requested',1,'طلب إعادة توجيه',0,'2026-10-28T00:00:00Z'),
('awaiting_owner',1,'بانتظار قرار المالك',0,'2026-10-28T00:00:00Z'),
('delivered',1,'تم التسليم',0,'2026-10-28T00:00:00Z'),
('verifying',1,'قيد التحقق',0,'2026-10-28T00:00:00Z'),
('completed',1,'مكتملة',1,'2026-10-28T00:00:00Z'),
('blocked',1,'متعذرة',0,'2026-10-28T00:00:00Z'),
('failed',1,'فشلت',1,'2026-10-28T00:00:00Z'),
('archived',1,'مؤرشفة',1,'2026-10-28T00:00:00Z');

INSERT OR IGNORE INTO workflow_reason_definitions
(reason_code,version,category,display_name,effective_at) VALUES
('missing_context',1,'clarification','معلومات غير مكتملة','2026-10-28T00:00:00Z'),
('scope_mismatch',1,'routing','الاختصاص أو النطاق غير مطابق','2026-10-28T00:00:00Z'),
('blocked_dependency',1,'blocker','اعتماد سابق غير مكتمل','2026-10-28T00:00:00Z'),
('verification_failed',1,'quality','فشل التحقق','2026-10-28T00:00:00Z'),
('delivery_failed',1,'delivery','تعذر التسليم','2026-10-28T00:00:00Z'),
('session_unavailable',1,'capacity','الجلسة غير متاحة','2026-10-28T00:00:00Z'),
('owner_decision_pending',1,'owner_wait','بانتظار المالك','2026-10-28T00:00:00Z'),
('unknown',1,'unclassified','السبب غير محسوم','2026-10-28T00:00:00Z');
