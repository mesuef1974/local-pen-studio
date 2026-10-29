"""Dispatch committed card assignments to their registered local Codex sessions."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from usage_database import connect, utc_now

CODEX_DEFAULT_DATABASE = Path(__import__("os").environ.get("CODEX_HOME", Path.home() / ".codex")) / "usage-logs" / "usage.sqlite3"
MAX_ATTEMPTS = 5
LEASE_SECONDS = 120


def register_endpoint(database: Path, actor_id: str, thread_id: str, capabilities: tuple[str, ...] = ()) -> None:
    try:
        canonical = str(uuid.UUID(thread_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("thread_id must be a Codex session UUID") from exc
    db = connect(database)
    try:
        with db:
            actor = db.execute("SELECT active FROM coordination_actors WHERE actor_id=? AND actor_id<>'owner'", (actor_id,)).fetchone()
            if not actor or not actor["active"]:
                raise ValueError("actor_id must identify an active specialist session")
            now = utc_now()
            db.execute("""INSERT INTO coordination_actor_endpoints(actor_id,provider_code,thread_id,enabled,created_at,updated_at)
                VALUES(?,'codex_cli',?,1,?,?)
                ON CONFLICT(actor_id) DO UPDATE SET provider_code='codex_cli',thread_id=excluded.thread_id,
                enabled=1,updated_at=excluded.updated_at""", (actor_id, canonical, now, now))
            normalized={" ".join(re.sub(r"[^\w\u0600-\u06ff]+", " ", term.casefold()).split()) for term in capabilities}
            normalized.discard("")
            db.execute("DELETE FROM coordination_actor_capabilities WHERE actor_id=?",(actor_id,))
            db.executemany("INSERT INTO coordination_actor_capabilities(actor_id,capability) VALUES(?,?)",
                           ((actor_id,term) for term in sorted(normalized)))
    finally:
        db.close()


def _message(row: sqlite3.Row, criteria: list[sqlite3.Row]) -> str:
    base_url = os.environ.get("WORKFLOW_BASE_URL", "http://127.0.0.1:8769").rstrip("/")
    origin = base_url
    lifecycle = f"{base_url}/api/workflow/cards/{row['card_id']}/lifecycle"
    actor_id = row["target_actor_id"]
    lines = [
        f"تكليف بطاقة منسق — {row['card_id']}",
        f"العنوان: {row['title']}",
        "طلب المالك:", row["owner_request"],
        "النطاق:", row["scope"],
        "معايير الإكمال:",
    ]
    lines.extend(f"- [{'مطلوب' if c['required'] else 'اختياري'}] {c['title']} ({c['criterion_code']}; {c['check_method']})" for c in criteria)
    headers = f'$headers = @{{ Origin = "{origin}"; "X-Workflow-Request" = "1" }}'
    lines.extend([
        "هذه البطاقة صادرة بأمر المالك. استلمها ونفذها ضمن النطاق، ولا ترفضها.",
        "عند بدء العمل حدّث الحالة فورًا إلى قيد التنفيذ بهذا الطلب المحلي:",
        headers,
        f'$body = @{{ actor_id = "{actor_id}"; status_code = "in_progress" }} | ConvertTo-Json -Compress',
        f'Invoke-RestMethod -Uri "{lifecycle}" -Method Post -Headers $headers -ContentType "application/json" -Body $body',
    ])
    if row["card_type_code"] == "review":
        lines.extend([
            "هذه بطاقة مراجعة وتقرير؛ لا تنفذ إصلاحات خارج النطاق ولا يلزم دفع تغييرات كود.",
            "بعد تسجيل نتائج المراجعة والفحوص في المصنع، أغلق بطاقة المراجعة بالتقرير النهائي عبر status_code=completed وsummary يوضح النتيجة.",
            f'$body = @{{ actor_id = "{actor_id}"; status_code = "completed"; summary = "اكتب هنا خلاصة المراجعة ونتيجتها" }} | ConvertTo-Json -Compress',
            f'Invoke-RestMethod -Uri "{lifecycle}" -Method Post -Headers $headers -ContentType "application/json" -Body $body',
        ])
    else:
        lines.extend([
            "إذا تعذر التنفيذ، سجّل سببًا واضحًا كعائق عبر الطلب المحلي:",
            f'$body = @{{ actor_id = "{actor_id}"; status_code = "blocked"; summary = "اكتب هنا سبب التعذر" }} | ConvertTo-Json -Compress',
            f'Invoke-RestMethod -Uri "{lifecycle}" -Method Post -Headers $headers -ContentType "application/json" -Body $body',
            "بعد الإنجاز ادفع التغييرات، وسجّل التسليم وفحوص الجودة وأدلتها في المصنع. بعد اجتياز المعايير المطلوبة حدّث الحالة إلى مكتملة:",
            f'$body = @{{ actor_id = "{actor_id}"; status_code = "completed"; summary = "اكتب خلاصة الدفع ونتيجة الفحوص" }} | ConvertTo-Json -Compress',
            f'Invoke-RestMethod -Uri "{lifecycle}" -Method Post -Headers $headers -ContentType "application/json" -Body $body',
            "إذا فشلت الفحوص بعد الدفع، أعد البطاقة للتنفيذ بدل تركها في حالة مسندة:",
            f'$body = @{{ actor_id = "{actor_id}"; status_code = "returned"; summary = "اكتب الفحوص التي فشلت والعمل المطلوب" }} | ConvertTo-Json -Compress',
            f'Invoke-RestMethod -Uri "{lifecycle}" -Method Post -Headers $headers -ContentType "application/json" -Body $body',
        ])
    lines.append(f"مرجع منع التكرار: {row['idempotency_key']}")
    return "\n".join(lines)


def dispatch_one(database: Path, *, codex_executable: str | None = None,
                 runner: Callable = subprocess.run, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    now_text = now.isoformat()
    db = connect(database)
    try:
        with db:
            # An expired claim has an uncertain result: the CLI may have queued the prompt
            # just before the worker stopped. Quarantine it instead of risking a duplicate.
            db.execute("""UPDATE coordination_outbox SET state_code='dead_letter',last_error_code='dispatch_result_unknown',
                locked_until=NULL,updated_at=? WHERE state_code='processing' AND locked_until<?""", (now_text, now_text))
            row = db.execute("""SELECT o.outbox_id,o.card_id,o.target_actor_id,o.idempotency_key,
                c.title,c.owner_request,c.scope,c.card_type_code,e.thread_id
                FROM coordination_outbox o JOIN coordination_cards c ON c.card_id=o.card_id
                JOIN coordination_actor_endpoints e ON e.actor_id=o.target_actor_id AND e.enabled=1
                WHERE o.state_code IN ('pending','retry') AND o.available_at<=?
                ORDER BY o.available_at,o.outbox_id LIMIT 1""", (now_text,)).fetchone()
            if not row:
                return None
            outbox_id = row["outbox_id"]
            db.execute("""UPDATE coordination_outbox SET state_code='processing',attempt_count=attempt_count+1,
                locked_until=?,updated_at=? WHERE outbox_id=?""",
                ((now + timedelta(seconds=LEASE_SECONDS)).isoformat(), now_text, outbox_id))
            criteria = db.execute("""SELECT criterion_code,title,required,check_method
                FROM coordination_card_criteria WHERE card_id=? ORDER BY sort_order,criterion_id""",
                (row["card_id"],)).fetchall()
            prompt = _message(row, criteria)
            attempt_count = db.execute("SELECT attempt_count FROM coordination_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()[0]
            thread_id = row["thread_id"]
    finally:
        db.close()


    executable = codex_executable or shutil.which("codex")
    if not executable:
        result = {"returncode": 127, "error": "codex_cli_unavailable"}
    else:
        try:
            completed = runner([executable, "queue", "--thread", thread_id, "--message", prompt],
                               capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            result = {"returncode": int(completed.returncode), "error": None if completed.returncode == 0 else f"codex_exit_{completed.returncode}"}
        except subprocess.TimeoutExpired:
            result = {"returncode": 124, "error": "codex_queue_timeout_unknown"}
        except OSError:
            result = {"returncode": 126, "error": "codex_queue_launch_failed"}

    db = connect(database)
    try:
        with db:
            if result["returncode"] == 0:
                db.execute("""UPDATE coordination_outbox SET state_code='sent',sent_at=?,locked_until=NULL,
                    last_error_code=NULL,updated_at=? WHERE outbox_id=? AND state_code='processing'""",
                    (utc_now(), utc_now(), outbox_id))
                from coordination_repository import _event
                _event(db, row["card_id"], "card_queued_to_session", stage_code="assignment",
                       source_type="outbox", source_id=row["idempotency_key"],
                       note="Codex CLI accepted the assignment for the registered session")
            else:
                state = "dead_letter" if attempt_count >= MAX_ATTEMPTS or result["error"] == "codex_queue_timeout_unknown" else "retry"
                backoff = min(3600, 15 * (2 ** max(0, attempt_count - 1)))
                available = (now + timedelta(seconds=backoff)).isoformat()
                db.execute("""UPDATE coordination_outbox SET state_code=?,available_at=?,locked_until=NULL,
                    last_error_code=?,updated_at=? WHERE outbox_id=? AND state_code='processing'""",
                    (state, available, result["error"], utc_now(), outbox_id))
        return {"outbox_id": outbox_id, "state_code": "sent" if result["returncode"] == 0 else state,
                "target_actor_id": row["target_actor_id"], "thread_id": thread_id,
                "attempt_count": attempt_count, "error_code": result["error"]}
    finally:
        db.close()


def dispatch_loop(database: Path, stop_event, *, interval_seconds: float = 5) -> None:
    """Poll the durable outbox while the local dashboard service is running."""
    while not stop_event.is_set():
        try:
            result = dispatch_one(database)
            if result is not None:
                stop_event.wait(1)
            else:
                stop_event.wait(interval_seconds)
        except (OSError, RuntimeError, sqlite3.Error):
            stop_event.wait(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=CODEX_DEFAULT_DATABASE)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register", help="Map a workflow actor to an existing Codex session")
    register.add_argument("--actor-id", required=True)
    register.add_argument("--thread-id", required=True)
    register.add_argument("--capability", action="append", default=[])
    sub.add_parser("dispatch-once", help="Send one ready assignment through Codex CLI")
    args = parser.parse_args()
    if args.command == "register":
        register_endpoint(args.database, args.actor_id, args.thread_id, tuple(args.capability))
        print(json.dumps({"registered": True, "actor_id": args.actor_id}, ensure_ascii=False))
    else:
        result = dispatch_one(args.database)
        print(json.dumps(result or {"dispatched": False, "reason": "no_ready_outbox_items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
