"""Read and write the local card-factory workflow API."""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import statistics
import uuid
from pathlib import Path
from typing import Any

from usage_database import utc_now


_ROUTING_HINTS = {
    "frontend": ("frontend", "front end", "interface", "ui", "dashboard", "css", "html", "javascript", "الواجهة", "الفرونت", "الصفحة", "التصميم"),
    "backend": ("backend", "back end", "django", "api", "server", "database", "sql", "migration", "باك اند", "الخلفية", "قاعدة البيانات", "الجدول", "api"),
    "svg": ("svg", "vector", "vectorization", "تنسيق svg", "متجه", "فيكتور"),
    "geometry": ("flux", "geometry", "path", "shape", "رسم هندسي", "مسار", "هندسة"),
    "architecture": ("architecture", "brainstorm", "planning", "strategy", "عصف ذهني", "بنية", "معمارية", "تخطيط", "استراتيجية"),
}


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^\w\u0600-\u06ff]+", " ", value.casefold()).split())


def _route_targets(connection: sqlite3.Connection, payload: dict[str, Any]) -> list[sqlite3.Row]:
    """Choose one active, dispatchable specialist using explicit charter capabilities."""
    actors = connection.execute("""SELECT a.actor_id,a.display_name,COALESCE(a.charter,'') charter
        FROM coordination_actors a JOIN coordination_actor_endpoints e ON e.actor_id=a.actor_id
        WHERE a.active=1 AND e.enabled=1 AND a.actor_id<>'owner' ORDER BY a.actor_id""").fetchall()
    if not actors:
        raise ValueError("لا توجد جلسة مختصة نشطة ومتصلة لاستلام البطاقة.")
    text = _normalize_text(" ".join(str(payload.get(k) or "") for k in ("title", "owner_request", "scope", "card_type_code")))
    hints = {name for name, terms in _ROUTING_HINTS.items() if any(_normalize_text(term) in text for term in terms)}
    if not hints:
        raise ValueError("لم تتضح تخصصات البطاقة من وصفها؛ أضف نوع المهمة أو كلمات تخصصية قبل إصدار الأمر.")
    scored = []
    for actor in actors:
        capabilities = [_normalize_text(row[0]) for row in connection.execute(
            "SELECT capability FROM coordination_actor_capabilities WHERE actor_id=?", (actor["actor_id"],))]
        charter = _normalize_text(actor["charter"])
        score = 0
        for hint in hints:
            terms = _ROUTING_HINTS[hint]
            if any(cap and (cap in terms or any(term in cap or cap in term for term in terms)) for cap in capabilities):
                score += 3
            elif any(_normalize_text(term) in charter for term in terms):
                score += 1
        if score:
            load = connection.execute("""SELECT COUNT(*) FROM coordination_cards
                WHERE assigned_actor_id=? AND current_status_code NOT IN ('completed','failed','archived')""",
                (actor["actor_id"],)).fetchone()[0]
            scored.append((score, load, actor["actor_id"], actor))
    if not scored:
        raise ValueError("لا توجد جلسة نشطة يتوافق ميثاقها وقدراتها مع نوع هذه البطاقة.")
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [scored[0][3]]


def _connect(path: Path, *, write: bool = False) -> sqlite3.Connection:
    if write:
        connection = sqlite3.connect(path, timeout=10)
    else:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _rows(connection: sqlite3.Connection, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, args).fetchall()]


