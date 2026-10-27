"""Record Codex token and weekly-allowance snapshots without calling a model.

The logger reads local rollout JSONL files only.  It stores one JSON document per
session and never reads prompt, response, or tool-output bodies into its output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

VERSION = 1
TAIL_BYTES = 8 * 1024 * 1024
MAX_SAMPLES = 20_000


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


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
        if isinstance(row.get("id"), str) and isinstance(row.get("thread_name"), str):
            names[row["id"]] = row["thread_name"].strip() or row["id"]
    return names


def safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .-")
    value = re.sub(r"\s+", " ", value)
    return (value[:100].rstrip(" .-") or "جلسة")


def metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            row = json.loads(stream.readline())
    except (OSError, ValueError):
        return None, None
    payload = row.get("payload", {}) if row.get("type") == "session_meta" else {}
    session_id = payload.get("session_id") or payload.get("id")
    return (session_id if isinstance(session_id, str) else None,
            payload.get("timestamp") if isinstance(payload.get("timestamp"), str) else None)


def new_rows(path: Path, offset: int) -> tuple[list[dict], int]:
    size = path.stat().st_size
    start = offset if 0 <= offset <= size else max(0, size - TAIL_BYTES)
    first_tail = offset == 0 and start > 0
    with path.open("rb") as stream:
        stream.seek(start)
        if first_tail:
            stream.readline()
        data = stream.read()
        end = stream.tell()
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


def output_path(directory: Path, title: str, session_id: str) -> Path:
    suffix = f"--{session_id}.json"
    desired = directory / f"{safe_name(title)}{suffix}"
    for existing in directory.glob(f"*{suffix}"):
        if existing != desired and not desired.exists():
            existing.replace(desired)
    return desired


def run(sessions_root: Path, index_path: Path, output: Path, state_path: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    state = read_json(state_path, {"version": VERSION, "files": {}})
    if not isinstance(state, dict) or not isinstance(state.get("files"), dict):
        state = {"version": VERSION, "files": {}}
    names = session_names(index_path)
    updated_sessions: set[str] = set()
    for transcript in sessions_root.rglob("*.jsonl"):
        session_id, created_at = metadata(transcript)
        if not session_id:
            continue
        file_key = str(transcript.resolve())
        saved = state["files"].get(file_key, {})
        offset = saved.get("offset", 0) if isinstance(saved.get("offset", 0), int) else 0
        if offset == transcript.stat().st_size:
            continue
        rows, end = new_rows(transcript, offset)
        settings = saved.get("settings", {}) if isinstance(saved.get("settings"), dict) else {}
        additions = []
        for row in rows:
            payload = row.get("payload", {})
            if row.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                candidate = payload.get("thread_settings")
                if isinstance(candidate, dict):
                    settings = {key: candidate.get(key) for key in
                                ("model", "reasoning_effort", "service_tier")}
            measured = sample(row, settings)
            if measured:
                additions.append(measured)
        state["files"][file_key] = {
            "session_id": session_id, "offset": end, "settings": settings,
        }
        if not additions:
            continue
        title = names.get(session_id, session_id)
        target = output_path(output, title, session_id)
        document = read_json(target, {})
        if not isinstance(document, dict):
            document = {}
        samples = document.get("samples", []) if isinstance(document.get("samples"), list) else []
        seen = {(item.get("timestamp"), item.get("cumulative", {}).get("total_tokens"))
                for item in samples if isinstance(item, dict)}
        samples.extend(item for item in additions
                       if (item.get("timestamp"), item["cumulative"]["total_tokens"]) not in seen)
        samples = samples[-MAX_SAMPLES:]
        atomic_json(target, {
            "version": VERSION,
            "session_id": session_id,
            "session_name": title,
            "created_at": document.get("created_at") or created_at,
            "updated_at": samples[-1]["timestamp"],
            "source": "local-codex-rollout-token-count",
            "samples": samples,
        })
        updated_sessions.add(session_id)
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(state_path, state)
    known = {item.get("session_id") for item in state["files"].values()
             if isinstance(item, dict) and isinstance(item.get("session_id"), str)}
    return {"sessions_updated": len(updated_sessions), "sessions_known": len(known),
            "output": str(output)}


def main() -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-root", type=Path, default=codex_home / "sessions")
    parser.add_argument("--index", type=Path, default=codex_home / "session_index.jsonl")
    parser.add_argument("--output", type=Path, default=codex_home / "usage-logs" / "sessions")
    parser.add_argument("--state", type=Path, default=codex_home / "usage-logs" / "state.json")
    args = parser.parse_args()
    print(json.dumps(run(args.sessions_root, args.index, args.output, args.state), ensure_ascii=False))


if __name__ == "__main__":
    main()
