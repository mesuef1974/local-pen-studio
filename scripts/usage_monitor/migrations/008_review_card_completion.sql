-- A review task delivers a written review; it does not require a source push.
-- The lifecycle API restricts this transition to review-classified cards.
INSERT OR IGNORE INTO workflow_transition_rules(from_status_code,to_status_code,version,enabled)
VALUES('in_progress','completed',1,1);