def board(path: Path, *, status: str = "", actor_id: str = "", query: str = "") -> dict[str, Any]:
    connection = _connect(path)
    try:
        filters: list[str] = []
        args: list[Any] = []
        if status:
            filters.append("c.current_status_code=?")
            args.append(status)
        if actor_id:
            filters.append("c.assigned_actor_id=?")
            args.append(actor_id)
        if query:
            filters.append("(c.card_id LIKE ? OR c.title LIKE ? OR c.owner_request LIKE ? OR EXISTS ("
                           "SELECT 1 FROM coordination_delivery_attempts d WHERE d.card_id=c.card_id AND d.branch_name LIKE ?))")
            args.extend([f"%{query}%"] * 4)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        cards = _rows(connection, f"""
            SELECT c.card_id,c.title,c.owner_request,c.scope,c.current_status_code AS status_code,
                   s.display_name AS status_label,c.assigned_actor_id,a.display_name AS assigned_actor_name,
                   c.parent_card_id,c.card_type_code,c.priority_code,c.created_at,c.updated_at,
                   (SELECT COUNT(*) FROM coordination_card_criteria cr WHERE cr.card_id=c.card_id) AS criteria_total,
                   (SELECT COUNT(*) FROM coordination_card_criteria cr WHERE cr.card_id=c.card_id AND (
                      EXISTS (SELECT 1 FROM coordination_validation_results v
                        WHERE v.card_id=cr.card_id AND v.criterion=cr.criterion_code AND v.outcome='pass')
                      OR EXISTS (SELECT 1 FROM coordination_quality_checks qc
                        JOIN coordination_quality_runs qr ON qr.quality_run_id=qc.quality_run_id
                        WHERE qr.card_id=cr.card_id AND qc.check_code=cr.criterion_code AND qc.outcome='pass')
                   )) AS criteria_passed,
                   (SELECT d.branch_name FROM coordination_delivery_attempts d WHERE d.card_id=c.card_id
                    ORDER BY d.attempt_number DESC LIMIT 1) AS branch_name,
                   (SELECT d.commit_sha FROM coordination_delivery_attempts d WHERE d.card_id=c.card_id
                    ORDER BY d.attempt_number DESC LIMIT 1) AS commit_sha,
                   (SELECT q.outcome FROM coordination_quality_runs q WHERE q.card_id=c.card_id
                    ORDER BY q.finished_at DESC LIMIT 1) AS qa_outcome
            FROM coordination_cards c
            LEFT JOIN workflow_status_definitions s ON s.status_code=c.current_status_code AND s.version=c.current_status_version
            LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id
            {where}
            ORDER BY c.updated_at DESC,c.card_id
        """, tuple(args))
        sessions = _rows(connection, """SELECT actor_id,display_name,charter,active
            FROM coordination_actors WHERE active=1 AND actor_id<>'owner' ORDER BY display_name,actor_id""")
        return {"cards": cards, "sessions": sessions, "generated_at": utc_now()}
    finally:
        connection.close()


def metrics(path: Path) -> dict[str, Any]:
    connection = _connect(path)
    try:
        assignments = _rows(connection, """SELECT (julianday(x.assigned_at)-julianday(c.created_at))*86400 AS seconds
            FROM coordination_cards c JOIN coordination_assignments x ON x.card_id=c.card_id
            WHERE x.ended_at IS NULL AND x.assigned_at>=c.created_at""")
        cycles = _rows(connection, """SELECT (julianday(COALESCE(c.closed_at,c.updated_at))-julianday(c.created_at))*86400 AS seconds
            FROM coordination_cards c WHERE c.current_status_code IN ('completed','failed','archived')""")
        first_qa = _rows(connection, """SELECT q.outcome FROM coordination_quality_runs q
            WHERE q.quality_run_id=(SELECT q2.quality_run_id FROM coordination_quality_runs q2
                WHERE q2.card_id=q.card_id ORDER BY q2.started_at,q2.quality_run_id LIMIT 1)""")
        pushes = _rows(connection, """SELECT outcome,commit_sha,remote_commit_sha,verified_at
            FROM coordination_delivery_attempts WHERE outcome IN ('accepted','returned','blocked','failed')""")

        def median(rows: list[dict[str, Any]]) -> float | None:
            values = [float(row["seconds"]) for row in rows if row.get("seconds") is not None and float(row["seconds"]) >= 0]
            return statistics.median(values) if values else None

        return {"summary": {
            "median_assignment_seconds": median(assignments),
            "median_cycle_seconds": median(cycles),
            "first_pass_qa_rate": (sum(row["outcome"] == "pass" for row in first_qa) / len(first_qa)) if first_qa else None,
            "push_verified_rate": (sum(bool(row["verified_at"] and row["commit_sha"] and row["remote_commit_sha"]
                and row["commit_sha"].lower() == row["remote_commit_sha"].lower()) for row in pushes) / len(pushes)) if pushes else None,
        }, "generated_at": utc_now()}
    finally:
        connection.close()


