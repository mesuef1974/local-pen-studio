CREATE TABLE IF NOT EXISTS coordination_actor_endpoints (
    actor_id TEXT PRIMARY KEY REFERENCES coordination_actors(actor_id),
    provider_code TEXT NOT NULL DEFAULT 'codex_cli'
        CHECK (provider_code IN ('codex_cli')),
    thread_id TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_actor_endpoints_enabled
    ON coordination_actor_endpoints(enabled,actor_id);

CREATE TABLE IF NOT EXISTS coordination_actor_capabilities (
    actor_id TEXT NOT NULL REFERENCES coordination_actor_endpoints(actor_id) ON DELETE CASCADE,
    capability TEXT NOT NULL,
    PRIMARY KEY (actor_id,capability)
);
CREATE INDEX IF NOT EXISTS idx_coord_actor_capabilities_term
    ON coordination_actor_capabilities(capability,actor_id);
