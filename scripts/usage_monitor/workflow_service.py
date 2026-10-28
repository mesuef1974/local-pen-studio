"""SQLite-backed card factory read models and commands."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from datetime import datetime
import uuid
from statistics import median
from typing import Any

from coordination_repository import create_card, transition_card, record_issue, record_delivery_attempt
from usage_database import utc_now

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def _card_rows(db: sqlite3.Connection, where: str = "", params: tuple = ()) -> list[dict]:
    sql = """SELECT c.*, s.display_name AS status_label, a.display_name AS assigned_actor_name,
        co.display_name AS coordinator_name,
        (SELECT COUNT(*) FROM coordination_card_criteria x WHERE x.card_id=c.card_id) criteria_total,
        (SELECT COUNT(DISTINCT passed_code) FROM (
            SELECT v.criterion AS passed_code FROM coordination_validation_results v WHERE v.card_id=c.card_id AND v.outcome='pass'
            UNION SELECT k.check_code FROM coordination_quality_checks k JOIN coordination_quality_runs q ON q.quality_run_id=k.quality_run_id WHERE q.card_id=c.card_id AND k.outcome='pass'
        )) criteria_passed,
        (SELECT COUNT(*) FROM coordination_card_criteria x WHERE x.card_id=c.card_id AND x.required=0) optional_count,
        (SELECT COUNT(*) FROM coordination_issues i WHERE i.card_id=c.card_id AND i.resolved_at IS NULL) open_issue_count,
        (SELECT MAX(recorded_at) FROM coordination_events e WHERE e.card_id=c.card_id) latest_event_at,
        (SELECT event_type FROM coordination_events e WHERE e.card_id=c.card_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1) latest_event_type,
        (SELECT branch_name FROM coordination_delivery_attempts d WHERE d.card_id=c.card_id ORDER BY attempt_number DESC LIMIT 1) branch_name,
        (SELECT COALESCE(remote_commit_sha,commit_sha) FROM coordination_delivery_attempts d WHERE d.card_id=c.card_id ORDER BY attempt_number DESC LIMIT 1) commit_sha,
        (SELECT outcome FROM coordination_delivery_attempts d WHERE d.card_id=c.card_id ORDER BY attempt_number DESC LIMIT 1) delivery_outcome,
        (SELECT outcome FROM coordination_quality_runs q WHERE q.card_id=c.card_id ORDER BY finished_at DESC,quality_run_id DESC LIMIT 1) qa_outcome
        FROM coordination_cards c
        LEFT JOIN workflow_status_definitions s ON s.status_code=c.current_status_code AND s.version=c.current_status_version
        LEFT JOIN coordination_actors a ON a.actor_id=c.assigned_actor_id
        LEFT JOIN coordination_actors co ON co.actor_id=c.coordinator_actor_id """
    return [dict(r) for r in db.execute(sql + where, params).fetchall()]


def board(db: sqlite3.Connection, *, status: str = "", actor_id: str = "", q: str = "") -> dict:
    sessions = [dict(r) for r in db.execute("SELECT actor_id,display_name,charter,active FROM coordination_actors WHERE active=1 AND actor_id<>'owner' ORDER BY display_name COLLATE NOCASE")]
    cards = _card_rows(db, "ORDER BY c.updated_at DESC,c.card_id")
    if status: cards = [c for c in cards if c["current_status_code"] == status]
    if actor_id: cards = [c for c in cards if c["assigned_actor_id"] == actor_id]
    if q:
        term = q.casefold(); cards = [c for c in cards if term in " ".join(str(c.get(k) or "") for k in ("card_id","title","owner_request","scope","branch_name")).casefold()]
    for card in cards: card["status_code"] = card["current_status_code"]
    keys = ("queued", "assigned", "in_progress", "blocked", "delivered", "verifying", "completed")
    counts = {k: sum(c["current_status_code"] == k for c in _card_rows(db)) for k in keys}
    return {"version": 1, "generated_at": utc_now(), "counts": counts, "sessions": sessions, "cards": cards}


def detail(db: sqlite3.Connection, card_id: str) -> dict:
    rows = _card_rows(db, "WHERE c.card_id=?", (card_id,))
    if not rows: raise KeyError(card_id)
    specs = {
        "criteria": "SELECT criterion_id,criterion_code,title,description,required,check_method,sort_order FROM coordination_card_criteria WHERE card_id=? ORDER BY sort_order,criterion_id",
        "events": "SELECT event_id,event_type,actor_id,stage_code,previous_status,next_status,details,recorded_at FROM coordination_events WHERE card_id=? ORDER BY recorded_at,event_id",
        "assignments": "SELECT assignment_id,assigned_actor_id,assigned_by_actor_id,reason_code,assigned_at,ended_at FROM coordination_assignments WHERE card_id=? ORDER BY assigned_at,assignment_id",
        "issues": "SELECT issue_id,stage_code,cause_code,cause_resolution,impact_summary,observed_at,resolved_at,resolved_by_actor_id FROM coordination_issues WHERE card_id=? ORDER BY observed_at,issue_id",
        "deliveries": "SELECT attempt_id,attempt_number,submitted_by_actor_id,submitted_at,outcome,summary,branch_name,remote_name,commit_sha,remote_commit_sha,verified_at FROM coordination_delivery_attempts WHERE card_id=? ORDER BY attempt_number",
        "validations": "SELECT validation_id,attempt_id,validator_actor_id,outcome,criterion,evidence_ref,recorded_at FROM coordination_validation_results WHERE card_id=? ORDER BY recorded_at,validation_id",
        "outbox": "SELECT outbox_id,target_actor_id,command_code,state_code,attempt_count,available_at,sent_at,last_error_code FROM coordination_outbox WHERE card_id=? ORDER BY outbox_id",
    }
    out = {k: [dict(r) for r in db.execute(sql, (card_id,))] for k, sql in specs.items()}
    return {"card": rows[0], **out}


def metrics(db: sqlite3.Connection) -> dict:
    cards = _card_rows(db)
    durations = []; assignment_durations=[]
    for c in cards:
        if c["started_at"] and c["closed_at"]:
            try:
                durations.append((datetime.fromisoformat(c["closed_at"]) - datetime.fromisoformat(c["started_at"])).total_seconds())
            except ValueError: pass
        if c["created_at"]:
            first=db.execute("SELECT assigned_at FROM coordination_assignments WHERE card_id=? ORDER BY assigned_at LIMIT 1",(c["card_id"],)).fetchone()
            if first:
                try: assignment_durations.append((datetime.fromisoformat(first[0])-datetime.fromisoformat(c["created_at"])).total_seconds())
                except ValueError: pass
    runs = db.execute("SELECT card_id,outcome FROM coordination_quality_runs ORDER BY card_id,quality_run_id").fetchall()
    deliveries = db.execute("SELECT remote_commit_sha,commit_sha FROM coordination_delivery_attempts WHERE commit_sha IS NOT NULL").fetchall()
    by_session = []
    for a in db.execute("SELECT actor_id,display_name FROM coordination_actors WHERE active=1 AND actor_id<>'owner' ORDER BY display_name"):
        own = [c for c in cards if c["assigned_actor_id"] == a["actor_id"]]
        own_cycles=[]
        for c in own:
            if c["started_at"] and c["closed_at"]:
                try: own_cycles.append((datetime.fromisoformat(c["closed_at"])-datetime.fromisoformat(c["started_at"])).total_seconds())
                except ValueError: pass
        own_runs={}
        for r in runs:
            if any(c["card_id"]==r["card_id"] for c in own): own_runs.setdefault(r["card_id"],[]).append(r["outcome"])
        by_session.append({"actor_id": a["actor_id"], "display_name": a["display_name"],
            "active_cards": sum(not c["current_status_code"] in ("completed","failed","archived") for c in own),
            "completed_cards": sum(c["current_status_code"] == "completed" for c in own),
            "blocked_cards": sum(c["current_status_code"] == "blocked" for c in own),
            "median_cycle_seconds": median(own_cycles) if own_cycles else None,
            "first_pass_qa_rate": sum(outcomes[0]=="pass" for outcomes in own_runs.values())/len(own_runs) if own_runs else None})
    first_by_card={}
    for r in runs: first_by_card.setdefault(r["card_id"],r["outcome"])
    return {"version": 1,"generated_at": utc_now(),"summary": {
        "total": len(cards), "queued": sum(c["current_status_code"]=="queued" for c in cards),
        "in_progress": sum(c["current_status_code"]=="in_progress" for c in cards),
        "blocked": sum(c["current_status_code"]=="blocked" for c in cards),
        "verifying": sum(c["current_status_code"]=="verifying" for c in cards),
        "completed": sum(c["current_status_code"]=="completed" for c in cards),
        "median_assignment_seconds": median(assignment_durations) if assignment_durations else None,"median_cycle_seconds": median(durations) if durations else None,
        "first_pass_qa_rate": sum(outcome=="pass" for outcome in first_by_card.values())/len(first_by_card) if first_by_card else None,
        "push_verified_rate": sum(bool(r["remote_commit_sha"] and r["remote_commit_sha"]==r["commit_sha"]) for r in deliveries)/len(deliveries) if deliveries else None},"by_session": by_session}


def create_command(db: sqlite3.Connection, body: dict) -> tuple[dict, bool]:
    key = body["idempotency_key"]
    prior = db.execute("SELECT root_card_id FROM coordination_command_receipts WHERE idempotency_key=?", (key,)).fetchone()
    if prior:
        ids = [r[0] for r in db.execute("SELECT card_id FROM coordination_command_cards WHERE idempotency_key=? ORDER BY role_code DESC,card_id", (key,))]
        return {"root_card_id": prior[0],"child_card_ids": [x for x in ids if x != prior[0]],"created": False}, False
    root = str(uuid.uuid4()); now = utc_now(); targets = list(dict.fromkeys(body.get("target_actor_ids", [])))
    if not targets:
        actors = db.execute("SELECT actor_id,display_name,COALESCE(charter,'') charter FROM coordination_actors WHERE active=1 AND actor_id<>'owner' ORDER BY actor_id").fetchall()
        if not actors: raise ValueError("No active session can be routed this command")
        terms = set((body["title"] + " " + body["scope"] + " " + body["owner_request"]).casefold().split())
        scored = [(sum(1 for term in set(a["charter"].casefold().split()) if len(term)>2 and term in terms),a["actor_id"]) for a in actors]
        best = max(score for score,_ in scored)
        targets = [actor for score,actor in scored if score==best] if best else [actors[0]["actor_id"]]
    missing = [x for x in targets if not db.execute("SELECT 1 FROM coordination_actors WHERE actor_id=? AND active=1", (x,)).fetchone()]
    if missing: raise ValueError("Unknown or inactive target actor")
    from coordination_repository import _event
    with db:
        for cid, parent, actor, status, role in [(root,None,None,"queued","root"), *[(str(uuid.uuid4()),root,a,"assigned","session") for a in targets]]:
            db.execute("INSERT INTO coordination_cards(card_id,title,owner_request,scope,status,assigned_actor_id,created_at,updated_at,current_status_code,current_status_version,parent_card_id,card_type_code,priority_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,body["title"],body["owner_request"],body["scope"],"in_progress" if status in {"queued","assigned"} else status,actor,now,now,status,1,parent,body.get("card_type_code","general"),body.get("priority_code","normal")))
            ev=_event(db,cid,"card_created",stage_code="intake",next_status=status,recorded_at=now)
            if cid == root: db.execute("INSERT INTO coordination_command_receipts VALUES(?,?,?)", (key,root,now))
            db.execute("INSERT INTO coordination_command_cards VALUES(?,?,?)", (key,cid,role))
            if actor:
                assign_event=_event(db,cid,"card_assigned",stage_code="assignment",source_type="assignment",source_id=actor,recorded_at=now)
                db.execute("INSERT INTO coordination_assignments(card_id,assigned_actor_id,assigned_at,source_event_id) VALUES(?,?,?,?)",(cid,actor,now,assign_event))
                for i,c in enumerate(body.get("criteria", [])):
                    db.execute("INSERT INTO coordination_card_criteria(card_id,criterion_code,title,description,required,check_method,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?)",(cid,c["criterion_code"],c["title"],c.get("description",""),int(c.get("required",True)),c.get("check_method","manual_evidence"),i,now))
                db.execute("INSERT INTO coordination_outbox(card_id,event_id,target_actor_id,command_code,idempotency_key,available_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (cid,assign_event,actor,"card_assignment",key+":"+cid,now,now,now))
    child_ids=[r[0] for r in db.execute("SELECT card_id FROM coordination_command_cards WHERE idempotency_key=? AND role_code='session' ORDER BY card_id",(key,))]
    return {"root_card_id":root,"child_card_ids":child_ids,"created":True}, True


def add_event(db: sqlite3.Connection, card_id: str, body: dict) -> int:
    if not db.execute("SELECT 1 FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone(): raise KeyError(card_id)
    from coordination_repository import _event
    return _event(db,card_id,body["event_type"],actor_id=body.get("actor_id"),note=json.dumps(body.get("details",{}),ensure_ascii=False),correlation_id=body.get("correlation_id"))


def add_blocker(db: sqlite3.Connection, card_id: str, body: dict) -> int:
    issue_id=record_issue(db,card_id,stage_code=body["stage_code"],cause_code=body.get("cause_code"),cause_resolution="unresolved",impact_summary=body["impact_summary"],actor_id=body.get("actor_id"))
    row=db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",(card_id,)).fetchone()
    if row and row[0] != "blocked": transition_card(db,card_id,"blocked",actor_id=body.get("actor_id"),stage_code=body["stage_code"],reason_code=body.get("cause_code"),note=body["impact_summary"])
    return issue_id


def resolve_issue(db: sqlite3.Connection, card_id: str, issue_id: int, body: dict) -> None:
    issue=db.execute("SELECT issue_id FROM coordination_issues WHERE card_id=? AND issue_id=? AND resolved_at IS NULL",(card_id,issue_id)).fetchone()
    if not issue: raise KeyError(f"Unknown open issue: {issue_id}")
    now=utc_now(); actor=body.get("actor_id")
    from coordination_repository import _event
    event=_event(db,card_id,"blocker_resolved",actor_id=actor,stage_code=body.get("stage_code","execution"),reason_code=body.get("cause_code"),reason_resolution="confirmed",note=body.get("resolution",""),source_type="workflow_issue",source_id=str(issue_id))
    db.execute("UPDATE coordination_issues SET resolved_at=?,resolved_by_actor_id=?,cause_resolution='confirmed' WHERE issue_id=?",(now,actor,issue_id))
    remaining=db.execute("SELECT 1 FROM coordination_issues WHERE card_id=? AND resolved_at IS NULL LIMIT 1",(card_id,)).fetchone()
    status=db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",(card_id,)).fetchone()[0]
    if not remaining and status=="blocked": transition_card(db,card_id,"in_progress",actor_id=actor,stage_code="execution",related_event_id=event,note="All recorded blockers resolved")


def add_delivery(db: sqlite3.Connection, card_id: str, body: dict) -> int:
    attempt=record_delivery_attempt(db,card_id,submitted_by_actor_id=body.get("submitted_by_actor_id"),summary=body.get("summary",""))
    now=utc_now()
    db.execute("UPDATE coordination_delivery_attempts SET branch_name=?,remote_name=?,commit_sha=? WHERE attempt_id=?", (body.get("branch_name"),body.get("remote_name"),body.get("commit_sha"),attempt))
    for path in body.get("changed_paths",[]): db.execute("INSERT OR IGNORE INTO coordination_delivery_paths(attempt_id,path) VALUES(?,?)",(attempt,path))
    return attempt


def verify_delivery(db: sqlite3.Connection, card_id: str, attempt_id: int) -> dict:
    row=db.execute("SELECT branch_name,commit_sha,remote_name FROM coordination_delivery_attempts WHERE card_id=? AND attempt_id=?",(card_id,attempt_id)).fetchone()
    if not row: raise KeyError(f"Unknown delivery attempt: {attempt_id}")
    if db.execute("SELECT 1 FROM coordination_issues WHERE card_id=? AND resolved_at IS NULL LIMIT 1",(card_id,)).fetchone():
        return {"verified":False,"reason":"unresolved_blocker"}
    branch,commit,remote=row
    if remote not in (None,"origin") or not branch or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}",branch) or ".." in branch or not commit or not re.fullmatch(r"[0-9a-fA-F]{40,64}",commit):
        raise ValueError("Delivery requires a valid branch, commit SHA, and configured origin remote")
    proc=subprocess.run(["git","-C",str(REPO_ROOT),"ls-remote","origin",f"refs/heads/{branch}"],capture_output=True,text=True,timeout=12,check=False)
    remote_sha=proc.stdout.split()[0] if proc.returncode==0 and proc.stdout.split() else None
    now=utc_now(); verified=bool(remote_sha and remote_sha.lower()==commit.lower())
    db.execute("UPDATE coordination_delivery_attempts SET remote_name='origin',remote_commit_sha=?,verified_at=? WHERE attempt_id=?",(remote_sha if verified else None,now if verified else None,attempt_id))
    db.execute("UPDATE coordination_delivery_attempts SET outcome=? WHERE attempt_id=?",("accepted" if verified else "failed",attempt_id))
    if not verified: return {"verified":False,"reason":"remote_commit_mismatch_or_unavailable","remote_commit_sha":remote_sha}
    current=db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",(card_id,)).fetchone()[0]
    if current in ("in_progress","returned","blocked"):
        transition_card(db,card_id,"delivered",actor_id=None,stage_code="delivery",note="Commit verified on origin")
    return {"verified":True,"remote_commit_sha":remote_sha}


def add_quality_run(db: sqlite3.Connection, card_id: str, body: dict) -> int:
    now=utc_now(); cur=db.execute("INSERT INTO coordination_quality_runs(card_id,attempt_id,commit_sha,profile_code,runner_name,runner_version,outcome,started_at,finished_at,correlation_id) VALUES(?,?,?,?,?,?,?,?,?,?)", (card_id,body.get("attempt_id"),body.get("commit_sha"),body["profile_code"],body["runner_name"],body["runner_version"],body["outcome"],now,now,body.get("attempt_id")))
    rid=cur.lastrowid
    for c in body.get("checks",[]): db.execute("INSERT INTO coordination_quality_checks(quality_run_id,check_code,outcome,duration_ms,evidence_ref,message_code) VALUES(?,?,?,?,?,?)",(rid,c["check_code"],c["outcome"],c.get("duration_ms"),c.get("evidence_ref"),c.get("message_code","")))
    if body["outcome"] == "pass":
        row=db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",(card_id,)).fetchone()
        unresolved=db.execute("SELECT 1 FROM coordination_issues WHERE card_id=? AND resolved_at IS NULL LIMIT 1",(card_id,)).fetchone()
        required=db.execute("SELECT criterion_code FROM coordination_card_criteria WHERE card_id=? AND required=1",(card_id,)).fetchall()
        passing={r[0] for r in db.execute("SELECT check_code FROM coordination_quality_checks WHERE quality_run_id=? AND outcome='pass'",(rid,))}
        delivery=db.execute("SELECT remote_commit_sha,commit_sha FROM coordination_delivery_attempts WHERE card_id=? ORDER BY attempt_number DESC LIMIT 1",(card_id,)).fetchone()
        if row and row[0]=="delivered": transition_card(db,card_id,"verifying",actor_id=None,stage_code="quality")
        if row and row[0] in ("delivered","verifying") and not unresolved and all(r[0] in passing for r in required) and delivery and delivery[0] and delivery[0]==delivery[1]:
            transition_card(db,card_id,"completed",actor_id=None,stage_code="quality",note="Automated close conditions satisfied")
            parent=db.execute("SELECT parent_card_id FROM coordination_cards WHERE card_id=?",(card_id,)).fetchone()[0]
            if parent:
                remaining=db.execute("SELECT 1 FROM coordination_cards WHERE parent_card_id=? AND current_status_code<>'completed' LIMIT 1",(parent,)).fetchone()
                p=db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",(parent,)).fetchone()
                if not remaining and p and p[0] in ("queued","assigned","in_progress"):
                    transition_card(db,parent,"completed",actor_id=None,stage_code="rollup",note="All assigned session cards completed")
    return rid