def card_details(path: Path, card_id: str) -> dict[str, Any] | None:
    connection = _connect(path)
    try:
        card = connection.execute("""SELECT c.*,c.current_status_code AS status_code,s.display_name AS status_label,
            a.display_name AS assigned_actor_name FROM coordination_cards c
            LEFT JOIN workflow_status_definitions s ON s.status_code=c.current_status_code AND s.version=c.current_status_version
            LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id WHERE c.card_id=?""", (card_id,)).fetchone()
        if not card:
            return None
        result = {"card": dict(card)}
        result["criteria"] = _rows(connection, "SELECT * FROM coordination_card_criteria WHERE card_id=? ORDER BY sort_order,criterion_id", (card_id,))
        result["events"] = _rows(connection, """SELECT event_id,card_id,actor_id,event_type,details,recorded_at,stage_code,
            previous_status,next_status,reason_code,reason_resolution FROM coordination_events
            WHERE card_id=? AND sensitivity<>'confidential' ORDER BY event_id""", (card_id,))
        result["assignments"] = _rows(connection, "SELECT * FROM coordination_assignments WHERE card_id=? ORDER BY assigned_at,assignment_id", (card_id,))
        result["issues"] = _rows(connection, "SELECT * FROM coordination_issues WHERE card_id=? ORDER BY observed_at,issue_id", (card_id,))
        deliveries = _rows(connection, """SELECT * FROM coordination_delivery_attempts
            WHERE card_id=? ORDER BY attempt_number,attempt_id""", (card_id,))
        for delivery in deliveries:
            delivery["changed_paths"] = [row["path"] for row in _rows(connection,
                "SELECT path FROM coordination_delivery_paths WHERE attempt_id=? ORDER BY path", (delivery["attempt_id"],))]
        result["deliveries"] = deliveries
        result["validations"] = _rows(connection, """SELECT criterion,outcome,evidence_ref,recorded_at
            FROM coordination_validation_results WHERE card_id=? ORDER BY recorded_at,validation_id""", (card_id,))
        result["validations"].extend(_rows(connection, """SELECT c.check_code AS criterion,c.outcome,c.evidence_ref,
            r.finished_at AS recorded_at FROM coordination_quality_checks c
            JOIN coordination_quality_runs r ON r.quality_run_id=c.quality_run_id
            WHERE r.card_id=? ORDER BY r.finished_at,c.check_id""", (card_id,)))
        result["outbox"] = _rows(connection, "SELECT * FROM coordination_outbox WHERE card_id=? ORDER BY outbox_id", (card_id,))
        return result
    finally:
        connection.close()


