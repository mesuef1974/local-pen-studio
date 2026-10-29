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


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^\w\u0600-\u06ff]+", " ", value.casefold()).split())


def _contains_arabic(value: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", value or ""))


def _derive_title(owner_request: str) -> str:
    for line in str(owner_request or "").splitlines():
        match = re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?العنوان(?:\*\*)?\s*[:：]\s*(?:\*\*)?(.+?)(?:\*\*)?\s*$", line)
        if match:
            title = re.sub(r"[*#\s]+$", "", match.group(1)).strip()
            if title:
                return title[:180]
    placeholders = {"نص المهمة لبطاقة التنفيذ", "نص المهمة", "بطاقة جديدة", "مهمة جديدة", "المهمة المطلوبة"}
    for line in str(owner_request or "").splitlines():
        candidate = re.sub(r"^\s*#+\s*|^\s*[-*]\s*|[*#]+\s*$", "", line).strip()
        if not candidate or _normalize_text(candidate) in placeholders:
            continue
        title = re.split(r"[.!?؟\n]", candidate, maxsplit=1)[0].strip()
        if title and _normalize_text(title) not in placeholders:
            return title[:180]
    return ""


def _display_title(title: str, owner_request: str) -> str:
    if _normalize_text(title) in {"نص المهمة لبطاقة التنفيذ", "نص المهمة", "بطاقة جديدة", "مهمة جديدة", "المهمة المطلوبة"}:
        return _derive_title(owner_request) or title
    return title


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
            filters.append("(c.assigned_actor_id=? OR EXISTS ("
                           "SELECT 1 FROM coordination_command_cards root "
                           "JOIN coordination_command_cards child ON child.idempotency_key=root.idempotency_key "
                           "AND child.role_code='session' JOIN coordination_cards execution ON execution.card_id=child.card_id "
                           "WHERE root.card_id=c.card_id AND root.role_code='root' "
                           "AND (?='owner' OR execution.assigned_actor_id=?)))")
            args.extend([actor_id, actor_id, actor_id])
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
        command_roots = {row[0] for row in connection.execute("""SELECT root.card_id
            FROM coordination_command_cards root JOIN coordination_command_cards child
              ON child.idempotency_key=root.idempotency_key AND child.role_code='session'
            WHERE root.role_code='root'""")}
        root_targets: dict[str, list[str]] = {}
        for target in connection.execute("""SELECT root.card_id,a.display_name
            FROM coordination_command_cards root
            JOIN coordination_command_cards child ON child.idempotency_key=root.idempotency_key AND child.role_code='session'
            JOIN coordination_cards execution ON execution.card_id=child.card_id
            LEFT JOIN coordination_actors a ON a.actor_id=execution.assigned_actor_id
            WHERE root.role_code='root' ORDER BY a.display_name"""):
            if target[1]:
                root_targets.setdefault(target[0], []).append(target[1])
        owner_cards = [dict(card, owner_command=card["card_id"] in command_roots,
                            owner_target_name="، ".join(root_targets.get(card["card_id"], [])))
                       for card in cards if card["card_id"] in command_roots or card["assigned_actor_id"] == "owner"]
        cards = [card for card in cards if card["card_id"] not in command_roots and card["assigned_actor_id"] != "owner"]
        for card in [*owner_cards, *cards]:
            card["display_title"] = _display_title(card["title"], card["owner_request"])
        sessions = _rows(connection, """SELECT a.actor_id,a.display_name,a.charter,a.active,
            CASE WHEN EXISTS (SELECT 1 FROM coordination_actor_endpoints e
                              WHERE e.actor_id=a.actor_id AND e.enabled=1) THEN 1 ELSE 0 END AS dispatchable
            FROM coordination_actors a WHERE a.active=1 AND a.actor_id<>'owner'
            ORDER BY a.display_name,a.actor_id""")
        completed_owner_commands = _rows(connection, """
            SELECT c.card_id,c.title,c.updated_at
            FROM coordination_command_receipts r
            JOIN coordination_cards c ON c.card_id=r.root_card_id
            WHERE c.current_status_code='completed'
            ORDER BY c.updated_at DESC,c.card_id
        """)
        completed_session_cards = _rows(connection, """SELECT c.card_id,c.title,c.assigned_actor_id,a.display_name AS assigned_actor_name
            FROM coordination_cards c LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id
            WHERE c.current_status_code='completed'
              AND NOT EXISTS (
                SELECT 1 FROM coordination_command_cards root
                WHERE root.card_id=c.card_id AND root.role_code='root'
                  AND EXISTS (SELECT 1 FROM coordination_command_cards child
                    WHERE child.idempotency_key=root.idempotency_key AND child.role_code='session')
              )
            ORDER BY a.active DESC,a.display_name,c.updated_at DESC,c.card_id""")
        cards_by_actor: dict[str, list[dict[str, Any]]] = {}
        for card in completed_session_cards:
            cards_by_actor.setdefault(card["assigned_actor_id"] or "", []).append(card)
        session_history_groups = [{"actor_id": session["actor_id"], "display_name": session["display_name"],
                                   "cards": cards_by_actor.get(session["actor_id"], [])}
                                  for session in sessions]
        status_groups = {code: _rows(connection, """SELECT c.card_id,c.title,c.assigned_actor_id,a.display_name AS assigned_actor_name
            FROM coordination_cards c LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id
            WHERE c.current_status_code=?
              AND NOT EXISTS (
                SELECT 1 FROM coordination_command_cards root
                WHERE root.card_id=c.card_id AND root.role_code='root'
                  AND EXISTS (SELECT 1 FROM coordination_command_cards child
                    WHERE child.idempotency_key=root.idempotency_key AND child.role_code='session')
              )
            ORDER BY a.active DESC,a.display_name,c.updated_at DESC,c.card_id""", (code,))
                        for code in ("failed", "blocked", "archived")}
        session_completions = _rows(connection, """
            SELECT a.actor_id,a.display_name,a.active,COUNT(c.card_id) AS completed_count
            FROM coordination_actors a
            LEFT JOIN coordination_cards c
              ON c.assigned_actor_id=a.actor_id AND c.current_status_code='completed'
            WHERE a.actor_id<>'owner'
              AND (a.active=1 OR c.card_id IS NOT NULL)
            GROUP BY a.actor_id,a.display_name,a.active
            ORDER BY a.active DESC,a.display_name,a.actor_id
        """)
        return {
            "cards": cards,
            "owner_cards": owner_cards,
            "sessions": sessions,
            "completion_summary": {
                "owner_commands_completed": len(completed_owner_commands),
                "completed_owner_commands": completed_owner_commands,
                "session_completions": session_completions,
                "session_cards_completed": sum(row["completed_count"] for row in session_completions),
            },
            "session_history_groups": session_history_groups,
            "status_groups": status_groups,
            "generated_at": utc_now(),
        }
    finally:
        connection.close()


def metrics(path: Path) -> dict[str, Any]:
    connection = _connect(path)
    try:
        command_roots = {row[0] for row in connection.execute("""SELECT root.card_id
            FROM coordination_command_cards root JOIN coordination_command_cards child
              ON child.idempotency_key=root.idempotency_key AND child.role_code='session'
            WHERE root.role_code='root'""")}
        cards = _rows(connection, "SELECT c.* FROM coordination_cards c ORDER BY c.updated_at DESC")
        cards = [card for card in cards if card["card_id"] not in command_roots]
        execution_ids = {card["card_id"] for card in cards}
        assignments = _rows(connection, """SELECT x.card_id,(julianday(x.assigned_at)-julianday(c.created_at))*86400 AS seconds
            FROM coordination_cards c JOIN coordination_assignments x ON x.card_id=c.card_id
            WHERE x.ended_at IS NULL AND x.assigned_at>=c.created_at""")
        assignments = [row for row in assignments if row["card_id"] in execution_ids]
        cycles = _rows(connection, """SELECT c.card_id,(julianday(COALESCE(c.closed_at,c.updated_at))-julianday(c.created_at))*86400 AS seconds
            FROM coordination_cards c WHERE c.current_status_code IN ('completed','failed','archived')""")
        cycles = [row for row in cycles if row["card_id"] in execution_ids]
        first_qa = _rows(connection, """SELECT q.card_id,q.outcome FROM coordination_quality_runs q
            WHERE q.quality_run_id=(SELECT q2.quality_run_id FROM coordination_quality_runs q2
                WHERE q2.card_id=q.card_id ORDER BY q2.started_at,q2.quality_run_id LIMIT 1)""")
        first_qa = [row for row in first_qa if row["card_id"] in execution_ids]
        pushes = _rows(connection, """SELECT card_id,outcome,commit_sha,remote_commit_sha,verified_at
            FROM coordination_delivery_attempts WHERE outcome IN ('accepted','returned','blocked','failed')""")
        pushes = [row for row in pushes if row["card_id"] in execution_ids]

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
        actor_names = {row["actor_id"]: row["display_name"] for row in connection.execute(
            "SELECT actor_id,display_name FROM coordination_actors")}
        card_data = dict(card)
        card_data["display_title"] = _display_title(card_data["title"], card_data["owner_request"])
        result = {"card": card_data}
        if card["parent_card_id"]:
            result["owner_command"] = _rows(connection, """SELECT card_id,title,owner_request,scope,created_at
                FROM coordination_cards WHERE card_id=?""", (card["parent_card_id"],))[0]
            result["owner_command"]["display_title"] = _display_title(
                result["owner_command"]["title"], result["owner_command"]["owner_request"])
        result["criteria"] = _rows(connection, "SELECT * FROM coordination_card_criteria WHERE card_id=? ORDER BY sort_order,criterion_id", (card_id,))
        result["events"] = _rows(connection, """SELECT event_id,card_id,actor_id,event_type,details,recorded_at,stage_code,
            previous_status,next_status,reason_code,reason_resolution FROM coordination_events
            WHERE card_id=? AND sensitivity<>'confidential' ORDER BY event_id""", (card_id,))
        for event in result["events"]:
            event["actor_name"] = actor_names.get(event.get("actor_id"), "")
            localized = connection.execute("""SELECT localized_text FROM workflow_text_localizations
                WHERE table_name='coordination_events' AND record_key=? AND field_name='details'""",
                (str(event["event_id"]),)).fetchone()
            if localized:
                event["localized_details"] = localized["localized_text"]
        result["assignments"] = _rows(connection, "SELECT * FROM coordination_assignments WHERE card_id=? ORDER BY assigned_at,assignment_id", (card_id,))
        for assignment in result["assignments"]:
            assignment["assigned_actor_name"] = actor_names.get(assignment.get("assigned_actor_id"), "")
            assignment["assigned_by_actor_name"] = actor_names.get(assignment.get("assigned_by_actor_id"), "")
        result["issues"] = _rows(connection, "SELECT * FROM coordination_issues WHERE card_id=? ORDER BY observed_at,issue_id", (card_id,))
        for issue in result["issues"]:
            localized = connection.execute("""SELECT localized_text FROM workflow_text_localizations
                WHERE table_name='coordination_issues' AND record_key=? AND field_name='impact_summary'""",
                (str(issue["issue_id"]),)).fetchone()
            if localized:
                issue["localized_impact_summary"] = localized["localized_text"]
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
        for item in result["outbox"]:
            item["target_actor_name"] = actor_names.get(item.get("target_actor_id"), "جلسة سابقة")
        return result
    finally:
        connection.close()


def create_command(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    owner_request = str(payload.get("owner_request", "")).strip()
    title = str(payload.get("title", "")).strip()
    if not title and owner_request:
        title = _derive_title(owner_request)
    scope = str(payload.get("scope", "")).strip() or owner_request
    key = str(payload.get("idempotency_key", "")).strip()
    if not owner_request or not key:
        raise ValueError("اكتب وصف المهمة أولًا.")
    if not all(_contains_arabic(value) for value in (owner_request, title, scope)):
        raise ValueError("اكتب عنوان البطاقة ومحتواها باللغة العربية.")
    if len(title) > 240 or len(owner_request) > 12000 or len(scope) > 12000 or len(key) > 200:
        raise ValueError("تجاوز أحد الحقول الحد المسموح به.")
    requested_targets = payload.get("target_actor_ids")
    if not isinstance(requested_targets, list) or len(requested_targets) != 1:
        raise ValueError("اختر جلسة واحدة من قائمة أمر المالك.")
    selected_actor_id = str(requested_targets[0] or "").strip()
    if not selected_actor_id or len(selected_actor_id) > 120:
        raise ValueError("اختيار الجلسة غير صالح.")

    criteria = payload.get("criteria", [])
    if not isinstance(criteria, list) or len(criteria) > 50:
        raise ValueError("معايير الإنجاز غير صالحة.")
    for item in criteria:
        if isinstance(item, dict) and str(item.get("title", "")).strip() and not _contains_arabic(str(item["title"])):
            raise ValueError("اكتب عناوين معايير البطاقة باللغة العربية.")
        if isinstance(item, dict) and str(item.get("description", "")).strip() and not _contains_arabic(str(item["description"])):
            raise ValueError("اكتب أوصاف معايير البطاقة باللغة العربية.")
    criteria = [
        item for item in criteria
        if isinstance(item, dict)
        and str(item.get("title", "")).strip()
        and str(item.get("criterion_code", "")).strip().casefold() != "owner_review"
        and str(item.get("check_method", "")).strip().casefold() != "owner_acceptance"
    ]
    if not criteria:
        criteria = [{"criterion_code": "automated_delivery_qa", "title": "التحقق الآلي من الإنجاز",
                     "description": "تشغيل الفحوص المناسبة وتسجيل النتيجة مع البطاقة.",
                     "required": True, "check_method": "automated_quality_gate"}]
    connection = _connect(path, write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        selected_actor = connection.execute("""SELECT a.actor_id FROM coordination_actors a
            WHERE a.actor_id=? AND a.active=1 AND a.actor_id<>'owner'
              AND EXISTS (SELECT 1 FROM coordination_actor_endpoints e
                          WHERE e.actor_id=a.actor_id AND e.enabled=1)""",
            (selected_actor_id,)).fetchone()
        if not selected_actor:
            raise ValueError("الجلسة المختارة غير نشطة أو غير مهيأة لاستلام البطاقة.")
        targets = [selected_actor["actor_id"]]

        prior = connection.execute("SELECT root_card_id FROM coordination_command_receipts WHERE idempotency_key=?", (key,)).fetchone()
        if prior:
            children = [row["card_id"] for row in connection.execute(
                "SELECT card_id FROM coordination_command_cards WHERE idempotency_key=? AND role_code='session' ORDER BY card_id", (key,))]
            connection.commit()
            return {"created": False, "root_card_id": prior["root_card_id"], "child_card_ids": children,
                    "session_card_ids": children}

        now = utc_now()
        date = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
        root_id = f"CARD-{date}-{uuid.uuid4().hex[:8].upper()}"
        command_text = _normalize_text(" ".join((title, owner_request, scope)))
        review_terms = ("review", "مراجعة", "تدقيق", "تقييم")
        implementation_terms = ("implement", "fix", "build", "edit", "نفذ", "نفّذ", "اصلح", "أصلح", "عدّل", "عدل", "أضف", "اضف", "برمج")
        inferred_type = "review" if any(_normalize_text(term) in command_text for term in review_terms) and not any(
            _normalize_text(term) in command_text for term in implementation_terms) else "implementation"
        card_type = inferred_type
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
                    VALUES(?,'owner','card_assigned','حدد المالك الجلسة في أمر المالك وأُسندت إليها بطاقة التنفيذ',?,'assignment',?,'owner','assignment',?,'internal')""",
                    (card_id,now,status_code,target))
                connection.execute("""INSERT INTO coordination_assignments
                    (card_id,assigned_actor_id,assigned_by_actor_id,assigned_at,source_event_id)
                    VALUES(?,?,'owner',?,?)""", (card_id,target,now,assignment.lastrowid))
                return int(assignment.lastrowid)
            return created_event_id

        root_event = insert_card(root_id, "assigned" if targets else "queued")
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


def transition_assigned_card(path: Path, card_id: str, actor_id: str,
                             status_code: str, summary: str = "") -> dict[str, Any]:
    """Record lifecycle updates only from the active session assigned to the card."""
    from coordination_repository import record_issue, transition_card

    summary = str(summary or "").strip()
    if len(summary) > 4000:
        raise ValueError("ملخص النتيجة أطول من الحد المسموح.")
    if summary and not _contains_arabic(summary):
        raise ValueError("اكتب ملخص التقدم والتسليم باللغة العربية.")
    if status_code not in {"in_progress", "blocked", "delivered", "returned", "completed"}:
        raise ValueError("حالة الجلسة المطلوبة غير مدعومة.")
    connection = _connect(path, write=True)
    try:
        card = connection.execute("""SELECT c.assigned_actor_id,c.current_status_code,c.card_type_code,
            c.title,c.owner_request,c.scope,a.active FROM coordination_cards c
            LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id
            WHERE c.card_id=?""", (card_id,)).fetchone()
        if not card:
            raise KeyError("البطاقة غير موجودة.")
        if card["assigned_actor_id"] != actor_id or not card["active"]:
            raise ValueError("هذه الجلسة ليست الجهة المسندة النشطة لهذه البطاقة.")
        current = card["current_status_code"]
        if current == status_code:
            return {"card_id": card_id, "status_code": current, "updated": False}
        active_assignment = connection.execute("""SELECT 1 FROM coordination_assignments
            WHERE card_id=? AND assigned_actor_id=? AND ended_at IS NULL LIMIT 1""", (card_id, actor_id)).fetchone()
        if not active_assignment:
            raise ValueError("لا يوجد إسناد نشط لهذه الجلسة على البطاقة.")

        if status_code == "in_progress":
            if current not in {"assigned", "returned"}:
                raise ValueError("لا يمكن بدء التنفيذ من الحالة الحالية.")
            transition_card(connection, card_id, status_code, actor_id=actor_id, stage_code="execution",
                            note=summary or "بدأت الجلسة تنفيذ البطاقة", source_type="session_lifecycle")
        elif status_code == "blocked":
            if not summary:
                raise ValueError("اكتب سبب التعذر حتى يُسجل العائق.")
            if current not in {"assigned", "in_progress"}:
                raise ValueError("لا يمكن تسجيل التعذر من الحالة الحالية.")
            issue_id = record_issue(connection, card_id, stage_code="execution", cause_code="session_blocked",
                                    cause_resolution="unresolved", impact_summary=summary, actor_id=actor_id)
            transition_card(connection, card_id, status_code, actor_id=actor_id, stage_code="execution",
                            reason_code="session_unavailable", note=summary, source_type="session_lifecycle",
                            source_id=str(issue_id))
        elif status_code == "delivered":
            delivery = connection.execute("""SELECT commit_sha,remote_commit_sha,verified_at,outcome
                FROM coordination_delivery_attempts WHERE card_id=? ORDER BY attempt_number DESC LIMIT 1""", (card_id,)).fetchone()
            if not delivery or not delivery["verified_at"] or not delivery["commit_sha"] or \
                    delivery["commit_sha"].lower() != (delivery["remote_commit_sha"] or "").lower() or delivery["outcome"] != "accepted":
                raise ValueError("لا يُسجل التسليم قبل التحقق من تطابق Commit مع origin.")
            if current not in {"in_progress", "blocked"}:
                raise ValueError("لا يمكن تسجيل التسليم من الحالة الحالية.")
            transition_card(connection, card_id, "delivered", actor_id=actor_id, stage_code="delivery",
                            note=summary or "تحقق دفع Commit على origin", source_type="session_lifecycle")
        elif status_code == "returned":
            latest_quality = connection.execute("SELECT outcome FROM coordination_quality_runs WHERE card_id=? ORDER BY quality_run_id DESC LIMIT 1", (card_id,)).fetchone()
            if current not in {"delivered", "verifying"} or not summary or (latest_quality and latest_quality["outcome"] == "pass"):
                raise ValueError("إعادة البطاقة تتطلب نتيجة فحص وسببًا واضحًا.")
            transition_card(connection, card_id, "returned", actor_id=actor_id, stage_code="quality",
                            note=summary, reason_code="verification_failed", source_type="session_lifecycle")
        else:
            text = _normalize_text(" ".join((card["title"], card["owner_request"], card["scope"])))
            review_terms = ("review", "مراجعة", "تدقيق", "تقييم")
            implementation_terms = ("implement", "fix", "build", "edit", "نفذ", "نفّذ", "اصلح", "أصلح", "عدّل", "عدل", "أضف", "اضف", "برمج")
            is_review = card["card_type_code"] == "review" or (
                any(_normalize_text(term) in text for term in review_terms)
                and not any(_normalize_text(term) in text for term in implementation_terms))
            if is_review:
                if current not in {"assigned", "in_progress"} or len(summary) < 20:
                    raise ValueError("إكمال بطاقة المراجعة يتطلب تقريرًا مختصرًا وحالة تنفيذ نشطة.")
                evidence = connection.execute("""SELECT 1 FROM coordination_quality_runs WHERE card_id=?
                    UNION SELECT 1 FROM coordination_validation_results WHERE card_id=?
                    UNION SELECT 1 FROM coordination_events WHERE card_id=? AND event_type='review_finding'
                    LIMIT 1""", (card_id, card_id, card_id)).fetchone()
                if not evidence:
                    raise ValueError("سجل نتيجة المراجعة أو الفحوص في المصنع قبل إكمال البطاقة.")
                transition_card(connection, card_id, "completed", actor_id=actor_id, stage_code="verification",
                                note=summary, source_type="review_report")
            else:
                if current in {"in_progress", "blocked"}:
                    delivery = connection.execute("""SELECT commit_sha,remote_commit_sha,verified_at,outcome
                        FROM coordination_delivery_attempts WHERE card_id=? ORDER BY attempt_number DESC LIMIT 1""", (card_id,)).fetchone()
                    if not delivery or not delivery["verified_at"] or not delivery["commit_sha"] or \
                            delivery["commit_sha"].lower() != (delivery["remote_commit_sha"] or "").lower() or delivery["outcome"] != "accepted":
                        raise ValueError("لا تُغلق بطاقة التنفيذ قبل إثبات الدفع إلى origin.")
                    transition_card(connection, card_id, "delivered", actor_id=actor_id, stage_code="delivery",
                                    note="تسليم موثق على origin", source_type="session_lifecycle")
                    current = "delivered"
                if current == "delivered":
                    transition_card(connection, card_id, "verifying", actor_id=actor_id, stage_code="quality",
                                    note="بدأ التحقق من فحوص الجودة", source_type="session_lifecycle")
                    current = "verifying"
                if current != "verifying":
                    raise ValueError("لا تُغلق بطاقة التنفيذ إلا من مرحلة فحوص الجودة.")
                if connection.execute("SELECT 1 FROM coordination_issues WHERE card_id=? AND resolved_at IS NULL LIMIT 1", (card_id,)).fetchone():
                    raise ValueError("لا تُغلق البطاقة مع وجود عائق غير محلول.")
                quality = connection.execute("""SELECT quality_run_id,outcome FROM coordination_quality_runs
                    WHERE card_id=? ORDER BY quality_run_id DESC LIMIT 1""", (card_id,)).fetchone()
                if not quality or quality["outcome"] != "pass":
                    raise ValueError("فحوص الجودة لم تجتز بعد؛ سجّل الحالة returned لإعادتها للتنفيذ.")
                required = {row[0] for row in connection.execute(
                    "SELECT criterion_code FROM coordination_card_criteria WHERE card_id=? AND required=1", (card_id,))}
                passed = {row[0] for row in connection.execute("""SELECT check_code FROM coordination_quality_checks
                    WHERE quality_run_id=? AND outcome='pass' UNION SELECT criterion FROM coordination_validation_results
                    WHERE card_id=? AND outcome='pass'""", (quality["quality_run_id"], card_id))}
                if not required.issubset(passed):
                    raise ValueError("بعض معايير الإنجاز المطلوبة لم تجتز.")
                if len(summary) < 20:
                    raise ValueError("أضف خلاصة التسليم قبل إكمال بطاقة التنفيذ.")
                transition_card(connection, card_id, "completed", actor_id=actor_id, stage_code="quality",
                                note=summary, source_type="session_lifecycle")
            parent = connection.execute("SELECT parent_card_id FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()[0]
            if parent:
                remaining = connection.execute("SELECT 1 FROM coordination_cards WHERE parent_card_id=? AND current_status_code<>'completed' LIMIT 1", (parent,)).fetchone()
                parent_status = connection.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?", (parent,)).fetchone()[0]
                if not remaining and parent_status in {"queued", "assigned", "in_progress"}:
                    transition_card(connection, parent, "completed", actor_id=actor_id, stage_code="rollup",
                                    note="اكتملت جميع بطاقات الجلسات التابعة", source_type="session_rollup")
        return {"card_id": card_id, "status_code": status_code, "updated": True}
    finally:
        connection.close()
