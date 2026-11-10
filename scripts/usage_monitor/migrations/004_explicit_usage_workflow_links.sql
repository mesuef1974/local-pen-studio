ALTER TABLE usage_samples ADD COLUMN coordination_card_id TEXT
    REFERENCES coordination_cards(card_id);
ALTER TABLE usage_samples ADD COLUMN workflow_stage_code TEXT;
ALTER TABLE coordination_events ADD COLUMN codex_session_id TEXT
    REFERENCES usage_sessions(session_id);

CREATE INDEX IF NOT EXISTS idx_usage_samples_card_stage_time
    ON usage_samples(coordination_card_id,workflow_stage_code,sampled_at DESC)
    WHERE coordination_card_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_coord_events_codex_session_time
    ON coordination_events(codex_session_id,recorded_at)
    WHERE codex_session_id IS NOT NULL;
