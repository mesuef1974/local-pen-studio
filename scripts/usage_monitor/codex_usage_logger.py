"""Record privacy-preserving Codex usage metrics in a local SQLite database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from usage_database import connect, import_legacy, insert_sample, utc_now

TAIL_BYTES = 8 * 1024 * 1024


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


def new_rows(path: Path, offset: int) -> tuple[list[dict], int]:
    size = path.stat().st_size
    if offset > size:
        offset = 0
    start = offset if 0 <= offset <= size else max(0, size - TAIL_BYTES)
    first_tail = offset == 0 and start > 0
    with path.open("rb") as stream:
        stream.seek(start)
        if first_tail:
            stream.readline()
        data = stream.read()
        end = stream.tell()
    if data and not data.endswith(b"\n"):
        complete_length = data.rfind(b"\n") + 1
        data = data[:complete_length]
        end = start + complete_length
    rows = []
    for raw in data.splitlines():
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows, end


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
    weekly = None
    if isinstance(used_percent, (int, float)) and not isinstance(used_percent, bool):
        weekly = {
            "used_percent": used_percent,
            "remaining_percent": max(0, min(100, 100 - used_percent)),
            "window_minutes": primary.get("window_minutes"),
            "resets_at": primary.get("resets_at"),
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
    try:
        migration = import_legacy(connection, legacy_sessions or Path(), legacy_state or Path())
        with connection:
            for session_id, name in names.items():
                connection.execute("UPDATE usage_sessions SET session_name=? WHERE session_id=?",
                                   (name, session_id))
        for transcript in sessions_root.rglob("*.jsonl"):
            session_id, created_at = metadata(transcript)
            if not session_id:
                continue
            file_key = str(transcript.resolve())
            saved = connection.execute("SELECT * FROM usage_sources WHERE source_path=?", (file_key,)).fetchone()
            size = transcript.stat().st_size
            offset = saved["offset_bytes"] if saved else 0
            if offset == size:
                continue
            rows, end = new_rows(transcript, offset)
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
                connection.execute(
                    """INSERT INTO usage_sources(source_path,session_id,offset_bytes,model,reasoning_effort,
                    service_tier,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_path) DO UPDATE SET
                    session_id=excluded.session_id,offset_bytes=excluded.offset_bytes,model=excluded.model,
                    reasoning_effort=excluded.reasoning_effort,service_tier=excluded.service_tier,
                    updated_at=excluded.updated_at""",
                    (file_key, session_id, end, settings.get("model"), settings.get("reasoning_effort"),
                     settings.get("service_tier"), utc_now()),
                )
        known = connection.execute("SELECT COUNT(DISTINCT session_id) FROM usage_sources").fetchone()[0]
        known += connection.execute("SELECT COUNT(*) FROM usage_sessions WHERE session_id NOT IN "
                                    "(SELECT DISTINCT session_id FROM usage_sources)").fetchone()[0]
        return {"sessions_updated": len(updated_sessions), "sessions_known": known,
                "database": str(database_path), **migration}
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