def create_command(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title", "")).strip()
    owner_request = str(payload.get("owner_request", "")).strip()
    scope = str(payload.get("scope", "")).strip()
    key = str(payload.get("idempotency_key", "")).strip()
    if not title or not owner_request or not scope or not key:
        raise ValueError("العنوان وطلب المالك والنطاق ومفتاح الطلب مطلوبة.")
    if len(title) > 240 or len(owner_request) > 12000 or len(scope) > 12000 or len(key) > 200:
        raise ValueError("تجاوز أحد الحقول الحد المسموح به.")
    requested_targets = payload.get("target_actor_ids", [])
    if not isinstance(requested_targets, list) or len(requested_targets) > 20:
        raise ValueError("قائمة الجلسات المستهدفة غير صالحة.")
    if requested_targets:
        raise ValueError("يحدد المصنع الجلسة المختصة تلقائيًا؛ لا يقبل اختيار جهة الإسناد من المتصفح.")

    criteria = payload.get("criteria", [])
    if not isinstance(criteria, list) or len(criteria) > 50:
        raise ValueError("معايير الإنجاز غير صالحة.")
    criteria = [
        item for item in criteria
        if isinstance(item, dict)
        and str(item.get("title", "")).strip()
        and str(item.get("criterion_code", "")).strip().casefold() != "owner_review"
        and str(item.get("check_method", "")).strip().casefold() != "owner_acceptance"
    ]
    connection = _connect(path, write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        prior = connection.execute("SELECT root_card_id FROM coordination_command_receipts WHERE idempotency_key=?", (key,)).fetchone()
        if prior:
            children = [row["card_id"] for row in connection.execute(
                "SELECT card_id FROM coordination_command_cards WHERE idempotency_key=? AND role_code='session' ORDER BY card_id", (key,))]
            connection.commit()
            return {"created": False, "root_card_id": prior["root_card_id"], "child_card_ids": children,
                    "session_card_ids": children}

        targets = [row["actor_id"] for row in _route_targets(connection, payload)]

        now = utc_now()
        date = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
        root_id = f"CARD-{date}-{uuid.uuid4().hex[:8].upper()}"
        card_type = str(payload.get("card_type_code") or "general")[:80]
        priority = str(payload.get("priority_code") or "normal")[:40]

        def insert_card(card_id: str, status_code: str, *, parent: str | None = None,
                        target: str | None = None) -> int:
            legacy_status = status_code if status_code in {"draft", "accepted", "in_progress", "blocked", "delivered", "accepted_by_owner", "archived"} else "in_progress"
            connection.execute("""INSERT INTO coordination_cards
                (card_id,title,owner_request,scope,status,assigned_actor_id,coordinator_actor_id,created_at,updated_at,
                 current_status_code,current_status_version,parent_card_id,card_type_code,priority_code)
                VALUES(?,?,?,?,?,?,?,?,?, ?,1,?,?,?)""",
                (card_id,title,owner_request,scope,legacy_status,target,"owner",now,now,status_code,parent,card_type,priority))
            cursor = connection.execute("""INSERT INTO coordination_events
                (card_id,actor_id,event_type,details,recorded_at,stage_code,next_status,owner_actor_id,source_type,source_id,sensitivity)
                VALUES(?,'owner','card_created','أمر مالك مسجل من مصنع البطاقات',?,'intake',?,'owner','owner_command',?,'internal')""",
                (card_id,now,status_code,key))
            created_event_id = int(cursor.lastrowid)
            if target:
                assignment = connection.execute("""INSERT INTO coordination_events
                    (card_id,actor_id,event_type,details,recorded_at,stage_code,next_status,owner_actor_id,source_type,source_id,sensitivity)
                    VALUES(?,'owner','card_assigned','أُنشئت البطاقة وأُسندت إلى الجلسة',?,'assignment',?,'owner','assignment',?,'internal')""",
                    (card_id,now,status_code,target))
                connection.execute("""INSERT INTO coordination_assignments
                    (card_id,assigned_actor_id,assigned_by_actor_id,assigned_at,source_event_id)
                    VALUES(?,?,'owner',?,?)""", (card_id,target,now,assignment.lastrowid))
                return int(assignment.lastrowid)
            return created_event_id

        root_event = insert_card(root_id, "queued")
        connection.execute("INSERT INTO coordination_command_receipts(idempotency_key,root_card_id,created_at) VALUES(?,?,?)",
                           (key, root_id, now))
        connection.execute("INSERT INTO coordination_command_cards(idempotency_key,card_id,role_code) VALUES(?,?, 'root')",
                           (key, root_id))
        for criterion in criteria:
            connection.execute("""INSERT INTO coordination_card_criteria
                (card_id,criterion_code,title,description,required,check_method,sort_order,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (root_id, str(criterion.get("criterion_code") or uuid.uuid4().hex[:10]),
                str(criterion["title"]).strip()[:300], str(criterion.get("description") or "")[:2000],
                int(bool(criterion.get("required", True))), str(criterion.get("check_method") or "manual_evidence")[:100],
                int(criterion.get("sort_order", 0) or 0), now))

        children: list[str] = []
        for target in targets:
            child_id = f"{root_id}-{target.upper()}"
            assigned_event = insert_card(child_id, "assigned", parent=root_id, target=target)
            connection.execute("INSERT INTO coordination_command_cards(idempotency_key,card_id,role_code) VALUES(?,?, 'session')",
                (key, child_id))
            for criterion in criteria:
                connection.execute("""INSERT INTO coordination_card_criteria
                    (card_id,criterion_code,title,description,required,check_method,sort_order,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (child_id, str(criterion.get("criterion_code") or uuid.uuid4().hex[:10]),
                    str(criterion["title"]).strip()[:300], str(criterion.get("description") or "")[:2000],
                    int(bool(criterion.get("required", True))), str(criterion.get("check_method") or "manual_evidence")[:100],
                    int(criterion.get("sort_order", 0) or 0), now))
            assignment_event = connection.execute("SELECT event_id FROM coordination_events WHERE card_id=? AND event_type='card_assigned' ORDER BY event_id DESC LIMIT 1", (child_id,)).fetchone()
            if assignment_event:
                connection.execute("""INSERT INTO coordination_outbox
                    (card_id,event_id,target_actor_id,command_code,idempotency_key,state_code,available_at,created_at,updated_at)
                    VALUES(?,?,?,'card_assignment',?,'pending',?,?,?)""", (child_id, assignment_event["event_id"], target,
                    f"{key}:{target}", now, now, now))
            children.append(child_id)
        connection.commit()
        return {"created": True, "root_card_id": root_id, "child_card_ids": children,
                "session_card_ids": children, "event_id": root_event}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
