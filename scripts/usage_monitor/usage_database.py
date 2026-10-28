"""Local SQLite persistence for coordination records and Codex usage metrics."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 6

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS coordination_actors (
    actor_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    charter TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE TABLE IF NOT EXISTS coordination_cards (
    card_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    owner_request TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','accepted','in_progress','blocked','delivered','accepted_by_owner','archived')),
    assigned_actor_id TEXT REFERENCES coordination_actors(actor_id),
    coordinator_actor_id TEXT REFERENCES coordination_actors(actor_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coordination_opinions (
    opinion_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES coordination_actors(actor_id),
    opinion TEXT NOT NULL,
    recommendation TEXT,
    recorded_at TEXT NOT NULL,
    UNIQUE (card_id, actor_id)
);
CREATE TABLE IF NOT EXISTS owner_decisions (
    decision_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id) ON DELETE CASCADE,
    axis TEXT NOT NULL,
    decision TEXT NOT NULL,
    notes TEXT,
    decided_at TEXT NOT NULL,
    UNIQUE (card_id, axis)
);
CREATE TABLE IF NOT EXISTS coordination_deliverables (
    deliverable_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    checksum_sha256 TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (card_id, path)
);
CREATE TABLE IF NOT EXISTS coordination_git_events (
    git_event_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id) ON DELETE CASCADE,
    remote_name TEXT,
    branch_name TEXT NOT NULL,
    commit_sha TEXT,
    action TEXT NOT NULL CHECK (action IN ('commit','push','merge','release')),
    outcome TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coordination_events (
    event_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES coordination_cards(card_id) ON DELETE CASCADE,
    actor_id TEXT REFERENCES coordination_actors(actor_id),
    event_type TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_cards_status ON coordination_cards(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_coord_events_card_time ON coordination_events(card_id, recorded_at);

CREATE TABLE IF NOT EXISTS usage_sessions (
    session_id TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS usage_samples (
    sample_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES usage_sessions(session_id) ON DELETE CASCADE,
    sampled_at TEXT NOT NULL,
    model TEXT,
    reasoning_effort TEXT,
    service_tier TEXT,
    context_window_tokens INTEGER NOT NULL CHECK (context_window_tokens > 0),
    context_total_tokens INTEGER NOT NULL CHECK (context_total_tokens >= 0),
    context_input_tokens INTEGER NOT NULL CHECK (context_input_tokens >= 0),
    context_cached_input_tokens INTEGER NOT NULL CHECK (context_cached_input_tokens >= 0),
    context_cache_write_input_tokens INTEGER NOT NULL CHECK (context_cache_write_input_tokens >= 0),
    context_output_tokens INTEGER NOT NULL CHECK (context_output_tokens >= 0),
    context_reasoning_output_tokens INTEGER NOT NULL CHECK (context_reasoning_output_tokens >= 0),
    context_used_percent REAL NOT NULL,
    cumulative_total_tokens INTEGER NOT NULL CHECK (cumulative_total_tokens >= 0),
    cumulative_input_tokens INTEGER NOT NULL CHECK (cumulative_input_tokens >= 0),
    cumulative_cached_input_tokens INTEGER NOT NULL CHECK (cumulative_cached_input_tokens >= 0),
    cumulative_cache_write_input_tokens INTEGER NOT NULL CHECK (cumulative_cache_write_input_tokens >= 0),
    cumulative_output_tokens INTEGER NOT NULL CHECK (cumulative_output_tokens >= 0),
    cumulative_reasoning_output_tokens INTEGER NOT NULL CHECK (cumulative_reasoning_output_tokens >= 0),
    weekly_used_percent REAL,
    weekly_remaining_percent REAL,
    weekly_window_minutes INTEGER,
    weekly_resets_at INTEGER,
    weekly_plan_type TEXT,
    UNIQUE (session_id, sampled_at, cumulative_total_tokens)
);
CREATE INDEX IF NOT EXISTS idx_usage_samples_session_time ON usage_samples(session_id, sampled_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_samples_weekly_time ON usage_samples(sampled_at DESC) WHERE weekly_used_percent IS NOT NULL;
CREATE TABLE IF NOT EXISTS usage_sources (
    source_path TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    offset_bytes INTEGER NOT NULL CHECK (offset_bytes >= 0),
    model TEXT,
    reasoning_effort TEXT,
    service_tier TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS database_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA synchronous = NORMAL")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        connection.close()
        raise RuntimeError(f"Database schema {version} is newer than supported {SCHEMA_VERSION}")
    if version < 1:
        connection.execute("PRAGMA journal_mode = WAL")
        with connection:
            connection.executescript(SCHEMA_V1)
            connection.execute("PRAGMA user_version = 1")
        version = 1
    while version < SCHEMA_VERSION:
        target = version + 1
        migration_path = Path(__file__).with_name("migrations") / f"{target:03d}_*.sql"
        matches = sorted(migration_path.parent.glob(migration_path.name))
        if len(matches) != 1:
            connection.close()
            raise RuntimeError(f"Expected one database migration for version {target}")
        migration_sql = matches[0].read_text(encoding="utf-8")
        checksum = hashlib.sha256(migration_sql.encode("utf-8")).hexdigest()
        try:
            connection.executescript("BEGIN IMMEDIATE;\n" + migration_sql)
            connection.execute(
                "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at) VALUES(?,?,?,?)",
                (target, matches[0].stem, checksum, utc_now()),
            )
            connection.execute(f"PRAGMA user_version = {target}")
            connection.commit()
        except Exception:
            connection.rollback()
            connection.close()
            raise
        version = target
    return connection


def _counter_values(value: object) -> list[int] | None:
    if not isinstance(value, dict):
        return None
    fields = ("total_tokens", "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
              "output_tokens", "reasoning_output_tokens")
    values = []
    for field in fields:
        number = value.get(field, 0)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            return None
        values.append(number)
    return values


def insert_sample(connection: sqlite3.Connection, session_id: str, session_name: str,
                  created_at: str | None, sample: dict) -> bool:
    timestamp = sample.get("timestamp")
    context = sample.get("context")
    cumulative = sample.get("cumulative")
    weekly = sample.get("weekly")
    if not isinstance(timestamp, str) or not isinstance(context, dict):
        return False
    current_values = _counter_values(context)
    cumulative_values = _counter_values(cumulative)
    window = context.get("window_tokens")
    used = context.get("used_percent")
    if (current_values is None or cumulative_values is None or not isinstance(window, int)
            or isinstance(window, bool) or window <= 0 or not isinstance(used, (int, float))):
        return False
    connection.execute(
        "INSERT INTO usage_sessions(session_id,session_name,created_at,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(session_id) DO UPDATE SET session_name=excluded.session_name, "
        "created_at=COALESCE(usage_sessions.created_at,excluded.created_at), "
        "updated_at=MAX(COALESCE(usage_sessions.updated_at,''),excluded.updated_at)",
        (session_id, session_name, created_at, timestamp),
    )
    weekly = weekly if isinstance(weekly, dict) else {}
    cursor = connection.execute(
        """INSERT OR IGNORE INTO usage_samples(
        session_id,sampled_at,model,reasoning_effort,service_tier,context_window_tokens,
        context_total_tokens,context_input_tokens,context_cached_input_tokens,context_cache_write_input_tokens,
        context_output_tokens,context_reasoning_output_tokens,context_used_percent,
        cumulative_total_tokens,cumulative_input_tokens,cumulative_cached_input_tokens,
        cumulative_cache_write_input_tokens,cumulative_output_tokens,cumulative_reasoning_output_tokens,
        weekly_used_percent,weekly_remaining_percent,weekly_window_minutes,weekly_resets_at,weekly_plan_type,
        coordination_card_id,workflow_stage_code
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, timestamp, sample.get("model"), sample.get("reasoning_effort"), sample.get("service_tier"),
         window, *current_values, float(used), *cumulative_values,
         weekly.get("used_percent"), weekly.get("remaining_percent"), weekly.get("window_minutes"),
         weekly.get("resets_at"), weekly.get("plan_type"),
         sample.get("coordination_card_id"), sample.get("workflow_stage_code")),
    )
    return cursor.rowcount == 1


