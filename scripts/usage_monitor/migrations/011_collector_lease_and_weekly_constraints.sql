ALTER TABLE usage_collector_runs ADD COLUMN heartbeat_at TEXT;
UPDATE usage_collector_runs SET heartbeat_at=started_at WHERE heartbeat_at IS NULL;
CREATE INDEX idx_usage_collector_runs_status_heartbeat
    ON usage_collector_runs(status,heartbeat_at DESC);

CREATE TRIGGER usage_samples_weekly_insert_guard
BEFORE INSERT ON usage_samples
WHEN NEW.weekly_used_percent IS NOT NULL AND (
    typeof(NEW.weekly_used_percent) NOT IN ('integer','real')
    OR NEW.weekly_used_percent < 0 OR NEW.weekly_used_percent > 100
    OR typeof(NEW.weekly_remaining_percent) NOT IN ('integer','real')
    OR NEW.weekly_remaining_percent < 0 OR NEW.weekly_remaining_percent > 100
    OR ABS(NEW.weekly_used_percent + NEW.weekly_remaining_percent - 100) > 0.001
    OR typeof(NEW.weekly_window_minutes) <> 'integer' OR NEW.weekly_window_minutes <= 0
)
BEGIN
    SELECT RAISE(ABORT,'invalid weekly usage snapshot');
END;

CREATE TRIGGER usage_samples_weekly_update_guard
BEFORE UPDATE OF weekly_used_percent,weekly_remaining_percent,weekly_window_minutes ON usage_samples
WHEN NEW.weekly_used_percent IS NOT NULL AND (
    typeof(NEW.weekly_used_percent) NOT IN ('integer','real')
    OR NEW.weekly_used_percent < 0 OR NEW.weekly_used_percent > 100
    OR typeof(NEW.weekly_remaining_percent) NOT IN ('integer','real')
    OR NEW.weekly_remaining_percent < 0 OR NEW.weekly_remaining_percent > 100
    OR ABS(NEW.weekly_used_percent + NEW.weekly_remaining_percent - 100) > 0.001
    OR typeof(NEW.weekly_window_minutes) <> 'integer' OR NEW.weekly_window_minutes <= 0
)
BEGIN
    SELECT RAISE(ABORT,'invalid weekly usage snapshot');
END;
