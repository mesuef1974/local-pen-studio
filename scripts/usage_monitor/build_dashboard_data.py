"""Build a privacy-preserving dashboard snapshot from local per-session JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path


def build_data(sessions_dir: Path) -> dict:
    sessions = []
    latest_weekly = None
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(item, dict) or not isinstance(item.get("samples"), list):
            continue
        samples = sorted(
            (row for row in item["samples"] if isinstance(row, dict)),
            key=lambda row: row.get("timestamp") if isinstance(row.get("timestamp"), str) else "",
        )
        if not samples:
            continue
        for row in samples:
            weekly = row.get("weekly")
            timestamp = row.get("timestamp")
            used = weekly.get("used_percent") if isinstance(weekly, dict) else None
            if not isinstance(timestamp, str) or not isinstance(used, (int, float)):
                continue
            if latest_weekly is None or timestamp > latest_weekly["timestamp"]:
                remaining = weekly.get("remaining_percent")
                latest_weekly = {
                    "timestamp": timestamp,
                    "used_percent": used,
                    "remaining_percent": remaining if isinstance(remaining, (int, float)) else max(0, min(100, 100 - used)),
                    "resets_at": weekly.get("resets_at"),
                    "window_minutes": weekly.get("window_minutes"),
                    "plan_type": weekly.get("plan_type"),
                }
        dashboard_samples = []
        for row in samples[-500:]:
            context = row.get("context") if isinstance(row.get("context"), dict) else {}
            cumulative = row.get("cumulative") if isinstance(row.get("cumulative"), dict) else {}
            dashboard_samples.append({
                "timestamp": row.get("timestamp"),
                "model": row.get("model"),
                "context": {key: context.get(key) for key in
                            ("used_percent", "total_tokens", "input_tokens", "cached_input_tokens",
                             "output_tokens", "reasoning_output_tokens")},
                "cumulative": {key: cumulative.get(key) for key in
                               ("total_tokens", "input_tokens", "cached_input_tokens",
                                "output_tokens", "reasoning_output_tokens")},
            })
        sessions.append({
            "session_id": item.get("session_id"),
            "session_name": item.get("session_name") or path.stem,
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "model": dashboard_samples[-1].get("model"),
            "samples": dashboard_samples,
        })
    return {
        "version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "weekly": latest_weekly,
        "sessions": sessions,
    }


def write_snapshot(sessions_dir: Path, output: Path) -> int:
    data = build_data(sessions_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return len(data["sessions"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser.add_argument("--sessions", type=Path, default=codex_home / "usage-logs" / "sessions")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("dashboard-data.json"))
    args = parser.parse_args()
    print(json.dumps({"sessions": write_snapshot(args.sessions, args.output)}, ensure_ascii=False))