def import_legacy(connection: sqlite3.Connection, sessions_dir: Path, state_path: Path) -> dict:
    imported_sessions = imported_samples = imported_cursors = 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        marker = connection.execute("SELECT value FROM database_metadata WHERE key='legacy_import_v1'").fetchone()
        if marker:
            connection.commit()
            return {"legacy_sessions": 0, "legacy_samples": 0, "legacy_cursors": 0}
        for path in sorted(sessions_dir.glob("*.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(item, dict) or not isinstance(item.get("samples"), list):
                continue
            session_id = item.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            name = item.get("session_name") if isinstance(item.get("session_name"), str) else session_id
            imported_sessions += 1
            for row in item["samples"]:
                if isinstance(row, dict) and insert_sample(connection, session_id, name, item.get("created_at"), row):
                    imported_samples += 1
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            state = {}
        files = state.get("files", {}) if isinstance(state, dict) else {}
        if isinstance(files, dict):
            for source_path, saved in files.items():
                if not isinstance(source_path, str) or not isinstance(saved, dict):
                    continue
                session_id = saved.get("session_id")
                offset = saved.get("offset")
                if not isinstance(session_id, str) or not isinstance(offset, int) or offset < 0:
                    continue
                settings = saved.get("settings") if isinstance(saved.get("settings"), dict) else {}
                connection.execute(
                    """INSERT OR IGNORE INTO usage_sources
                    (source_path,session_id,offset_bytes,model,reasoning_effort,service_tier,updated_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (source_path, session_id, offset, settings.get("model"), settings.get("reasoning_effort"),
                     settings.get("service_tier"), utc_now()),
                )
                imported_cursors += 1
        connection.execute("INSERT INTO database_metadata(key,value) VALUES('legacy_import_v1',?)",
                           (utc_now(),))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"legacy_sessions": imported_sessions, "legacy_samples": imported_samples,
            "legacy_cursors": imported_cursors}


def dashboard_data(database: Path) -> dict:
    connection = connect(database)
    try:
        sessions = []
        for session in connection.execute("SELECT * FROM usage_sessions ORDER BY session_name COLLATE NOCASE"):
            rows = connection.execute(
                "SELECT * FROM usage_samples WHERE session_id=? ORDER BY sampled_at DESC,sample_id DESC LIMIT 500",
                (session["session_id"],),
            ).fetchall()
            if not rows:
                continue
            samples = []
            for row in reversed(rows):
                samples.append({
                    "timestamp": row["sampled_at"], "model": row["model"],
                    "context": {"used_percent": row["context_used_percent"],
                                "total_tokens": row["context_total_tokens"],
                                "input_tokens": row["context_input_tokens"],
                                "cached_input_tokens": row["context_cached_input_tokens"],
                                "output_tokens": row["context_output_tokens"],
                                "reasoning_output_tokens": row["context_reasoning_output_tokens"]},
                    "cumulative": {"total_tokens": row["cumulative_total_tokens"],
                                   "input_tokens": row["cumulative_input_tokens"],
                                   "cached_input_tokens": row["cumulative_cached_input_tokens"],
                                   "output_tokens": row["cumulative_output_tokens"],
                                   "reasoning_output_tokens": row["cumulative_reasoning_output_tokens"]},
                })
            sessions.append({"session_id": session["session_id"], "session_name": session["session_name"],
                             "created_at": session["created_at"], "updated_at": session["updated_at"],
                             "model": samples[-1].get("model"), "samples": samples})
        weekly_row = connection.execute(
            """SELECT sampled_at,weekly_used_percent,weekly_remaining_percent,weekly_resets_at,
            weekly_window_minutes,weekly_plan_type FROM usage_samples
            WHERE weekly_used_percent IS NOT NULL ORDER BY sampled_at DESC,sample_id DESC LIMIT 1"""
        ).fetchone()
        weekly = None
        if weekly_row:
            weekly = {"timestamp": weekly_row["sampled_at"], "used_percent": weekly_row["weekly_used_percent"],
                      "remaining_percent": weekly_row["weekly_remaining_percent"],
                      "resets_at": weekly_row["weekly_resets_at"],
                      "window_minutes": weekly_row["weekly_window_minutes"],
                      "plan_type": weekly_row["weekly_plan_type"]}
        return {"version": 1, "generated_at": utc_now(), "weekly": weekly, "sessions": sessions}
    finally:
        connection.close()
