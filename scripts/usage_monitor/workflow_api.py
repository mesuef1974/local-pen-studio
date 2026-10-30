"""Read and write the local card-factory workflow API."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import statistics
import subprocess
import uuid
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from coordination_repository import _event
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


def _require_proposal_schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version < 16:
        raise RuntimeError("يتطلب مسار توصيات المتابعة مخطط قاعدة البيانات 16 وتحديث جامع القياس؛ لم تُجر أي كتابة.")


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
            d.assignment_scope,d.flow_responsibility,d.required_outputs,d.verification_guidance,
            CASE WHEN EXISTS (SELECT 1 FROM coordination_actor_endpoints e
                              WHERE e.actor_id=a.actor_id AND e.enabled=1) THEN 1 ELSE 0 END AS dispatchable
            FROM coordination_actors a JOIN coordination_actor_duties d ON d.actor_id=a.actor_id
            WHERE a.active=1 AND a.actor_id<>'owner'
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
        proposal_workflow_available = connection.execute("PRAGMA user_version").fetchone()[0] >= 16
        proposals = _rows(connection, """SELECT p.proposal_id,p.source_card_id,source.title AS source_card_title,
            p.proposed_by_actor_id,proposer.display_name AS proposed_by_name,p.title,p.owner_request,p.scope,
            p.rationale,p.suggested_assignee_actor_id,suggested.display_name AS suggested_assignee_name,
            p.status_code,p.decision_notes,p.decided_by_actor_id,p.decided_at,p.issued_root_card_id,
            p.created_at,p.updated_at,h.opinion AS source_opinion,h.recommendation AS session_recommendation
            FROM coordination_card_proposals p
            JOIN coordination_cards source ON source.card_id=p.source_card_id
            JOIN coordination_actors proposer ON proposer.actor_id=p.proposed_by_actor_id
            JOIN coordination_opinion_history h ON h.opinion_history_id=p.source_opinion_history_id
            LEFT JOIN coordination_actors suggested ON suggested.actor_id=p.suggested_assignee_actor_id
            ORDER BY CASE p.status_code WHEN 'pending_owner' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                     p.created_at DESC,p.proposal_id""") if proposal_workflow_available else []
        proposal_criteria = _rows(connection, """SELECT proposal_id,criterion_code,title,description,required,
            check_method,sort_order FROM coordination_card_proposal_criteria
            ORDER BY proposal_id,sort_order,proposal_criterion_id""") if proposal_workflow_available else []
        criteria_by_proposal: dict[str, list[dict[str, Any]]] = {}
        for criterion in proposal_criteria:
            criteria_by_proposal.setdefault(criterion["proposal_id"], []).append(criterion)
        for proposal in proposals:
            proposal["criteria"] = criteria_by_proposal.get(proposal["proposal_id"], [])
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
            "proposal_workflow_available": proposal_workflow_available,
            "card_proposals": proposals,
            "generated_at": utc_now(),
        }
    finally:
        connection.close()


def criterion_catalog(path: Path) -> dict[str, Any]:
    connection = _connect(path)
    try:
        return {"criteria": _rows(connection, """SELECT criterion_code,category_code,title,description,
            check_method,default_required,sort_order FROM workflow_criterion_catalog
            WHERE active=1 ORDER BY category_code,sort_order,criterion_code""")}
    finally:
        connection.close()


def submit_card_proposal(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a session opinion and its follow-up card proposal atomically."""
    actor_id = str(payload.get("actor_id", "")).strip()
    card_id = str(payload.get("source_card_id", "")).strip()
    title = str(payload.get("title", "")).strip()
    owner_request = str(payload.get("owner_request", "")).strip()
    scope = str(payload.get("scope", "")).strip()
    opinion = str(payload.get("opinion", "")).strip()
    recommendation = str(payload.get("recommendation", "")).strip()
    rationale = str(payload.get("rationale", "")).strip()
    key = str(payload.get("idempotency_key", "")).strip()
    suggested = str(payload.get("suggested_assignee_actor_id", "")).strip() or None
    if not all((actor_id, card_id, title, owner_request, scope, opinion, recommendation, rationale, key)):
        raise ValueError("أكمل الرأي والتوصية والبطاقة المقترحة ونطاقها وسببها.")
    if not all(_contains_arabic(value) for value in (title, owner_request, scope, opinion, recommendation, rationale)):
        raise ValueError("اكتب الرأي ومحتوى البطاقة المقترحة باللغة العربية.")
    if len(title) > 240 or len(owner_request) > 12000 or len(scope) > 12000 or len(opinion) > 8000 \
            or len(recommendation) > 8000 or len(rationale) > 4000 or len(key) > 200:
        raise ValueError("تجاوز أحد الحقول الحد المسموح به.")
    raw_criteria = payload.get("criteria", [])
    if not isinstance(raw_criteria, list) or len(raw_criteria) > 50:
        raise ValueError("معايير البطاقة المقترحة غير صالحة.")
    criteria: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_criteria):
        if not isinstance(item, dict):
            raise ValueError("صيغة أحد معايير البطاقة المقترحة غير صالحة.")
        criterion_title = str(item.get("title", "")).strip()
        if not criterion_title or not _contains_arabic(criterion_title):
            raise ValueError("يجب أن يكون لكل معيار عنوان عربي واضح.")
        code = str(item.get("criterion_code") or f"proposal_{uuid.uuid4().hex[:12]}").strip()
        if code in seen:
            raise ValueError("لا تكرر معيارًا في البطاقة المقترحة.")
        seen.add(code)
        criteria.append({"criterion_code": code[:120], "title": criterion_title[:300],
            "description": str(item.get("description") or "").strip()[:2000],
            "required": int(bool(item.get("required", True))),
            "check_method": str(item.get("check_method") or "manual_evidence").strip()[:100],
            "sort_order": index})
    request_hash = hashlib.sha256(json.dumps({
        "actor_id": actor_id, "source_card_id": card_id, "title": title,
        "owner_request": owner_request, "scope": scope, "opinion": opinion,
        "recommendation": recommendation, "rationale": rationale,
        "suggested_assignee_actor_id": suggested, "criteria": criteria,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    connection = _connect(path, write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _require_proposal_schema(connection)
        duplicate = connection.execute("SELECT proposal_id,request_hash_sha256 FROM coordination_card_proposals WHERE idempotency_key=?", (key,)).fetchone()
        if duplicate:
            if duplicate["request_hash_sha256"] != request_hash:
                raise ValueError("مفتاح منع التكرار مستخدم مع محتوى توصية مختلف.")
            connection.commit()
            return {"created": False, "proposal_id": duplicate["proposal_id"]}
        actor = connection.execute("SELECT actor_id FROM coordination_actors WHERE actor_id=? AND active=1 AND actor_id<>'owner'", (actor_id,)).fetchone()
        if not actor:
            raise ValueError("الجلسة المرسلة غير نشطة أو غير صالحة لتقديم توصية.")
        source = connection.execute("SELECT assigned_actor_id FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()
        if not source:
            raise KeyError("البطاقة الأصلية غير موجودة.")
        if source["assigned_actor_id"] != actor_id:
            raise ValueError("لا يمكن للجلسة اقتراح متابعة على بطاقة غير مسندة إليها.")
        if suggested:
            valid_suggestion = connection.execute("SELECT 1 FROM coordination_actors WHERE actor_id=? AND active=1 AND actor_id<>'owner'", (suggested,)).fetchone()
            if not valid_suggestion:
                raise ValueError("الجلسة المقترحة غير نشطة؛ يمكن تركها فارغة.")
        now = utc_now()
        event_cursor = connection.execute("""INSERT INTO coordination_events
            (card_id,actor_id,event_type,details,recorded_at,stage_code,source_type,source_id,sensitivity)
            VALUES(?,?, 'session_opinion_recorded', ?, ?, 'advisory', 'session_opinion', ?, 'internal')""",
            (card_id, actor_id, recommendation, now, key))
        event_id = int(event_cursor.lastrowid)
        connection.execute("""INSERT INTO coordination_opinions(card_id,actor_id,opinion,recommendation,recorded_at)
            VALUES(?,?,?,?,?) ON CONFLICT(card_id,actor_id) DO UPDATE SET opinion=excluded.opinion,
            recommendation=excluded.recommendation,recorded_at=excluded.recorded_at""",
            (card_id, actor_id, opinion, recommendation, now))
        opinion_id = connection.execute("SELECT opinion_id FROM coordination_opinions WHERE card_id=? AND actor_id=?", (card_id, actor_id)).fetchone()[0]
        history_cursor = connection.execute("""INSERT INTO coordination_opinion_history
            (card_id,actor_id,opinion,recommendation,recorded_at,source_event_id) VALUES(?,?,?,?,?,?)""",
            (card_id, actor_id, opinion, recommendation, now, event_id))
        history_id = int(history_cursor.lastrowid)
        proposal_id = f"PROP-{dt.datetime.now(dt.timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"
        proposal_event = connection.execute("""INSERT INTO coordination_events
            (card_id,actor_id,event_type,details,recorded_at,stage_code,source_type,source_id,sensitivity)
            VALUES(?,?, 'followup_card_proposed', ?, ?, 'advisory', 'card_proposal', ?, 'internal')""",
            (card_id, actor_id, rationale, now, proposal_id))
        connection.execute("""INSERT INTO coordination_card_proposals
            (proposal_id,source_card_id,source_opinion_history_id,proposed_by_actor_id,title,owner_request,scope,
             rationale,suggested_assignee_actor_id,status_code,source_event_id,idempotency_key,request_hash_sha256,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,'pending_owner',?,?,?,?,?)""",
            (proposal_id,card_id,history_id,actor_id,title,owner_request,scope,rationale,suggested,
             proposal_event.lastrowid,key,request_hash,now,now))
        for item in criteria:
            connection.execute("""INSERT INTO coordination_card_proposal_criteria
                (proposal_id,criterion_code,title,description,required,check_method,sort_order,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (proposal_id,item["criterion_code"],item["title"],item["description"],
                item["required"],item["check_method"],item["sort_order"],now))
        connection.commit()
        return {"created": True, "proposal_id": proposal_id, "opinion_id": opinion_id,
                "opinion_history_id": history_id, "source_event_id": int(proposal_event.lastrowid)}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def decide_card_proposal(path: Path, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = str(payload.get("actor_id", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    if actor_id != "owner":
        raise ValueError("قرار التوصية من صلاحية المالك فقط.")
    if decision not in {"approve", "reject"}:
        raise ValueError("اختر قبول التوصية أو رفضها.")
    if notes and not _contains_arabic(notes):
        raise ValueError("اكتب ملاحظة قرار المالك باللغة العربية.")
    if len(notes) > 4000:
        raise ValueError("تجاوزت ملاحظة القرار الحد المسموح به.")
    connection = _connect(path, write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _require_proposal_schema(connection)
        proposal = connection.execute("SELECT source_card_id,status_code,decided_by_actor_id,decision_notes FROM coordination_card_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if not proposal:
            raise KeyError("التوصية غير موجودة.")
        desired = "approved" if decision == "approve" else "rejected"
        if proposal["status_code"] == desired:
            connection.commit()
            return {"proposal_id": proposal_id, "status_code": desired, "updated": False}
        if proposal["status_code"] != "pending_owner":
            raise ValueError("لا يمكن تغيير توصية حُسم قرارها أو صدرت منها بطاقة.")
        now = utc_now()
        event = connection.execute("""INSERT INTO coordination_events
            (card_id,actor_id,event_type,details,recorded_at,stage_code,source_type,source_id,sensitivity)
            VALUES(?,'owner','owner_card_proposal_decided',?,?, 'owner_decision','card_proposal',?,'internal')""",
            (proposal["source_card_id"],notes or ("اعتمد المالك التوصية" if desired == "approved" else "رفض المالك التوصية"),now,proposal_id))
        axis = f"followup_proposal:{proposal_id}"
        connection.execute("INSERT INTO owner_decisions(card_id,axis,decision,notes,decided_at) VALUES(?,?,?,?,?)",
            (proposal["source_card_id"],axis,desired,notes,now))
        connection.execute("""INSERT INTO owner_decision_history
            (card_id,axis,decision,previous_decision,decided_by_actor_id,decided_at,source_event_id)
            VALUES(?,?,?,NULL,'owner',?,?)""", (proposal["source_card_id"],axis,desired,now,event.lastrowid))
        connection.execute("""UPDATE coordination_card_proposals SET status_code=?,decision_notes=?,
            decided_by_actor_id='owner',decided_at=?,decision_event_id=?,updated_at=? WHERE proposal_id=? AND status_code='pending_owner'""",
            (desired,notes,now,event.lastrowid,now,proposal_id))
        connection.commit()
        return {"proposal_id": proposal_id, "status_code": desired, "updated": True}
    except Exception:
        connection.rollback()
        raise
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
        duty = connection.execute("""SELECT assignment_scope,flow_responsibility,required_outputs,verification_guidance
            FROM coordination_actor_duties WHERE actor_id=?""", (card["assigned_actor_id"],)).fetchone()
        result["assigned_session_duties"] = dict(duty) if duty else None
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
        result["git_integrations"] = _rows(connection, """SELECT integration_id,attempt_id,repository,base_branch,
            head_branch,head_sha,state_code,pull_request_number,pull_request_url,base_sha,merge_sha,
            local_main_sha,remote_main_sha,last_error_code,created_at,updated_at
            FROM coordination_git_integrations WHERE card_id=? ORDER BY integration_id""", (card_id,))
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
        if not isinstance(item, dict):
            raise ValueError("صيغة أحد معايير الإنجاز غير صالحة.")
        if str(item.get("title", "")).strip() and not _contains_arabic(str(item["title"])):
            raise ValueError("اكتب عناوين معايير البطاقة باللغة العربية.")
        if str(item.get("description", "")).strip() and not _contains_arabic(str(item["description"])):
            raise ValueError("اكتب أوصاف معايير البطاقة باللغة العربية.")
    criteria = [
        item for item in criteria
        if (str(item.get("criterion_code", "")).strip() or str(item.get("title", "")).strip())
        and str(item.get("criterion_code", "")).strip().casefold() != "owner_review"
        and str(item.get("check_method", "")).strip().casefold() != "owner_acceptance"
    ]
    connection = _connect(path, write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        proposal_id = str(payload.get("proposal_id", "")).strip()
        approved_proposal = None
        if proposal_id:
            _require_proposal_schema(connection)
            approved_proposal = connection.execute("SELECT * FROM coordination_card_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if not approved_proposal:
                raise ValueError("اقتراح البطاقة غير موجود.")
            prior_for_proposal = connection.execute("SELECT root_card_id FROM coordination_command_receipts WHERE idempotency_key=?", (key,)).fetchone()
            if approved_proposal["status_code"] == "issued" and prior_for_proposal and \
                    prior_for_proposal["root_card_id"] == approved_proposal["issued_root_card_id"]:
                children = [row[0] for row in connection.execute(
                    "SELECT card_id FROM coordination_command_cards WHERE idempotency_key=? AND role_code='session' ORDER BY card_id", (key,))]
                connection.commit()
                return {"created": False, "root_card_id": prior_for_proposal["root_card_id"],
                        "child_card_ids": children, "session_card_ids": children, "proposal_id": proposal_id}
            if approved_proposal["status_code"] != "approved":
                raise ValueError("لا تصدر بطاقة من توصية قبل اعتماد المالك لها.")
        selected_actor = connection.execute("""SELECT a.actor_id FROM coordination_actors a
            WHERE a.actor_id=? AND a.active=1 AND a.actor_id<>'owner'
              AND EXISTS (SELECT 1 FROM coordination_actor_duties d WHERE d.actor_id=a.actor_id)
              AND EXISTS (SELECT 1 FROM coordination_actor_endpoints e
                          WHERE e.actor_id=a.actor_id AND e.enabled=1)""",
            (selected_actor_id,)).fetchone()
        if not selected_actor:
            raise ValueError("الجلسة المختارة غير نشطة أو غير مهيأة لاستلام البطاقة.")
        targets = [selected_actor["actor_id"]]

        catalog = {row["criterion_code"]: dict(row) for row in connection.execute(
            "SELECT criterion_code,title,description,check_method,default_required FROM workflow_criterion_catalog WHERE active=1")}
        normalized_criteria: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for index, item in enumerate(criteria):
            code = str(item.get("criterion_code") or "").strip()
            template = catalog.get(code)
            if template:
                if code in seen_codes:
                    raise ValueError("لا تكرر معيارًا من القائمة.")
                normalized_criteria.append({
                    "criterion_code": code, "title": template["title"], "description": template["description"],
                    "check_method": template["check_method"],
                    "required": int(bool(item.get("required", template["default_required"]))), "sort_order": index,
                })
                seen_codes.add(code)
                continue
            if code and not str(item.get("title") or "").strip():
                raise ValueError("أحد المعايير المختارة لم يعد موجودًا في القائمة؛ حدّث الصفحة وحاول مجددًا.")
            title_value = str(item.get("title") or "").strip()
            if not title_value:
                continue
            if len(title_value) > 300 or len(str(item.get("description") or "")) > 2000:
                raise ValueError("تجاوز اسم المعيار أو وصفه الحد المسموح به.")
            code = code or f"custom_{uuid.uuid4().hex[:12]}"
            if code in seen_codes:
                raise ValueError("لا تكرر رمز معيار يدوي.")
            normalized_criteria.append({
                "criterion_code": code, "title": title_value, "description": str(item.get("description") or "").strip(),
                "check_method": str(item.get("check_method") or "manual_evidence").strip()[:100],
                "required": int(bool(item.get("required", True))), "sort_order": index,
            })
            seen_codes.add(code)
        if not normalized_criteria:
            default = catalog.get("automated_delivery_qa")
            if not default:
                raise RuntimeError("كتالوج المعايير لا يحتوي معيار الجودة الافتراضي.")
            normalized_criteria.append({"criterion_code": "automated_delivery_qa", "title": default["title"],
                "description": default["description"], "check_method": default["check_method"],
                "required": 1, "sort_order": 0})

        prior = connection.execute("SELECT root_card_id FROM coordination_command_receipts WHERE idempotency_key=?", (key,)).fetchone()
        if prior:
            if approved_proposal and prior["root_card_id"] != approved_proposal["issued_root_card_id"]:
                raise ValueError("مفتاح التكرار مستخدم لأمر آخر؛ لم تُصدر بطاقة من التوصية.")
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
        if approved_proposal:
            if approved_proposal["issued_root_card_id"]:
                raise ValueError("صدرت بطاقة بالفعل من هذا الاقتراح.")
            connection.execute("""UPDATE coordination_card_proposals SET status_code='issued',issued_root_card_id=?,updated_at=?
                WHERE proposal_id=? AND status_code='approved' AND issued_root_card_id IS NULL""",
                (root_id,now,proposal_id))
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("تعذر قفل الاقتراح للإصدار؛ حدّث اللوحة وحاول مجددًا.")
            connection.execute("""INSERT INTO coordination_events
                (card_id,actor_id,event_type,details,recorded_at,stage_code,source_type,source_id,sensitivity)
                VALUES(?,'owner','followup_card_issued','أصدر المالك بطاقة المتابعة المعتمدة',?,'owner_decision','card_proposal',?,'internal')""",
                (approved_proposal["source_card_id"],now,proposal_id))
        for criterion in normalized_criteria:
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
            for criterion in normalized_criteria:
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
                "session_card_ids": children, "event_id": root_event,
                **({"proposal_id": proposal_id} if approved_proposal else {})}
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
                raise ValueError("إكمال بطاقة التنفيذ آلي بعد مراجعة GitHub ودمجها ومزامنة main؛ سجّل التسليم وفحوص الجودة في المصنع.")
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


def _assigned_card(connection: sqlite3.Connection, card_id: str, actor_id: str) -> sqlite3.Row:
    row = connection.execute("""SELECT c.assigned_actor_id,c.current_status_code,c.card_type_code,
        a.active FROM coordination_cards c LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id
        WHERE c.card_id=?""", (card_id,)).fetchone()
    if not row:
        raise KeyError("البطاقة غير موجودة.")
    if row["assigned_actor_id"] != actor_id or not row["active"]:
        raise ValueError("هذه الجلسة ليست الجهة المسندة النشطة لهذه البطاقة.")
    if not connection.execute("""SELECT 1 FROM coordination_assignments
        WHERE card_id=? AND assigned_actor_id=? AND ended_at IS NULL""", (card_id, actor_id)).fetchone():
        raise ValueError("لا يوجد إسناد نشط لهذه الجلسة على البطاقة.")
    return row


def _github_repository() -> str:
    try:
        completed = subprocess.run(["git", "-C", str(Path(__file__).resolve().parents[2]),
                                    "remote", "get-url", "origin"], capture_output=True,
                                   text=True, encoding="utf-8", timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("origin_remote_unavailable") from exc
    if completed.returncode:
        raise RuntimeError("origin_remote_unavailable")
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", completed.stdout.strip(), re.I)
    if not match:
        raise ValueError("المستودع البعيد ليس مستودع GitHub مدعومًا.")
    return match.group(1)


def submit_delivery(path: Path, card_id: str, body: dict[str, Any]) -> dict[str, Any]:
    actor_id = str(body.get("actor_id") or "").strip()
    branch = str(body.get("branch_name") or "").strip()
    remote = str(body.get("remote_name") or "origin").strip()
    commit = str(body.get("commit_sha") or "").strip().lower()
    summary = str(body.get("summary") or "").strip()
    changed_paths = body.get("changed_paths")
    if not actor_id or not branch or remote != "origin" or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("بيانات الفرع أو المستودع أو الالتزام غير صالحة.")
    if not summary or not _contains_arabic(summary) or len(summary) > 4000:
        raise ValueError("اكتب ملخص التسليم بالعربية وبحد أقصى 4000 حرف.")
    if not isinstance(changed_paths, list) or not changed_paths or len(changed_paths) > 500:
        raise ValueError("أرسل قائمة مسارات التغيير من الفرع.")
    normalized_paths: list[str] = []
    for value in changed_paths:
        if not isinstance(value, str) or not value or len(value) > 500 or "\\" in value or "\x00" in value:
            raise ValueError("أحد مسارات الملفات غير صالح.")
        item = PurePosixPath(value)
        if item.is_absolute() or not item.parts or item.as_posix() == "." or ".." in item.parts or ":" in value or "\n" in value:
            raise ValueError("يجب أن تكون المسارات نسبية وآمنة داخل المستودع.")
        normalized_paths.append(item.as_posix())
    normalized_paths = sorted(set(normalized_paths))
    repo_root = Path(__file__).resolve().parents[2]
    check_ref = subprocess.run(["git", "-C", str(repo_root), "check-ref-format", "--branch", branch],
                               capture_output=True, text=True, timeout=10, check=False)
    if check_ref.returncode or branch in {"main", "staging", "production"}:
        raise ValueError("يجب أن يكون التسليم على فرع مهمة غير محمي.")
    try:
        remote_check = subprocess.run(["git", "-C", str(repo_root), "ls-remote", remote,
                                       f"refs/heads/{branch}"], capture_output=True, text=True,
                                      encoding="utf-8", timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("remote_ref_unavailable") from exc
    remote_sha = remote_check.stdout.split()[0].lower() if remote_check.returncode == 0 and remote_check.stdout.split() else None
    verified = remote_sha == commit
    connection = _connect(path, write=True)
    try:
        card = _assigned_card(connection, card_id, actor_id)
        existing = connection.execute("""SELECT attempt_id,verified_at,remote_commit_sha FROM coordination_delivery_attempts
            WHERE card_id=? AND branch_name=? AND commit_sha=? ORDER BY attempt_number DESC LIMIT 1""",
            (card_id, branch, commit)).fetchone()
        if existing and existing["verified_at"] and existing["remote_commit_sha"] == commit and \
                card["current_status_code"] != "in_progress":
            return {"card_id": card_id, "attempt_id": existing["attempt_id"], "commit_sha": commit,
                    "remote_commit_sha": commit, "verified": True, "duplicate": True}
        if card["current_status_code"] != "in_progress":
            raise ValueError("يجب أن تكون البطاقة قيد التنفيذ قبل تسجيل التسليم.")
        with connection:
            attempt_number = connection.execute("SELECT COALESCE(MAX(attempt_number),0)+1 FROM coordination_delivery_attempts WHERE card_id=?", (card_id,)).fetchone()[0]
            now = utc_now()
            event_id = _event(connection, card_id, "delivery_attempt", actor_id=actor_id,
                stage_code="delivery", note=summary, source_type="delivery_attempt", source_id=str(attempt_number))
            cursor = connection.execute("""INSERT INTO coordination_delivery_attempts
                (card_id,attempt_number,submitted_by_actor_id,submitted_at,outcome,summary,source_event_id,
                 branch_name,remote_name,commit_sha,remote_commit_sha,verified_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (card_id, attempt_number, actor_id, now, "accepted" if verified else "failed", summary,
                 event_id, branch, remote, commit, remote_sha, now if verified else None))
            attempt_id = int(cursor.lastrowid)
            connection.executemany("INSERT INTO coordination_delivery_paths(attempt_id,path) VALUES(?,?)",
                ((attempt_id, item) for item in normalized_paths))
            _event(connection, card_id, "git_push", actor_id=actor_id, stage_code="git_delivery",
                source_type="git", source_id=commit, note="دفع موثق على origin" if verified else "لم يتطابق SHA البعيد مع الالتزام المرسل")
            connection.execute("""INSERT INTO coordination_git_events
                (card_id,remote_name,branch_name,commit_sha,action,outcome,recorded_at)
                VALUES(?,?,?,?,?,?,?)""", (card_id, remote, branch, commit, "push",
                "verified" if verified else "sha_mismatch", now))
            if verified:
                from coordination_repository import transition_card
                transition_card(connection, card_id, "delivered", actor_id=actor_id, stage_code="delivery",
                                source_type="session_delivery", source_id=str(attempt_id),
                                note="تأكد دفع الالتزام المطابق إلى origin")
        return {"card_id": card_id, "attempt_id": attempt_id, "commit_sha": commit,
                "remote_commit_sha": remote_sha, "verified": verified}
    finally:
        connection.close()


def submit_quality(path: Path, card_id: str, body: dict[str, Any]) -> dict[str, Any]:
    actor_id = str(body.get("actor_id") or "").strip()
    try:
        attempt_id = int(body.get("attempt_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("معرّف محاولة التسليم غير صالح.") from exc
    commit = str(body.get("commit_sha") or "").strip().lower()
    profile = str(body.get("profile_code") or "").strip()
    runner_name = str(body.get("runner_name") or "").strip()
    runner_version = str(body.get("runner_version") or "").strip()
    checks = body.get("checks")
    if not actor_id or not re.fullmatch(r"[0-9a-f]{40,64}", commit) or not profile or not runner_name or not runner_version:
        raise ValueError("بيانات تشغيل فحوص الجودة غير مكتملة.")
    if len(profile) > 100 or len(runner_name) > 160 or len(runner_version) > 100:
        raise ValueError("بيانات مشغل فحوص الجودة تجاوزت الحد.")
    if not isinstance(checks, list) or len(checks) > 200:
        raise ValueError("أرسل قائمة نتائج الفحوص بصيغة صحيحة.")
    connection = _connect(path, write=True)
    try:
        card = _assigned_card(connection, card_id, actor_id)
        delivery = connection.execute("""SELECT attempt_id,commit_sha,remote_commit_sha,verified_at,outcome,branch_name
            FROM coordination_delivery_attempts WHERE card_id=? AND attempt_id=?""", (card_id, attempt_id)).fetchone()
        if not delivery or delivery["outcome"] != "accepted" or not delivery["verified_at"] or \
                delivery["commit_sha"] != commit or delivery["remote_commit_sha"] != commit:
            raise ValueError("نتائج الجودة يجب أن ترتبط بالالتزام المدفوع والمتحقق منه نفسه.")
        existing_integration = connection.execute("""SELECT integration_id,state_code,pull_request_number
            FROM coordination_git_integrations WHERE attempt_id=?""", (attempt_id,)).fetchone()
        if existing_integration:
            return {"card_id": card_id, "attempt_id": attempt_id, "outcome": "pass",
                    "integration_queued": True, "integration_id": existing_integration["integration_id"],
                    "integration_state": existing_integration["state_code"], "duplicate": True}
        if card["current_status_code"] != "delivered":
            raise ValueError("لا تُسجل فحوص الجودة إلا بعد التحقق من الدفع.")
        repository = _github_repository()
        required = {row[0] for row in connection.execute("SELECT criterion_code FROM coordination_card_criteria WHERE card_id=? AND required=1", (card_id,))}
        clean_checks: list[dict[str, Any]] = []
        for item in checks:
            if not isinstance(item, dict):
                raise ValueError("تنسيق إحدى نتائج الفحص غير صالح.")
            code = str(item.get("check_code") or "").strip()
            outcome = str(item.get("outcome") or "").strip()
            evidence = str(item.get("evidence_ref") or "").strip()
            if not code or len(code) > 120 or outcome not in {"pass", "conditional", "fail", "skipped"} or len(evidence) > 2000:
                raise ValueError("رمز الفحص أو نتيجته أو مرجع دليله غير صالح.")
            duration = item.get("duration_ms")
            if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration < 0):
                raise ValueError("مدة فحص الجودة يجب أن تكون عددًا صحيحًا غير سالب.")
            clean_checks.append({"check_code": code, "outcome": outcome, "evidence_ref": evidence or None,
                                 "duration_ms": duration, "message_code": str(item.get("message_code") or "")[:100]})
        by_code = {item["check_code"]: item for item in clean_checks}
        passed_required = all(code in by_code and by_code[code]["outcome"] == "pass" and by_code[code]["evidence_ref"] for code in required)
        reported = str(body.get("outcome") or "").strip()
        has_failure = any(item["outcome"] == "fail" for item in clean_checks)
        outcome = "pass" if reported == "pass" and passed_required and not has_failure else "fail"
        now = utc_now()
        with connection:
            cursor = connection.execute("""INSERT INTO coordination_quality_runs
                (card_id,attempt_id,commit_sha,profile_code,runner_name,runner_version,outcome,started_at,finished_at,correlation_id)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (card_id, attempt_id, commit, profile, runner_name,
                runner_version, outcome, now, now, f"delivery-{attempt_id}"))
            run_id = int(cursor.lastrowid)
            for item in clean_checks:
                connection.execute("""INSERT INTO coordination_quality_checks
                    (quality_run_id,check_code,outcome,duration_ms,evidence_ref,message_code)
                    VALUES(?,?,?,?,?,?)""", (run_id, item["check_code"], item["outcome"],
                    item["duration_ms"], item["evidence_ref"], item["message_code"]))
            _event(connection, card_id, "quality_run_recorded", actor_id=actor_id,
                stage_code="quality", source_type="quality_run", source_id=str(run_id),
                note="اجتازت الفحوص المطلوبة؛ بانتظار فحوص GitHub والدمج" if outcome == "pass" else "فشلت بعض فحوص الجودة؛ أُعيدت البطاقة للتنفيذ")
            if outcome == "pass":
                from coordination_repository import transition_card
                transition_card(connection, card_id, "verifying", actor_id=actor_id, stage_code="quality",
                                source_type="quality_run", source_id=str(run_id),
                                note="اجتازت المعايير؛ انتقل التكامل الآلي لمراجعة GitHub ودمج main")
                connection.execute("""INSERT INTO coordination_git_integrations
                    (card_id,attempt_id,repository,base_branch,head_branch,head_sha,state_code,next_attempt_at,created_at,updated_at)
                    VALUES(?,?,?,'main',?,?,'pending',?,?,?)""",
                    (card_id, attempt_id, repository, delivery["branch_name"], commit, now, now, now))
            else:
                from coordination_repository import transition_card
                transition_card(connection, card_id, "returned", actor_id=actor_id, stage_code="quality",
                                reason_code="verification_failed", source_type="quality_run", source_id=str(run_id),
                                note="فشل فحص مطلوب؛ تُستكمل البطاقة وتُرسل محاولة جديدة")
        return {"card_id": card_id, "attempt_id": attempt_id, "quality_run_id": run_id,
                "outcome": outcome, "integration_queued": outcome == "pass"}
    finally:
        connection.close()
