"""Transactional write operations for structured owner-card workflow records."""

from __future__ import annotations

import re
import sqlite3

from usage_database import utc_now


def _require_arabic(value: str | None, field: str, *, optional: bool = False) -> None:
    text = str(value or "").strip()
    if (text or not optional) and not re.search(r"[\u0600-\u06ff]", text):
        raise ValueError(f"اكتب {field} باللغة العربية.")


LEGACY_STATUS = {
    "draft", "accepted", "in_progress", "blocked", "delivered", "accepted_by_owner", "archived",
}
COARSE_STATUS = {
    "needs_clarification": "in_progress",
    "reassignment_requested": "in_progress",
    "awaiting_owner": "in_progress",
    "verifying": "delivered",
    "completed": "accepted_by_owner",
    "failed": "blocked",
}


def upsert_actor(connection: sqlite3.Connection, actor_id: str, display_name: str,
                 charter: str | None = None) -> None:
    with connection:
        connection.execute(
            """INSERT INTO coordination_actors(actor_id,display_name,charter) VALUES(?,?,?)
            ON CONFLICT(actor_id) DO UPDATE SET display_name=excluded.display_name,
            charter=COALESCE(excluded.charter,coordination_actors.charter)""",
            (actor_id, display_name, charter),
        )


def _event(connection: sqlite3.Connection, card_id: str, event_type: str, *,
           actor_id: str | None = None, owner_actor_id: str | None = None,
           stage_code: str | None = None, previous_status: str | None = None,
           next_status: str | None = None, reason_code: str | None = None,
           reason_resolution: str | None = None, note: str = "", source_type: str | None = None,
           source_id: str | None = None, related_event_id: int | None = None,
           correlation_id: str | None = None, codex_session_id: str | None = None,
           sensitivity: str = "internal",
           definition_version: int = 1, recorded_at: str | None = None) -> int:
    cursor = connection.execute(
        """INSERT INTO coordination_events(
        card_id,actor_id,event_type,details,recorded_at,stage_code,previous_status,next_status,
        owner_actor_id,reason_code,reason_resolution,source_type,source_id,related_event_id,
        correlation_id,codex_session_id,sensitivity,definition_version)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (card_id, actor_id, event_type, note, recorded_at or utc_now(), stage_code, previous_status,
         next_status, owner_actor_id, reason_code, reason_resolution, source_type, source_id,
         related_event_id, correlation_id, codex_session_id, sensitivity, definition_version),
    )
    return int(cursor.lastrowid)


def create_card(connection: sqlite3.Connection, *, card_id: str, title: str, owner_request: str,
                scope: str, status_code: str = "draft", assigned_actor_id: str | None = None,
                coordinator_actor_id: str | None = None, owner_actor_id: str | None = None,
                source_type: str = "owner_card", source_id: str | None = None) -> int:
    _require_arabic(title, "عنوان البطاقة")
    _require_arabic(owner_request, "طلب المالك")
    _require_arabic(scope, "نطاق البطاقة")
    now = utc_now()
    legacy = status_code if status_code in LEGACY_STATUS else COARSE_STATUS.get(status_code, "in_progress")
    with connection:
        connection.execute(
            """INSERT INTO coordination_cards(
            card_id,title,owner_request,scope,status,assigned_actor_id,coordinator_actor_id,created_at,updated_at,
            current_status_code,current_status_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (card_id, title, owner_request, scope, legacy, assigned_actor_id, coordinator_actor_id,
             now, now, status_code, 1),
        )
        event_id = _event(connection, card_id, "card_created", actor_id=coordinator_actor_id,
                          owner_actor_id=owner_actor_id, stage_code="intake", next_status=status_code,
                          source_type=source_type, source_id=source_id, recorded_at=now)
        if assigned_actor_id:
            assignment_event = _event(connection, card_id, "card_assigned", actor_id=coordinator_actor_id,
                                      owner_actor_id=owner_actor_id, stage_code="assignment",
                                      source_type="assignment", source_id=assigned_actor_id, recorded_at=now)
            connection.execute(
                """INSERT INTO coordination_assignments
                (card_id,assigned_actor_id,assigned_by_actor_id,assigned_at,source_event_id)
                VALUES(?,?,?,?,?)""",
                (card_id, assigned_actor_id, coordinator_actor_id, now, assignment_event),
            )
    return event_id


def transition_card(connection: sqlite3.Connection, card_id: str, next_status: str, *,
                    actor_id: str | None, owner_actor_id: str | None = None,
                    stage_code: str, reason_code: str | None = None,
                    reason_resolution: str | None = None, note: str = "",
                    related_event_id: int | None = None, source_type: str | None = None,
                    source_id: str | None = None) -> int:
    with connection:
        card = connection.execute(
            "SELECT current_status_code,current_status_version FROM coordination_cards WHERE card_id=?",
            (card_id,),
        ).fetchone()
        if not card:
            raise KeyError(f"Unknown coordination card: {card_id}")
        status = connection.execute(
            "SELECT version FROM workflow_status_definitions WHERE status_code=? AND retired_at IS NULL "
            "ORDER BY version DESC LIMIT 1", (next_status,),
        ).fetchone()
        if not status:
            raise ValueError(f"Unknown or retired workflow status: {next_status}")
        previous = card["current_status_code"]
        event_id = _event(connection, card_id, "status_transition", actor_id=actor_id,
                          owner_actor_id=owner_actor_id, stage_code=stage_code,
                          previous_status=previous, next_status=next_status,
                          reason_code=reason_code, reason_resolution=reason_resolution,
                          note=note, related_event_id=related_event_id,
                          source_type=source_type, source_id=source_id)
        legacy = next_status if next_status in LEGACY_STATUS else COARSE_STATUS.get(next_status, "in_progress")
        transitioned_at = utc_now()
        connection.execute(
            """UPDATE coordination_cards SET current_status_code=?,current_status_version=?,status=?,updated_at=?
            WHERE card_id=?""",
            (next_status, status["version"], legacy, transitioned_at, card_id),
        )
        if next_status in {"completed", "failed", "archived"}:
            connection.execute(
                "UPDATE coordination_assignments SET ended_at=? WHERE card_id=? AND ended_at IS NULL",
                (transitioned_at, card_id),
            )
    return event_id


def assign_card(connection: sqlite3.Connection, card_id: str, assigned_actor_id: str, *,
                assigned_by_actor_id: str | None, owner_actor_id: str | None = None,
                reason_code: str | None = None, source_event_id: int | None = None) -> int:
    now = utc_now()
    with connection:
        card = connection.execute("SELECT card_id FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()
        if not card:
            raise KeyError(f"Unknown coordination card: {card_id}")
        active = connection.execute(
            "SELECT assignment_id,assigned_actor_id FROM coordination_assignments WHERE card_id=? AND ended_at IS NULL",
            (card_id,),
        ).fetchone()
        event_id = _event(connection, card_id, "card_reassigned" if active else "card_assigned",
                          actor_id=assigned_by_actor_id, owner_actor_id=owner_actor_id,
                          stage_code="assignment", reason_code=reason_code,
                          source_type="assignment", source_id=assigned_actor_id,
                          related_event_id=source_event_id, recorded_at=now)
        if active:
            connection.execute("UPDATE coordination_assignments SET ended_at=? WHERE assignment_id=?",
                               (now, active["assignment_id"]))
        connection.execute(
            """INSERT INTO coordination_assignments
            (card_id,assigned_actor_id,assigned_by_actor_id,reason_code,assigned_at,source_event_id)
            VALUES(?,?,?,?,?,?)""",
            (card_id, assigned_actor_id, assigned_by_actor_id, reason_code, now, event_id),
        )
        connection.execute("UPDATE coordination_cards SET assigned_actor_id=?,updated_at=? WHERE card_id=?",
                           (assigned_actor_id, now, card_id))
    return event_id


def record_opinion(connection: sqlite3.Connection, card_id: str, actor_id: str, opinion: str,
                   recommendation: str | None = None) -> int:
    _require_arabic(opinion, "رأي الجلسة")
    _require_arabic(recommendation, "التوصية", optional=True)
    now = utc_now()
    with connection:
        event_id = _event(connection, card_id, "session_opinion_recorded", actor_id=actor_id,
                          stage_code="advisory", source_type="session_opinion", note="رأي استشاري مسجل")
        connection.execute(
            """INSERT INTO coordination_opinions(card_id,actor_id,opinion,recommendation,recorded_at)
            VALUES(?,?,?,?,?) ON CONFLICT(card_id,actor_id) DO UPDATE SET
            opinion=excluded.opinion,recommendation=excluded.recommendation,recorded_at=excluded.recorded_at""",
            (card_id, actor_id, opinion, recommendation, now),
        )
        connection.execute(
            """INSERT INTO coordination_opinion_history
            (card_id,actor_id,opinion,recommendation,recorded_at,source_event_id) VALUES(?,?,?,?,?,?)""",
            (card_id, actor_id, opinion, recommendation, now, event_id),
        )
    return event_id


def record_owner_decision(connection: sqlite3.Connection, card_id: str, axis: str, decision: str, *,
                          owner_actor_id: str, notes: str | None = None) -> int:
    _require_arabic(notes, "ملاحظات قرار المالك", optional=True)
    now = utc_now()
    with connection:
        previous = connection.execute("SELECT decision FROM owner_decisions WHERE card_id=? AND axis=?",
                                      (card_id, axis)).fetchone()
        event_id = _event(connection, card_id, "owner_decision_recorded", actor_id=owner_actor_id,
                          owner_actor_id=owner_actor_id, stage_code="owner_decision",
                          note=notes or f"قرار مسجل للمحور: {axis}",
                          source_type="owner_decision", source_id=axis,
                          sensitivity="confidential")
        connection.execute(
            """INSERT INTO owner_decisions(card_id,axis,decision,notes,decided_at) VALUES(?,?,?,?,?)
            ON CONFLICT(card_id,axis) DO UPDATE SET decision=excluded.decision,
            notes=excluded.notes,decided_at=excluded.decided_at""",
            (card_id, axis, decision, notes, now),
        )
        connection.execute(
            """INSERT INTO owner_decision_history
            (card_id,axis,decision,previous_decision,decided_by_actor_id,decided_at,source_event_id)
            VALUES(?,?,?,?,?,?,?)""",
            (card_id, axis, decision, previous["decision"] if previous else None,
             owner_actor_id, now, event_id),
        )
    return event_id


def record_issue(connection: sqlite3.Connection, card_id: str, *, stage_code: str,
                 cause_resolution: str, impact_summary: str, cause_code: str | None = None,
                 actor_id: str | None = None) -> int:
    _require_arabic(impact_summary, "وصف العائق")
    if cause_resolution not in {"confirmed", "unresolved"}:
        raise ValueError("cause_resolution must be confirmed or unresolved")
    now = utc_now()
    with connection:
        event_id = _event(connection, card_id, "blocker_observed", actor_id=actor_id,
                          stage_code=stage_code, reason_code=cause_code,
                          reason_resolution=cause_resolution, note=impact_summary,
                          source_type="workflow_issue")
        cursor = connection.execute(
            """INSERT INTO coordination_issues
            (card_id,event_id,stage_code,cause_code,cause_resolution,impact_summary,observed_at)
            VALUES(?,?,?,?,?,?,?)""",
            (card_id, event_id, stage_code, cause_code, cause_resolution, impact_summary, now),
        )
    return int(cursor.lastrowid)


def record_delivery_attempt(connection: sqlite3.Connection, card_id: str, *,
                            submitted_by_actor_id: str | None, outcome: str = "submitted",
                            summary: str = "") -> int:
    _require_arabic(summary, "ملخص التسليم", optional=True)
    with connection:
        attempt = connection.execute(
            "SELECT COALESCE(MAX(attempt_number),0)+1 FROM coordination_delivery_attempts WHERE card_id=?",
            (card_id,),
        ).fetchone()[0]
        now = utc_now()
        event_id = _event(connection, card_id, "delivery_attempt", actor_id=submitted_by_actor_id,
                          stage_code="delivery", note=summary, source_type="delivery_attempt",
                          source_id=str(attempt))
        cursor = connection.execute(
            """INSERT INTO coordination_delivery_attempts
            (card_id,attempt_number,submitted_by_actor_id,submitted_at,outcome,summary,source_event_id)
            VALUES(?,?,?,?,?,?,?)""",
            (card_id, attempt, submitted_by_actor_id, now, outcome, summary, event_id),
        )
    return int(cursor.lastrowid)


def record_validation(connection: sqlite3.Connection, card_id: str, *, outcome: str,
                      criterion: str, evidence_ref: str | None = None,
                      validator_actor_id: str | None = None, attempt_id: int | None = None) -> int:
    now = utc_now()
    with connection:
        event_id = _event(connection, card_id, "validation_result", actor_id=validator_actor_id,
                          stage_code="verification", note=f"{criterion}: {outcome}",
                          source_type="validation", source_id=evidence_ref)
        cursor = connection.execute(
            """INSERT INTO coordination_validation_results
            (card_id,attempt_id,validator_actor_id,outcome,criterion,evidence_ref,recorded_at,source_event_id)
            VALUES(?,?,?,?,?,?,?,?)""",
            (card_id, attempt_id, validator_actor_id, outcome, criterion, evidence_ref, now, event_id),
        )
    return int(cursor.lastrowid)


def record_deliverable(connection: sqlite3.Connection, card_id: str, path: str, *,
                       kind: str, checksum_sha256: str | None = None,
                       actor_id: str | None = None) -> int:
    now = utc_now()
    with connection:
        _event(connection, card_id, "deliverable_registered", actor_id=actor_id,
                          stage_code="delivery", source_type="file", source_id=path,
                          note=f"مخرج مسجل من النوع {kind}")
        connection.execute(
            """INSERT INTO coordination_deliverables
            (card_id,path,kind,checksum_sha256,created_at) VALUES(?,?,?,?,?)
            ON CONFLICT(card_id,path) DO UPDATE SET kind=excluded.kind,
            checksum_sha256=COALESCE(excluded.checksum_sha256,coordination_deliverables.checksum_sha256)""",
            (card_id, path, kind, checksum_sha256, now),
        )
        cursor = connection.execute("SELECT deliverable_id FROM coordination_deliverables WHERE card_id=? AND path=?",
                                    (card_id, path))
    return int(cursor.fetchone()[0])


def record_git_event(connection: sqlite3.Connection, card_id: str, *, action: str,
                     branch_name: str, outcome: str, remote_name: str | None = None,
                     commit_sha: str | None = None, actor_id: str | None = None) -> int:
    now = utc_now()
    with connection:
        event_id = _event(connection, card_id, "git_" + action, actor_id=actor_id,
                          stage_code="git_delivery", source_type="git", source_id=commit_sha,
                          note=outcome)
        cursor = connection.execute(
            """INSERT INTO coordination_git_events
            (card_id,remote_name,branch_name,commit_sha,action,outcome,recorded_at)
            VALUES(?,?,?,?,?,?,?)""",
            (card_id, remote_name, branch_name, commit_sha, action, outcome, now),
        )
    return int(cursor.lastrowid or event_id)
