DROP TRIGGER usage_samples_weekly_insert_guard;
DROP TRIGGER usage_samples_weekly_update_guard;

CREATE TRIGGER usage_samples_weekly_insert_guard
BEFORE INSERT ON usage_samples
WHEN NEW.weekly_used_percent IS NOT NULL OR NEW.weekly_remaining_percent IS NOT NULL
     OR NEW.weekly_window_minutes IS NOT NULL
BEGIN
    SELECT CASE WHEN
        typeof(NEW.weekly_used_percent) NOT IN ('integer','real')
        OR NEW.weekly_used_percent < 0 OR NEW.weekly_used_percent > 100
        OR typeof(NEW.weekly_remaining_percent) NOT IN ('integer','real')
        OR NEW.weekly_remaining_percent < 0 OR NEW.weekly_remaining_percent > 100
        OR ABS(NEW.weekly_used_percent + NEW.weekly_remaining_percent - 100) > 0.001
        OR typeof(NEW.weekly_window_minutes) <> 'integer' OR NEW.weekly_window_minutes <= 0
    THEN RAISE(ABORT,'invalid weekly usage snapshot') END;
END;

CREATE TRIGGER usage_samples_weekly_update_guard
BEFORE UPDATE OF weekly_used_percent,weekly_remaining_percent,weekly_window_minutes ON usage_samples
WHEN NEW.weekly_used_percent IS NOT NULL OR NEW.weekly_remaining_percent IS NOT NULL
     OR NEW.weekly_window_minutes IS NOT NULL
BEGIN
    SELECT CASE WHEN
        typeof(NEW.weekly_used_percent) NOT IN ('integer','real')
        OR NEW.weekly_used_percent < 0 OR NEW.weekly_used_percent > 100
        OR typeof(NEW.weekly_remaining_percent) NOT IN ('integer','real')
        OR NEW.weekly_remaining_percent < 0 OR NEW.weekly_remaining_percent > 100
        OR ABS(NEW.weekly_used_percent + NEW.weekly_remaining_percent - 100) > 0.001
        OR typeof(NEW.weekly_window_minutes) <> 'integer' OR NEW.weekly_window_minutes <= 0
    THEN RAISE(ABORT,'invalid weekly usage snapshot') END;
END;
