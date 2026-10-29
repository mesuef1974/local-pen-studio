"""Record privacy-preserving Codex usage metrics in a local SQLite database."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import time

from usage_database import SCHEMA_VERSION, connect, import_legacy, insert_sample, utc_now

COLLECTOR_VERSION = "4"
RUN_LEASE_SECONDS = 15 * 60


def session_names(index_path: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        rows = index_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return names
    for line in rows:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("thread_name"), str):
            names[row["id"]] = row["thread_name"].strip() or row["id"]
    return names


def metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            row = json.loads(stream.readline())
    except (OSError, ValueError):
        return None, None
    payload = row.get("payload", {}) if isinstance(row, dict) and row.get("type") == "session_meta" else {}
    if not isinstance(payload, dict):
        return None, None
    session_id = payload.get("session_id") or payload.get("id")
    return (session_id if isinstance(session_id, str) else None,
            payload.get("timestamp") if isinstance(payload.get("timestamp"), str) else None)


def new_rows(path: Path, offset: int) -> tuple[list[dict], int, int]:
    size = path.stat().st_size
    if offset > size:
        offset = 0
    start = max(0, offset)
    with path.open("rb") as stream:
        stream.seek(start)
        data = stream.read()
        end = stream.tell()
    if data and not data.endswith(b"\n"):
        complete_length = data.rfind(b"\n") + 1
        data = data[:complete_length]
        end = start + complete_length
    rows = []
    malformed_lines = 0
    for raw in data.splitlines():
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            malformed_lines += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            malformed_lines += 1
    return rows, end, malformed_lines


def numeric_usage(value: object) -> dict | None:
    fields = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
              "output_tokens", "reasoning_output_tokens", "total_tokens")
    if not isinstance(value, dict):
        return None
    result = {}
    for field in fields:
        number = value.get(field, 0)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            return None
        result[field] = number
    return result


def sample(row: dict, settings: dict) -> dict | None:
    payload = row.get("payload", {})
    if not isinstance(payload, dict):
        return None
    if row.get("type") != "event_msg" or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    current = numeric_usage(info.get("last_token_usage"))
    cumulative = numeric_usage(info.get("total_token_usage"))
    window = info.get("model_context_window")
    if not current or not cumulative or not isinstance(window, int) or window <= 0:
        return None
    rate = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else {}
    primary = rate.get("primary") if isinstance(rate.get("primary"), dict) else {}
    used_percent = primary.get("used_percent")
    window_minutes = primary.get("window_minutes")
    weekly = None
    if (isinstance(used_percent, (int, float)) and not isinstance(used_percent, bool)
            and 0 <= used_percent <= 100 and math.isfinite(used_percent)
            and isinstance(window_minutes, int) and not isinstance(window_minutes, bool)
            and window_minutes > 0):
        weekly = {
            "used_percent": used_percent,
            "remaining_percent": 100 - used_percent,
            "window_minutes": window_minutes,
            "resets_at": primary.get("resets_at") if isinstance(primary.get("resets_at"), int)
                         and not isinstance(primary.get("resets_at"), bool) else None,
            "plan_type": rate.get("plan_type"),
        }
    return {
        "timestamp": row.get("timestamp"),
        "model": settings.get("model"),
        "reasoning_effort": settings.get("reasoning_effort"),
        "service_tier": settings.get("service_tier"),
        "context": {
            **current,
            "window_tokens": window,
            "used_percent": round(current["total_tokens"] * 100 / window, 3),
            "remaining_percent": round(max(0, window - current["total_tokens"]) * 100 / window, 3),
        },
        "cumulative": cumulative,
        "weekly": weekly,
    }


def run(sessions_root: Path, index_path: Path, database_path: Path,
        legacy_sessions: Path | None = None, legacy_state: Path | None = None) -> dict:
    names = session_names(index_path)
    updated_sessions: set[str] = set()
    connection = connect(database_path)
    started_at = utc_now()
    run_id = None
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=RUN_LEASE_SECONDS)).isoformat()
            active = connection.execute(
                "SELECT run_id,started_at FROM usage_collector_runs WHERE status='running' "
                "AND COALESCE(heartbeat_at,started_at)>=? ORDER BY run_id DESC LIMIT 1", (cutoff,)
            ).fetchone()
            if active:
                raise RuntimeError(
                    f"يوجد تشغيل جامع نشط بالفعل (run_id={active['run_id']})؛ لم يبدأ تشغيل متداخل."
                )
            connection.execute(
                "UPDATE usage_collector_runs SET status='interrupted',completed_at=?, "
                "error_message='انتهت مهلة نبض تشغيل سابق' WHERE status='running' "
                "AND COALESCE(heartbeat_at,started_at)<?", (started_at, cutoff),
            )
            run_id = connection.execute(
                """INSERT INTO usage_collector_runs(started_at,heartbeat_at,status,collector_version,schema_version)
                VALUES(?,?,'running',?,?)""",
                (started_at, started_at, COLLECTOR_VERSION, SCHEMA_VERSION),
            ).lastrowid
    except Exception:
        connection.close()
        raise
    source_files_seen = source_files_updated = records_read = samples_inserted = malformed_lines = 0
    last_heartbeat = time.monotonic()
    try:
        migration = import_legacy(connection, legacy_sessions or Path(), legacy_state or Path())
        with connection:
            for session_id, name in names.items():
                connection.execute("UPDATE usage_sessions SET session_name=? WHERE session_id=?",
                                   (name, session_id))
        transcripts = list(sessions_root.rglob("*.jsonl"))
        source_files_seen = len(transcripts)
        for transcript in transcripts:
            if time.monotonic() - last_heartbeat >= 30:
                with connection:
                    connection.execute("UPDATE usage_collector_runs SET heartbeat_at=? WHERE run_id=?",
                                       (utc_now(), run_id))
                last_heartbeat = time.monotonic()
            session_id, created_at = metadata(transcript)
            if not session_id:
                continue
            file_key = str(transcript.resolve())
            saved = connection.execute("SELECT * FROM usage_sources WHERE source_path=?", (file_key,)).fetchone()
            size = transcript.stat().st_size
            offset = saved["offset_bytes"] if saved else 0
            if offset == size:
                continue
            rows, end, invalid = new_rows(transcript, offset)
            records_read += len(rows)
            malformed_lines += invalid
            source_files_updated += 1
            settings = {"model": saved["model"], "reasoning_effort": saved["reasoning_effort"],
                        "service_tier": saved["service_tier"]} if saved else {}
            with connection:
                for row in rows:
                    payload = row.get("payload", {})
                    if row.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                        candidate = payload.get("thread_settings")
                        if isinstance(candidate, dict):
                            settings = {key: candidate.get(key) for key in
                                        ("model", "reasoning_effort", "service_tier")}
                    measured = sample(row, settings)
                    if measured and insert_sample(connection, session_id,
                                                  names.get(session_id, session_id), created_at, measured):
                        updated_sessions.add(session_id)
                        samples_inserted += 1
                connection.execute(
                    """INSERT INTO usage_sources(source_path,session_id,offset_bytes,model,reasoning_effort,
                    service_tier,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_path) DO UPDATE SET
                    session_id=excluded.session_id,offset_bytes=excluded.offset_bytes,model=excluded.model,
                    reasoning_effort=excluded.reasoning_effort,service_tier=excluded.service_tier,
                    updated_at=excluded.updated_at""",
                    (file_key, session_id, end, settings.get("model"), settings.get("reasoning_effort"),
                     settings.get("service_tier"), utc_now()),
                )
                connection.execute(
                    """UPDATE usage_collector_runs SET heartbeat_at=?,source_files_seen=?,source_files_updated=?,records_read=?,
                    samples_inserted=?,malformed_lines=? WHERE run_id=?""",
                    (utc_now(), source_files_seen, source_files_updated, records_read, samples_inserted,
                     malformed_lines, run_id),
                )
            last_heartbeat = time.monotonic()
        known = connection.execute("SELECT COUNT(DISTINCT session_id) FROM usage_sources").fetchone()[0]
        known += connection.execute("SELECT COUNT(*) FROM usage_sessions WHERE session_id NOT IN "
                                    "(SELECT DISTINCT session_id FROM usage_sources)").fetchone()[0]
        completed_at = utc_now()
        with connection:
            connection.execute(
                """UPDATE usage_collector_runs SET heartbeat_at=?,completed_at=?,status='success',source_files_seen=?,
                source_files_updated=?,records_read=?,samples_inserted=?,malformed_lines=? WHERE run_id=?""",
                (completed_at, completed_at, source_files_seen, source_files_updated, records_read, samples_inserted,
                 malformed_lines, run_id),
            )
        return {"sessions_updated": len(updated_sessions), "sessions_known": known,
                "source_files_seen": source_files_seen, "source_files_updated": source_files_updated,
                "records_read": records_read, "samples_inserted": samples_inserted,
                "malformed_lines": malformed_lines, "run_id": run_id,
                "database": str(database_path), **migration}
    except Exception as exc:
        try:
            with connection:
                connection.execute(
                    """UPDATE usage_collector_runs SET heartbeat_at=?,completed_at=?,status='failed',source_files_seen=?,
                    source_files_updated=?,records_read=?,samples_inserted=?,malformed_lines=?,error_message=?
                    WHERE run_id=?""",
                    (utc_now(), utc_now(), source_files_seen, source_files_updated, records_read, samples_inserted,
                     malformed_lines, f"{type(exc).__name__}: {exc}"[:500], run_id),
                )
        except Exception:
            pass
        raise
    finally:
        connection.close()


def main() -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-root", type=Path, default=codex_home / "sessions")
    parser.add_argument("--index", type=Path, default=codex_home / "session_index.jsonl")
    parser.add_argument("--database", type=Path, default=codex_home / "usage-logs" / "usage.sqlite3")
    parser.add_argument("--legacy-sessions", type=Path, default=codex_home / "usage-logs" / "sessions")
    parser.add_argument("--legacy-state", type=Path, default=codex_home / "usage-logs" / "state.json")
    args = parser.parse_args()
    result = run(args.sessions_root, args.index, args.database, args.legacy_sessions, args.legacy_state)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
