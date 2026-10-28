ALTER TABLE coordination_cards ADD COLUMN current_status_code TEXT NOT NULL DEFAULT 'draft';
ALTER TABLE coordination_cards ADD COLUMN current_status_version INTEGER NOT NULL DEFAULT 1
    CHECK (current_status_version > 0);

INSERT OR IGNORE INTO workflow_status_definitions
(status_code,version,display_name,terminal,effective_at) VALUES
('accepted_by_owner',1,'مقبولة من المالك',1,'2026-10-28T00:00:00Z');

UPDATE coordination_cards SET current_status_code=status
WHERE EXISTS (SELECT 1 FROM workflow_status_definitions s
              WHERE s.status_code=coordination_cards.status AND s.version=1);

CREATE TRIGGER IF NOT EXISTS trg_coord_card_status_valid_insert
BEFORE INSERT ON coordination_cards
WHEN NOT EXISTS (SELECT 1 FROM workflow_status_definitions s
                 WHERE s.status_code=NEW.current_status_code AND s.version=NEW.current_status_version)
BEGIN SELECT RAISE(ABORT, 'unknown versioned workflow status'); END;

CREATE TRIGGER IF NOT EXISTS trg_coord_card_status_valid_update
BEFORE UPDATE OF current_status_code,current_status_version ON coordination_cards
WHEN NOT EXISTS (SELECT 1 FROM workflow_status_definitions s
                 WHERE s.status_code=NEW.current_status_code AND s.version=NEW.current_status_version)
BEGIN SELECT RAISE(ABORT, 'unknown versioned workflow status'); END;

CREATE TRIGGER IF NOT EXISTS trg_coord_card_transition_requires_event
BEFORE UPDATE OF current_status_code,current_status_version ON coordination_cards
WHEN (NEW.current_status_code <> OLD.current_status_code OR NEW.current_status_version <> OLD.current_status_version)
 AND NOT EXISTS (SELECT 1 FROM coordination_events e WHERE e.card_id=OLD.card_id
                 AND e.previous_status=OLD.current_status_code AND e.next_status=NEW.current_status_code)
BEGIN SELECT RAISE(ABORT, 'status transition requires an append-only coordination event'); END;

CREATE INDEX IF NOT EXISTS idx_coord_cards_current_status
    ON coordination_cards(current_status_code,current_status_version,updated_at);
