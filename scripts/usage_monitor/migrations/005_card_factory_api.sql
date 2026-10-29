ALTER TABLE coordination_cards ADD COLUMN parent_card_id TEXT
    REFERENCES coordination_cards(card_id);
ALTER TABLE coordination_cards ADD COLUMN card_type_code TEXT NOT NULL DEFAULT 'general';
ALTER TABLE coordination_cards ADD COLUMN priority_code TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE coordination_cards ADD COLUMN started_at TEXT;
ALTER TABLE coordination_cards ADD COLUMN closed_at TEXT;
ALTER TABLE coordination_cards ADD COLUMN due_at TEXT;

ALTER TABLE coordination_delivery_attempts ADD COLUMN branch_name TEXT;
ALTER TABLE coordination_delivery_attempts ADD COLUMN remote_name TEXT;
ALTER TABLE coordination_delivery_attempts ADD COLUMN commit_sha TEXT;
ALTER TABLE coordination_delivery_attempts ADD COLUMN remote_commit_sha TEXT;
ALTER TABLE coordination_delivery_attempts ADD COLUMN verified_at TEXT;
ALTER TABLE coordination_issues ADD COLUMN resolved_at TEXT;
ALTER TABLE coordination_issues ADD COLUMN resolved_by_actor_id TEXT
    REFERENCES coordination_actors(actor_id);

CREATE TABLE IF NOT EXISTS coordination_command_receipts (
    idempotency_key TEXT PRIMARY KEY,
    root_card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coordination_command_cards (
    idempotency_key TEXT NOT NULL REFERENCES coordination_command_receipts(idempotency_key),
    card_id TEXT NOT NULL UNIQUE REFERENCES coordination_cards(card_id),
    role_code TEXT NOT NULL CHECK (role_code IN ('root','session')),
    PRIMARY KEY (idempotency_key, card_id)
);

CREATE TABLE IF NOT EXISTS coordination_card_criteria (
    criterion_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    criterion_code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    check_method TEXT NOT NULL DEFAULT 'manual_evidence',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (card_id, criterion_code)
);
CREATE INDEX IF NOT EXISTS idx_coord_criteria_card_order
    ON coordination_card_criteria(card_id, sort_order, criterion_id);

CREATE TABLE IF NOT EXISTS coordination_outbox (
    outbox_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    event_id INTEGER NOT NULL REFERENCES coordination_events(event_id),
    target_actor_id TEXT NOT NULL REFERENCES coordination_actors(actor_id),
    command_code TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    state_code TEXT NOT NULL DEFAULT 'pending'
        CHECK (state_code IN ('pending','processing','sent','retry','dead_letter')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    available_at TEXT NOT NULL,
    locked_until TEXT,
    sent_at TEXT,
    remote_message_id TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_outbox_ready
    ON coordination_outbox(state_code, available_at, outbox_id);

CREATE TABLE IF NOT EXISTS workflow_transition_rules (
    from_status_code TEXT NOT NULL,
    to_status_code TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    PRIMARY KEY (from_status_code, to_status_code, version),
    FOREIGN KEY (from_status_code, version)
        REFERENCES workflow_status_definitions(status_code, version),
    FOREIGN KEY (to_status_code, version)
        REFERENCES workflow_status_definitions(status_code, version)
);

CREATE TABLE IF NOT EXISTS coordination_quality_runs (
    quality_run_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    attempt_id INTEGER REFERENCES coordination_delivery_attempts(attempt_id),
    commit_sha TEXT,
    profile_code TEXT NOT NULL,
    runner_name TEXT NOT NULL,
    runner_version TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pass','conditional','fail')),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_coord_quality_card_time
    ON coordination_quality_runs(card_id, finished_at DESC);
CREATE TABLE IF NOT EXISTS coordination_quality_checks (
    check_id INTEGER PRIMARY KEY,
    quality_run_id INTEGER NOT NULL REFERENCES coordination_quality_runs(quality_run_id),
    check_code TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pass','conditional','fail','skipped')),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    evidence_ref TEXT,
    message_code TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS coordination_delivery_paths (
    delivery_path_id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES coordination_delivery_attempts(attempt_id),
    path TEXT NOT NULL,
    scope_result TEXT NOT NULL DEFAULT 'pending'
        CHECK (scope_result IN ('pending','allowed','rejected')),
    UNIQUE (attempt_id, path)
);

INSERT OR IGNORE INTO workflow_status_definitions
(status_code,version,display_name,terminal,effective_at) VALUES
('queued',1,'في الطابور',0,'2026-10-29T00:00:00Z'),
('assigned',1,'مسندة',0,'2026-10-29T00:00:00Z'),
('returned',1,'معادة للتنفيذ',0,'2026-10-29T00:00:00Z');

UPDATE workflow_status_definitions
SET retired_at='2026-10-29T00:00:00Z'
WHERE status_code IN ('awaiting_owner','accepted_by_owner') AND retired_at IS NULL;

INSERT OR IGNORE INTO workflow_transition_rules(from_status_code,to_status_code,version) VALUES
('draft','queued',1),('draft','assigned',1),('draft','in_progress',1),('draft','archived',1),
('queued','assigned',1),('queued','in_progress',1),('queued','blocked',1),('queued','archived',1),
('assigned','in_progress',1),('assigned','blocked',1),('assigned','queued',1),('assigned','archived',1),
('accepted','in_progress',1),('accepted','blocked',1),('accepted','archived',1),
('in_progress','delivered',1),('in_progress','blocked',1),('in_progress','returned',1),
('in_progress','failed',1),('in_progress','archived',1),
('blocked','assigned',1),('blocked','in_progress',1),('blocked','returned',1),('blocked','delivered',1),
('blocked','failed',1),('blocked','archived',1),
('delivered','verifying',1),('delivered','returned',1),('delivered','blocked',1),
('verifying','completed',1),('verifying','returned',1),('verifying','blocked',1),
('returned','assigned',1),('returned','in_progress',1),('returned','blocked',1),('returned','archived',1),
('queued','completed',1),('assigned','completed',1);

CREATE INDEX IF NOT EXISTS idx_coord_cards_parent_status
    ON coordination_cards(parent_card_id, current_status_code, updated_at);

CREATE TRIGGER IF NOT EXISTS trg_coord_card_transition_allowed
BEFORE UPDATE OF current_status_code ON coordination_cards
WHEN NEW.current_status_code <> OLD.current_status_code
 AND NOT EXISTS (
    SELECT 1 FROM workflow_transition_rules r
    WHERE r.from_status_code=OLD.current_status_code
      AND r.to_status_code=NEW.current_status_code
      AND r.enabled=1
      AND r.version=NEW.current_status_version
 )
BEGIN SELECT RAISE(ABORT, 'workflow transition is not allowed'); END;
