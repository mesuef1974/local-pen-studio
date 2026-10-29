CREATE TABLE IF NOT EXISTS workflow_admin_audit (
    audit_id INTEGER PRIMARY KEY,
    actor_username TEXT NOT NULL,
    table_name TEXT NOT NULL,
    object_pk TEXT NOT NULL,
    action_code TEXT NOT NULL CHECK (action_code IN ('create','update','delete')),
    before_json TEXT,
    after_json TEXT,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_admin_audit_object
    ON workflow_admin_audit(table_name, object_pk, audit_id DESC);
