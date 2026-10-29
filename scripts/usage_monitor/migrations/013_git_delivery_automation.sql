CREATE TABLE IF NOT EXISTS coordination_git_integrations (
    integration_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES coordination_delivery_attempts(attempt_id),
    repository TEXT NOT NULL,
    base_branch TEXT NOT NULL DEFAULT 'main',
    head_branch TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    state_code TEXT NOT NULL CHECK (state_code IN (
        'pending','processing','awaiting_checks','awaiting_review',
        'merged_sync_pending','completed','returned','blocked'
    )),
    pull_request_number INTEGER,
    pull_request_url TEXT,
    base_sha TEXT,
    merge_sha TEXT,
    local_main_sha TEXT,
    remote_main_sha TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    locked_until TEXT,
    next_attempt_at TEXT NOT NULL,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_git_integrations_ready
    ON coordination_git_integrations(state_code,next_attempt_at,integration_id);
