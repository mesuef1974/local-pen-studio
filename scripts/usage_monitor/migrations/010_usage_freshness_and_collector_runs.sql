ALTER TABLE usage_samples ADD COLUMN recorded_at TEXT;
CREATE INDEX IF NOT EXISTS idx_usage_samples_recorded_at
    ON usage_samples(recorded_at DESC);

CREATE TABLE usage_collector_runs (
    run_id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'interrupted')),
    collector_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    source_files_seen INTEGER NOT NULL DEFAULT 0 CHECK (source_files_seen >= 0),
    source_files_updated INTEGER NOT NULL DEFAULT 0 CHECK (source_files_updated >= 0),
    records_read INTEGER NOT NULL DEFAULT 0 CHECK (records_read >= 0),
    samples_inserted INTEGER NOT NULL DEFAULT 0 CHECK (samples_inserted >= 0),
    malformed_lines INTEGER NOT NULL DEFAULT 0 CHECK (malformed_lines >= 0),
    error_message TEXT
);
CREATE INDEX idx_usage_collector_runs_started
    ON usage_collector_runs(started_at DESC, run_id DESC);
