CREATE TABLE coordination_card_proposals (
    proposal_id TEXT PRIMARY KEY,
    source_card_id TEXT NOT NULL REFERENCES coordination_cards(card_id) ON DELETE RESTRICT,
    source_opinion_history_id INTEGER NOT NULL REFERENCES coordination_opinion_history(opinion_history_id) ON DELETE RESTRICT,
    proposed_by_actor_id TEXT NOT NULL REFERENCES coordination_actors(actor_id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    owner_request TEXT NOT NULL,
    scope TEXT NOT NULL,
    rationale TEXT NOT NULL,
    suggested_assignee_actor_id TEXT REFERENCES coordination_actors(actor_id) ON DELETE SET NULL,
    status_code TEXT NOT NULL DEFAULT 'pending_owner'
        CHECK (status_code IN ('pending_owner','approved','rejected','issued')),
    decision_notes TEXT,
    decided_by_actor_id TEXT REFERENCES coordination_actors(actor_id) ON DELETE SET NULL,
    decided_at TEXT,
    source_event_id INTEGER REFERENCES coordination_events(event_id) ON DELETE SET NULL,
    decision_event_id INTEGER REFERENCES coordination_events(event_id) ON DELETE SET NULL,
    issued_root_card_id TEXT UNIQUE REFERENCES coordination_cards(card_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status_code='issued' AND issued_root_card_id IS NOT NULL)
        OR (status_code<>'issued' AND issued_root_card_id IS NULL)),
    CHECK ((status_code='pending_owner' AND decided_by_actor_id IS NULL AND decided_at IS NULL)
        OR (status_code IN ('approved','rejected','issued') AND decided_by_actor_id IS NOT NULL AND decided_at IS NOT NULL))
);

CREATE TABLE coordination_card_proposal_criteria (
    proposal_criterion_id INTEGER PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES coordination_card_proposals(proposal_id) ON DELETE CASCADE,
    criterion_code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    check_method TEXT NOT NULL DEFAULT 'manual_evidence',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (proposal_id, criterion_code)
);

CREATE INDEX idx_card_proposals_status_time
    ON coordination_card_proposals(status_code, created_at DESC, proposal_id);
CREATE INDEX idx_card_proposals_source_time
    ON coordination_card_proposals(source_card_id, created_at DESC, proposal_id);
CREATE INDEX idx_card_proposal_criteria_order
    ON coordination_card_proposal_criteria(proposal_id, sort_order, proposal_criterion_id);

CREATE TRIGGER trg_card_proposal_state_transitions
BEFORE UPDATE OF status_code ON coordination_card_proposals
WHEN NOT (
    (OLD.status_code='pending_owner' AND NEW.status_code IN ('approved','rejected')
        AND NEW.decided_by_actor_id='owner' AND NEW.decided_at IS NOT NULL
        AND NEW.decision_event_id IS NOT NULL AND NEW.issued_root_card_id IS NULL)
    OR
    (OLD.status_code='approved' AND NEW.status_code='issued'
        AND NEW.decided_by_actor_id=OLD.decided_by_actor_id AND NEW.decided_at=OLD.decided_at
        AND NEW.decision_event_id=OLD.decision_event_id AND NEW.issued_root_card_id IS NOT NULL
        AND EXISTS (SELECT 1 FROM coordination_command_cards c
                    WHERE c.card_id=NEW.issued_root_card_id AND c.role_code='root'))
)
BEGIN SELECT RAISE(ABORT, 'invalid card proposal state transition'); END;

CREATE TRIGGER trg_card_proposal_content_immutable
BEFORE UPDATE OF source_card_id,source_opinion_history_id,proposed_by_actor_id,title,owner_request,scope,
    rationale,suggested_assignee_actor_id,idempotency_key,request_hash_sha256,created_at
ON coordination_card_proposals
BEGIN SELECT RAISE(ABORT, 'card proposal content is immutable'); END;

CREATE TRIGGER trg_card_proposal_no_delete
BEFORE DELETE ON coordination_card_proposals
BEGIN SELECT RAISE(ABORT, 'card proposals cannot be deleted'); END;

CREATE TRIGGER trg_card_proposal_criteria_no_update
BEFORE UPDATE ON coordination_card_proposal_criteria
BEGIN SELECT RAISE(ABORT, 'card proposal criteria are immutable'); END;

CREATE TRIGGER trg_card_proposal_criteria_no_delete
BEFORE DELETE ON coordination_card_proposal_criteria
BEGIN SELECT RAISE(ABORT, 'card proposal criteria cannot be deleted'); END;
