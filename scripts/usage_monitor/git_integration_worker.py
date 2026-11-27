"""Integrate verified card deliveries through GitHub and the canonical local main worktree."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from usage_database import connect, utc_now
from coordination_repository import _event

ROOT = Path(__file__).resolve().parents[2]
LEASE_SECONDS = 180
POLL_SECONDS = 20


class IntegrationError(RuntimeError):
    def __init__(self, code: str, *, returned: bool = False):
        super().__init__(code)
        self.code = code
        self.returned = returned


def _run(args: list[str], *, cwd: Path = ROOT, timeout: int = 45) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IntegrationError("git_or_github_command_unavailable") from exc
    if result.returncode:
        raise IntegrationError("git_or_github_command_failed")
    return result.stdout.strip()


def _main_worktree() -> Path:
    configured = os.environ.get("WORKFLOW_MAIN_REPOSITORY")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if Path(_run(["git", "rev-parse", "--show-toplevel"], cwd=candidate)).resolve() != candidate:
            raise IntegrationError("canonical_main_worktree_invalid")
        branch = _run(["git", "branch", "--show-current"], cwd=candidate)
        if branch != "main":
            raise IntegrationError("canonical_worktree_not_on_main")
        return candidate
    listing = _run(["git", "worktree", "list", "--porcelain"])
    current_path = None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[9:]).resolve()
        elif line == "branch refs/heads/main" and current_path:
            return current_path
    raise IntegrationError("canonical_main_worktree_not_found")


def _claim(database: Path) -> sqlite3.Row | None:
    db = connect(database)
    try:
        now = utc_now()
        with db:
            db.execute("""UPDATE coordination_git_integrations SET state_code='pending',locked_until=NULL,
                updated_at=? WHERE state_code='processing' AND locked_until<?""", (now, now))
            row = db.execute("""SELECT i.*,c.title,c.owner_request,d.submitted_by_actor_id
                FROM coordination_git_integrations i JOIN coordination_cards c ON c.card_id=i.card_id
                JOIN coordination_delivery_attempts d ON d.attempt_id=i.attempt_id
                WHERE i.state_code IN ('pending','awaiting_checks','awaiting_review','merged_sync_pending')
                  AND i.next_attempt_at<=? AND (i.locked_until IS NULL OR i.locked_until<?)
                ORDER BY i.next_attempt_at,i.integration_id LIMIT 1""", (now, now)).fetchone()
            if not row:
                return None
            db.execute("""UPDATE coordination_git_integrations SET state_code='processing',
                locked_until=?,attempt_count=attempt_count+1,updated_at=? WHERE integration_id=?""",
                ((datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat(), now,
                 row["integration_id"]))
            return row
    finally:
        db.close()


def _read_paths(database: Path, attempt_id: int) -> list[str]:
    db = connect(database)
    try:
        return [row[0] for row in db.execute(
            "SELECT path FROM coordination_delivery_paths WHERE attempt_id=? ORDER BY path", (attempt_id,))]
    finally:
        db.close()


def _ensure_verifying(database: Path, card_id: str) -> None:
    db = connect(database)
    try:
        row = db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()
        if not row or row[0] != "verifying":
            raise IntegrationError("card_no_longer_verifying", returned=bool(row and row[0] == "returned"))
    finally:
        db.close()


def _pr_json(number: int, repository: str) -> dict:
    value = _run(["gh", "pr", "view", str(number),
                  "--repo", repository, "--json",
                  "state,headRefOid,baseRefOid,baseRefName,mergeStateStatus,reviewDecision,statusCheckRollup,mergeCommit,url,number"])
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise IntegrationError("github_response_invalid") from exc


def _record(database: Path, row: sqlite3.Row, *, state: str, note: str,
            updates: dict[str, object] | None = None, code: str | None = None,
            returned: bool = False) -> None:
    db = connect(database)
    try:
        with db:
            db.execute("SELECT * FROM coordination_git_integrations WHERE integration_id=?",
                                 (row["integration_id"],)).fetchone()
            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=POLL_SECONDS)).isoformat()
            assignments = {"state_code": state, "last_error_code": code,
                           "updated_at": utc_now(), "locked_until": None,
                           "next_attempt_at": retry_at}
            if updates:
                assignments.update(updates)
            db.execute("UPDATE coordination_git_integrations SET " + ",".join(f"{key}=?" for key in assignments)
                       + " WHERE integration_id=?", (*assignments.values(), row["integration_id"]))
            if row["state_code"] != state or row["last_error_code"] != code:
                _event(db, row["card_id"], "git_integration_state", stage_code="git_integration",
                       source_type="git_integration", source_id=str(row["integration_id"]),
                       note=note + (f" ({code})" if code else ""))
            if state == "returned":
                from coordination_repository import transition_card
                card = db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",
                                  (row["card_id"],)).fetchone()
                if card and card[0] in {"verifying", "delivered"}:
                    transition_card(db, row["card_id"], "returned", actor_id=None,
                                    stage_code="git_integration", reason_code=code or "integration_failed",
                                    note=note, source_type="git_integration", source_id=str(row["integration_id"]))
    finally:
        db.close()


def _finish_local_sync(database: Path, row: sqlite3.Row, pr: dict) -> None:
    merge_sha = (pr.get("mergeCommit") or {}).get("oid")
    if not merge_sha or not re.fullmatch(r"[0-9a-f]{40,64}", merge_sha.lower()):
        raise IntegrationError("github_merge_sha_missing")
    main = _main_worktree()
    status = _run(["git", "status", "--porcelain"], cwd=main)
    if any(line[3:].strip() and not line.startswith("?? ") for line in status.splitlines()):
        raise IntegrationError("canonical_main_has_local_changes")
    _run(["git", "fetch", "origin", "main"], cwd=main, timeout=120)
    remote_sha = _run(["git", "rev-parse", "refs/remotes/origin/main"], cwd=main).lower()
    if not re.fullmatch(r"[0-9a-f]{40,64}", remote_sha):
        raise IntegrationError("remote_main_sha_unavailable")
    local_sha = _run(["git", "rev-parse", "HEAD"], cwd=main).lower()
    if local_sha != remote_sha:
        try:
            base_sha = _run(["git", "merge-base", "HEAD", "refs/remotes/origin/main"], cwd=main).lower()
        except IntegrationError as exc:
            raise IntegrationError("canonical_main_diverged_from_remote") from exc
        if base_sha != local_sha:
            raise IntegrationError("canonical_main_diverged_from_remote")
        untracked = {item for item in _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=main).splitlines() if item}
        incoming = set(_run(["git", "diff", "--name-only", "HEAD..refs/remotes/origin/main"], cwd=main).splitlines())
        if any(local == changed or local.startswith(changed + "/") or changed.startswith(local + "/")
               for local in untracked for changed in incoming):
            raise IntegrationError("canonical_main_untracked_file_conflict")
        try:
            _run(["git", "pull", "--ff-only", "origin", "main"], cwd=main, timeout=120)
        except IntegrationError as exc:
            raise IntegrationError("canonical_main_pull_blocked") from exc
        local_sha = _run(["git", "rev-parse", "HEAD"], cwd=main).lower()
    current_remote_values = _run(["git", "ls-remote", "origin", "refs/heads/main"], cwd=main).split()
    if not current_remote_values:
        raise IntegrationError("remote_main_sha_unavailable")
    current_remote_sha = current_remote_values[0].lower()
    if current_remote_sha != remote_sha:
        raise IntegrationError("remote_main_changed_during_sync")
    if local_sha != remote_sha:
        raise IntegrationError("canonical_main_sync_mismatch")
    try:
        merge_base = _run(["git", "merge-base", merge_sha, "HEAD"], cwd=main).lower()
    except IntegrationError as exc:
        raise IntegrationError("merged_commit_not_in_local_main") from exc
    if merge_base != merge_sha.lower():
        raise IntegrationError("merged_commit_not_in_local_main")
    db = connect(database)
    try:
        with db:
            now = utc_now()
            db.execute("""UPDATE coordination_git_integrations SET state_code='completed',
                merge_sha=?,base_sha=?,local_main_sha=?,remote_main_sha=?,last_error_code=NULL,
                updated_at=?,locked_until=NULL,next_attempt_at=? WHERE integration_id=?""",
                (merge_sha, pr.get("baseRefOid"), local_sha,
                 remote_sha, now, now, row["integration_id"]))
            _event(db, row["card_id"], "git_integration_completed", stage_code="git_integration",
                   source_type="git_integration", source_id=str(row["integration_id"]),
                   note=f"دُمج PR #{pr.get('number')}؛ main المحلي والبعيد متطابقان عند {local_sha[:12]}")
            from coordination_repository import transition_card
            card_status = db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",
                                     (row["card_id"],)).fetchone()
            if card_status and card_status[0] == "verifying":
                transition_card(db, row["card_id"], "completed", actor_id=None, stage_code="git_integration",
                                note="اجتازت الفحوص، ودُمجت البطاقة، وتزامن main المحلي مع origin/main",
                                source_type="git_integration", source_id=str(row["integration_id"]))
            parent = db.execute("SELECT parent_card_id FROM coordination_cards WHERE card_id=?",
                                (row["card_id"],)).fetchone()[0]
            if parent:
                remaining = db.execute("SELECT 1 FROM coordination_cards WHERE parent_card_id=? AND current_status_code<>'completed' LIMIT 1",
                                       (parent,)).fetchone()
                parent_status = db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?",
                                           (parent,)).fetchone()[0]
                if card_status and card_status[0] == "verifying" and not remaining and parent_status in {"queued", "assigned", "in_progress"}:
                    transition_card(db, parent, "completed", actor_id=None, stage_code="rollup",
                                    note="اكتملت جميع بطاقات الجلسات التابعة بعد مزامنة main",
                                    source_type="session_rollup")
            db.execute("""INSERT INTO coordination_git_events
                (card_id,remote_name,branch_name,commit_sha,action,outcome,recorded_at)
                VALUES(?,'origin',?,?, 'merge','verified',?)""",
                (row["card_id"], row["head_branch"], (pr.get("mergeCommit") or {}).get("oid") or local_sha, now))
    finally:
        db.close()


def process_one(database: Path) -> dict | None:
    row = _claim(database)
    if row is None:
        return None
    ident = int(row["integration_id"])
    try:
        if row["state_code"] == "merged_sync_pending":
            pr = _pr_json(int(row["pull_request_number"]), row["repository"])
            if pr.get("state") != "MERGED":
                raise IntegrationError("merged_pull_request_not_confirmed")
            if pr.get("baseRefName") != "main" or pr.get("headRefOid", "").lower() != row["head_sha"].lower():
                raise IntegrationError("merged_pull_request_head_or_base_mismatch")
            _finish_local_sync(database, row, pr)
            return {"integration_id": ident, "state": "completed"}

        if not row["pull_request_number"]:
            _ensure_verifying(database, row["card_id"])
            matches = _run(["gh", "pr", "list", "--repo", row["repository"], "--state", "all",
                            "--head", row["head_branch"], "--base", "main", "--json", "number,url,state"])
            prs = json.loads(matches or "[]")
            pr_ref = next((item for item in prs if item.get("state") == "OPEN"), None)
            if not pr_ref:
                merged_pr = None
                for candidate in prs:
                    if candidate.get("state") != "MERGED":
                        continue
                    candidate_pr = _pr_json(int(candidate["number"]), row["repository"])
                    if candidate_pr.get("baseRefName") == "main" and candidate_pr.get("headRefOid", "").lower() == row["head_sha"].lower():
                        merged_pr = candidate_pr
                        break
                if merged_pr:
                    _record(database, row, state="merged_sync_pending", note="استُعيد PR مطابق ومدمج من GitHub؛ جارٍ مزامنة main المحلي",
                            updates={"pull_request_number": merged_pr["number"], "pull_request_url": merged_pr.get("url"),
                                     "base_sha": merged_pr.get("baseRefOid"),
                                     "merge_sha": (merged_pr.get("mergeCommit") or {}).get("oid")})
                    fresh = connect(database)
                    try:
                        merged_row = fresh.execute("SELECT * FROM coordination_git_integrations WHERE integration_id=?", (ident,)).fetchone()
                        _finish_local_sync(database, merged_row, merged_pr)
                    finally:
                        fresh.close()
                    return {"integration_id": ident, "state": "completed"}
                title = f"{row['card_id']}: {row['title']}"[:240]
                body = "بطاقة مصنع موثقة في قاعدة البيانات. راجع سجل البطاقة ونتائج الجودة قبل الدمج."
                created = _run(["gh", "pr", "create", "--repo", row["repository"], "--base", "main", "--head", row["head_branch"],
                                "--title", title, "--body", body])
                pr_ref = {"url": created.strip()}
            if not pr_ref.get("number"):
                pr_ref["number"] = int(_run(["gh", "pr", "view", pr_ref["url"], "--repo", row["repository"], "--json", "number", "--jq", ".number"]))
            pr = _pr_json(int(pr_ref["number"]), row["repository"])
            if pr.get("state") == "MERGED" and pr.get("baseRefName") == "main" and \
                    pr.get("headRefOid", "").lower() == row["head_sha"].lower():
                _record(database, row, state="merged_sync_pending", note="استُعيد PR مدمج من قاعدة GitHub؛ جارٍ مزامنة main المحلي",
                        updates={"pull_request_number": pr["number"], "pull_request_url": pr.get("url"),
                                 "base_sha": pr.get("baseRefOid"),
                                 "merge_sha": (pr.get("mergeCommit") or {}).get("oid")})
                fresh = connect(database)
                try:
                    merged_row = fresh.execute("SELECT * FROM coordination_git_integrations WHERE integration_id=?", (ident,)).fetchone()
                    _finish_local_sync(database, merged_row, pr)
                finally:
                    fresh.close()
                return {"integration_id": ident, "state": "completed"}
            if pr.get("state") == "MERGED":
                raise IntegrationError("pull_request_head_or_base_mismatch", returned=True)
            if pr.get("state") != "OPEN":
                raise IntegrationError("pull_request_closed_without_merge", returned=True)
            _record(database, row, state="awaiting_checks", note="أُنشئ أو استُعيد PR تلقائيًا؛ بانتظار CI ومراجعة الدمج",
                    updates={"pull_request_number": pr["number"], "pull_request_url": pr.get("url"),
                             "base_sha": pr.get("baseRefOid")})
            return {"integration_id": ident, "state": "awaiting_checks", "pull_request": pr["number"]}

        pr = _pr_json(int(row["pull_request_number"]), row["repository"])
        if pr.get("state") == "MERGED":
            if pr.get("baseRefName") != "main" or pr.get("headRefOid", "").lower() != row["head_sha"].lower():
                raise IntegrationError("merged_pull_request_head_or_base_mismatch")
            _record(database, row, state="merged_sync_pending", note="اكتُشف دمج PR؛ جارٍ مزامنة main المحلي",
                    updates={"merge_sha": (pr.get("mergeCommit") or {}).get("oid"), "base_sha": pr.get("baseRefOid")})
            fresh = connect(database)
            try:
                merged_row = fresh.execute("SELECT * FROM coordination_git_integrations WHERE integration_id=?", (ident,)).fetchone()
                _finish_local_sync(database, merged_row, pr)
            finally:
                fresh.close()
            return {"integration_id": ident, "state": "completed"}
        _ensure_verifying(database, row["card_id"])
        if pr.get("state") != "OPEN" or pr.get("baseRefName") != "main" or pr.get("headRefOid", "").lower() != row["head_sha"].lower():
            raise IntegrationError("pull_request_head_or_base_mismatch", returned=True)

        expected_paths = _read_paths(database, int(row["attempt_id"]))
        actual_paths = sorted(set(_run(["gh", "pr", "diff", str(row["pull_request_number"]),
                                       "--repo", row["repository"], "--name-only"]).splitlines()))
        if not expected_paths or actual_paths != expected_paths:
            raise IntegrationError("pull_request_changed_paths_mismatch", returned=True)
        checks = pr.get("statusCheckRollup") or []
        if not checks:
            _record(database, row, state="awaiting_checks", note="لم تُنشر نتائج CI بعد؛ ستُعاد المراجعة آليًا")
            return {"integration_id": ident, "state": "awaiting_checks"}
        failing = any(item.get("conclusion") not in {None, "SUCCESS"} and item.get("state") not in {"SUCCESS"}
                      for item in checks)
        pending = any((item.get("status") not in {None, "COMPLETED"}) or
                      (item.get("state") not in {None, "SUCCESS"}) for item in checks)
        if failing:
            raise IntegrationError("github_checks_failed", returned=True)
        if pending:
            _record(database, row, state="awaiting_checks", note="فحوص CI لا تزال جارية؛ ستُعاد المراجعة آليًا")
            return {"integration_id": ident, "state": "awaiting_checks"}
        if pr.get("reviewDecision") == "CHANGES_REQUESTED":
            raise IntegrationError("github_changes_requested", returned=True)
        if pr.get("reviewDecision") == "REVIEW_REQUIRED":
            _record(database, row, state="awaiting_review", note="فحوص CI اجتازت؛ PR ينتظر مراجعة GitHub المطلوبة")
            return {"integration_id": ident, "state": "awaiting_review"}
        if pr.get("mergeStateStatus") == "BEHIND":
            raise IntegrationError("pull_request_branch_behind_main", returned=True)
        if pr.get("mergeStateStatus") == "DIRTY":
            raise IntegrationError("pull_request_merge_conflict", returned=True)
        if pr.get("mergeStateStatus") != "CLEAN":
            _record(database, row, state="awaiting_checks", note="GitHub لم يؤكد بعد أن فرع PR قابل للدمج بلا تعارض")
            return {"integration_id": ident, "state": "awaiting_checks"}
        _ensure_verifying(database, row["card_id"])
        _run(["gh", "pr", "merge", str(row["pull_request_number"]), "--repo", row["repository"], "--squash"])
        pr = _pr_json(int(row["pull_request_number"]), row["repository"])
        if pr.get("state") != "MERGED":
            _record(database, row, state="merged_sync_pending", note="أُرسل طلب الدمج؛ بانتظار تأكيد GitHub")
            return {"integration_id": ident, "state": "merged_sync_pending"}
        if pr.get("baseRefName") != "main" or pr.get("headRefOid", "").lower() != row["head_sha"].lower():
            raise IntegrationError("merged_pull_request_head_or_base_mismatch")
        _record(database, row, state="merged_sync_pending", note="تم الدمج على GitHub؛ جارٍ مزامنة main المحلي",
                updates={"merge_sha": (pr.get("mergeCommit") or {}).get("oid"), "base_sha": pr.get("baseRefOid")})
        fresh = connect(database)
        try:
            merged_row = fresh.execute("SELECT * FROM coordination_git_integrations WHERE integration_id=?", (ident,)).fetchone()
            _finish_local_sync(database, merged_row, pr)
        finally:
            fresh.close()
        return {"integration_id": ident, "state": "completed"}
    except IntegrationError as exc:
        if exc.code in {"git_or_github_command_unavailable", "git_or_github_command_failed",
                        "remote_main_changed_during_sync"}:
            _record(database, row, state="awaiting_checks", code=exc.code,
                    note="تعذر اتصال مؤقت؛ ستُعاد المحاولة تلقائيًا")
            return {"integration_id": ident, "state": "awaiting_checks", "error_code": exc.code}
        state = "returned" if exc.returned else "blocked"
        _record(database, row, state=state, code=exc.code, returned=exc.returned,
                note="توقف تكامل Git بأمان؛ سُجل السبب في تاريخ البطاقة")
        return {"integration_id": ident, "state": state, "error_code": exc.code}
    except (ValueError, sqlite3.Error):
        _record(database, row, state="blocked", code="integration_data_or_database_error",
                note="توقف التكامل بسبب بيانات أو قاعدة غير صالحة؛ لم تُسجل مخرجات حساسة")
        return {"integration_id": ident, "state": "blocked", "error_code": "integration_data_or_database_error"}
    except Exception:
        _record(database, row, state="blocked", code="integration_unexpected_error",
                note="توقف التكامل بسبب خطأ داخلي؛ حُفظ رمز عام في تاريخ البطاقة")
        return {"integration_id": ident, "state": "blocked", "error_code": "integration_unexpected_error"}


def integration_loop(database: Path, stop_event, *, interval_seconds: float = POLL_SECONDS) -> None:
    while not stop_event.is_set():
        try:
            result = process_one(database)
            stop_event.wait(1 if result else interval_seconds)
        except Exception:
            stop_event.wait(interval_seconds)
