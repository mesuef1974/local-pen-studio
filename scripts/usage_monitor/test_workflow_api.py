from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from codex_session_dispatcher import dispatch_one
from coordination_repository import transition_card
from usage_database import SCHEMA_VERSION, connect, utc_now
from workflow_api import board, card_details, criterion_catalog, create_command, decide_card_proposal, submit_session_opinion, submit_card_proposal, submit_delivery, submit_quality, transition_assigned_card


class WorkflowCommandRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "usage.sqlite3"
        db = connect(self.path)
        now = utc_now()
        with db:
            db.execute("INSERT INTO coordination_actors(actor_id,display_name,charter,active) VALUES('owner','Owner','owner',1) "
                       "ON CONFLICT(actor_id) DO UPDATE SET display_name=excluded.display_name,charter=excluded.charter,active=1")
            db.execute("INSERT INTO coordination_actors(actor_id,display_name,charter,active) VALUES('laser','Laser','frontend interface',1) "
                       "ON CONFLICT(actor_id) DO UPDATE SET display_name=excluded.display_name,charter=excluded.charter,active=1")
            db.execute("INSERT INTO coordination_actor_endpoints(actor_id,provider_code,thread_id,enabled,created_at,updated_at) VALUES('laser','codex_cli','thread-laser',1,?,?)", (now, now))
            db.execute("INSERT INTO coordination_actor_capabilities(actor_id,capability) VALUES('laser','frontend')")
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def payload(self):
        return {"title": "إصلاح واجهة لوحة المتابعة frontend", "owner_request": "إصلاح واجهة dashboard وتحسين العرض frontend", "scope": "تعديل CSS وHTML", "idempotency_key": "cmd-routing-1", "target_actor_ids": ["laser"], "criteria": []}

    def create_proposal(self):
        source = create_command(self.path, self.payload())
        proposal_payload = {
            "actor_id": "laser", "source_card_id": source["child_card_ids"][0],
            "opinion": "تحتاج البطاقة إلى متابعة مستقلة لفحص الوصولية بعد تغيير النمط.",
            "recommendation": "أوصي ببطاقة متابعة منفصلة للتحقق من التنقل بلوحة المفاتيح.",
            "title": "مراجعة الوصولية بعد تحديث النمط",
            "owner_request": "افحص التنقل بلوحة المفاتيح والتباين في صفحة لوحة المتابعة وسجل النتائج.",
            "scope": "مراجعة الواجهة الحالية واختبارات الوصولية المرتبطة فقط.",
            "rationale": "تحتاج متابعة الوصولية إلى مراجعة مستقلة بعد التعديل.",
            "suggested_assignee_actor_id": "laser", "idempotency_key": "proposal-laser-1",
            "criteria": [{"criterion_code": "keyboard_navigation", "title": "فحص التنقل بلوحة المفاتيح",
                          "description": "تسجيل نتيجة المرور على عناصر التحكم.", "required": True}],
        }
        return source, proposal_payload, submit_card_proposal(self.path, proposal_payload)

    def test_coordinator_records_relay_without_changing_author(self):
        source=create_command(self.path,self.payload())
        db=connect(self.path)
        with db:
            db.execute("INSERT INTO coordination_actors(actor_id,display_name,charter,active) VALUES('brainstorm','عصف ذهني','coordination',1) ON CONFLICT(actor_id) DO UPDATE SET active=1")
        db.close()
        payload={"actor_id":"brainstorm","opinion_actor_id":"laser","source_card_id":source["child_card_ids"][0],
            "opinion":"رأي ليزر المنقول", "recommendation":"أوصي بالتحقق", "source_reference":"استشارة منقولة موثقة", "idempotency_key":"relay-one"}
        submit_session_opinion(self.path,payload)
        history=card_details(self.path,payload["source_card_id"])["opinion_history"]
        self.assertEqual(history[0]["actor_id"],"laser")
        self.assertEqual(history[0]["recorded_by_actor_id"],"brainstorm")

    def test_opinion_provenance_idempotency_and_author_guard(self):
        source=create_command(self.path,self.payload())
        payload={"actor_id":"laser","opinion_actor_id":"laser","source_card_id":source["child_card_ids"][0],
            "opinion":"هذا رأي استشاري للاختبار", "recommendation":"أوصي بالمراجعة", "source_reference":"مصدر مباشر", "idempotency_key":"opinion-one"}
        first=submit_session_opinion(self.path,payload)
        self.assertTrue(first["created"])
        self.assertFalse(submit_session_opinion(self.path,payload)["created"])
        with self.assertRaises(ValueError):
            submit_session_opinion(self.path,dict(payload,opinion="رأي مختلف"))
        with self.assertRaises(ValueError):
            submit_session_opinion(self.path,dict(payload,opinion_actor_id="svg",idempotency_key="other"))
        history=card_details(self.path,payload["source_card_id"])["opinion_history"]
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]["actor_id"],"laser")
        self.assertEqual(history[0]["recorded_by_actor_id"],"laser")
        self.assertIn("مصدر مباشر",history[0]["source_details"])

    def test_session_proposal_is_persisted_with_immutable_opinion_link_and_owner_review(self):
        source, payload, created = self.create_proposal()
        self.assertTrue(created["created"])
        duplicate = submit_card_proposal(self.path, payload)
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["proposal_id"], created["proposal_id"])
        changed_payload = dict(payload, rationale="تغير سبب الاقتراح مع إعادة استخدام المفتاح نفسه.")
        with self.assertRaisesRegex(ValueError, "مفتاح منع التكرار"):
            submit_card_proposal(self.path, changed_payload)
        data = board(self.path)
        proposal = next(item for item in data["card_proposals"] if item["proposal_id"] == created["proposal_id"])
        self.assertEqual(proposal["status_code"], "pending_owner")
        self.assertEqual(proposal["suggested_assignee_actor_id"], "laser")
        self.assertEqual(len(proposal["criteria"]), 1)
        db = connect(self.path)
        try:
            linked = db.execute("""SELECT p.source_opinion_history_id,h.opinion,h.recommendation
                FROM coordination_card_proposals p JOIN coordination_opinion_history h
                ON h.opinion_history_id=p.source_opinion_history_id WHERE p.proposal_id=?""", (created["proposal_id"],)).fetchone()
            self.assertEqual(linked["opinion"], payload["opinion"])
            self.assertEqual(linked["recommendation"], payload["recommendation"])
            events = db.execute("SELECT event_type FROM coordination_events WHERE card_id=? ORDER BY event_id", (source["child_card_ids"][0],)).fetchall()
            self.assertIn("followup_card_proposed", [row[0] for row in events])
        finally:
            db.close()

    def test_proposal_database_rejects_skipped_state_transitions_and_older_schema_board_stays_available(self):
        _, proposal_payload, created = self.create_proposal()
        db = connect(self.path)
        try:
            with self.assertRaisesRegex(Exception, "invalid card proposal state transition"):
                db.execute("UPDATE coordination_card_proposals SET status_code='issued',decided_by_actor_id='owner',decided_at=?,issued_root_card_id='fake' WHERE proposal_id=?",
                           (utc_now(),created["proposal_id"]))
            db.rollback()
            db.execute("DROP TRIGGER trg_card_proposal_state_transitions")
            db.execute("DROP TRIGGER trg_card_proposal_content_immutable")
            db.execute("DROP TRIGGER trg_card_proposal_no_delete")
            db.execute("DROP TRIGGER trg_card_proposal_criteria_no_update")
            db.execute("DROP TRIGGER trg_card_proposal_criteria_no_delete")
            db.execute("DROP TABLE coordination_card_proposal_criteria")
            db.execute("DROP TABLE coordination_card_proposals")
            db.execute("PRAGMA user_version=14")
            db.commit()
        finally:
            db.close()
        data = board(self.path)
        self.assertFalse(data["proposal_workflow_available"])
        self.assertEqual(data["card_proposals"], [])
        with self.assertRaisesRegex(RuntimeError, "مخطط قاعدة البيانات 16"):
            submit_card_proposal(self.path, proposal_payload)

    def test_pending_or_rejected_proposal_cannot_issue_and_only_owner_can_decide(self):
        _, _, created = self.create_proposal()
        command = {"title": "مراجعة الوصولية بعد تحديث النمط", "owner_request": "افحص التنقل بلوحة المفاتيح والتباين في صفحة لوحة المتابعة وسجل النتائج.",
                   "scope": "مراجعة الواجهة الحالية واختبارات الوصولية المرتبطة فقط.", "idempotency_key": "issue-before-approval",
                   "target_actor_ids": ["laser"], "proposal_id": created["proposal_id"]}
        with self.assertRaisesRegex(ValueError, "قبل اعتماد المالك"):
            create_command(self.path, command)
        with self.assertRaisesRegex(ValueError, "صلاحية المالك فقط"):
            decide_card_proposal(self.path, created["proposal_id"], {"actor_id": "laser", "decision": "approve"})
        decision = decide_card_proposal(self.path, created["proposal_id"], {"actor_id": "owner", "decision": "reject", "notes": "لا حاجة للمتابعة الآن"})
        self.assertEqual(decision["status_code"], "rejected")
        with self.assertRaisesRegex(ValueError, "قبل اعتماد المالك"):
            create_command(self.path, command)

    def test_owner_approval_issues_exactly_one_linked_command_and_keeps_session_choice_explicit(self):
        _, _, created = self.create_proposal()
        proposal_id = created["proposal_id"]
        decide_card_proposal(self.path, proposal_id, {"actor_id": "owner", "decision": "approve", "notes": "اعتماد بعد المراجعة"})
        command = {"title": "مراجعة الوصولية بعد تحديث النمط", "owner_request": "افحص التنقل بلوحة المفاتيح والتباين في صفحة لوحة المتابعة وسجل النتائج.",
                   "scope": "مراجعة الواجهة الحالية واختبارات الوصولية المرتبطة فقط.", "idempotency_key": "issue-approved-proposal",
                   "target_actor_ids": ["laser"], "proposal_id": proposal_id,
                   "criteria": [{"criterion_code": "keyboard_navigation", "title": "فحص التنقل بلوحة المفاتيح",
                                 "description": "تسجيل نتيجة المرور على عناصر التحكم.", "required": True}]}
        result = create_command(self.path, command)
        self.assertTrue(result["created"])
        retry = create_command(self.path, command)
        self.assertFalse(retry["created"])
        self.assertEqual(retry["root_card_id"], result["root_card_id"])
        db = connect(self.path)
        try:
            proposal = db.execute("SELECT status_code,issued_root_card_id,decided_by_actor_id FROM coordination_card_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            self.assertEqual(tuple(proposal), ("issued", result["root_card_id"], "owner"))
            target = db.execute("SELECT assigned_actor_id FROM coordination_cards WHERE card_id=?", (result["child_card_ids"][0],)).fetchone()[0]
            self.assertEqual(target, "laser")
            history = db.execute("SELECT decision,decided_by_actor_id FROM owner_decision_history WHERE axis=?", (f"followup_proposal:{proposal_id}",)).fetchone()
            self.assertEqual(tuple(history), ("approved", "owner"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coordination_events WHERE source_type='card_proposal' AND source_id=? AND event_type='followup_card_issued'", (proposal_id,)).fetchone()[0], 1)
        finally:
            db.close()

    def test_owner_selected_session_is_assigned_and_recorded(self):
        result = create_command(self.path, self.payload())
        self.assertEqual(result["child_card_ids"], result["session_card_ids"])
        db = connect(self.path)
        try:
            row = db.execute("SELECT assigned_actor_id FROM coordination_cards WHERE card_id=?", (result["child_card_ids"][0],)).fetchone()
            self.assertEqual(row[0], "laser")
            assignment = db.execute("SELECT assigned_by_actor_id FROM coordination_assignments WHERE card_id=?", (result["child_card_ids"][0],)).fetchone()
            self.assertEqual(assignment[0], "owner")
            event = db.execute("SELECT actor_id,details FROM coordination_events WHERE card_id=? AND event_type='card_assigned'", (result["child_card_ids"][0],)).fetchone()
            self.assertEqual(event[0], "owner")
            self.assertIn("حدد المالك الجلسة", event[1])
            root = db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?", (result["root_card_id"],)).fetchone()
            self.assertEqual(root[0], "assigned")
            board_data = board(self.path)
            self.assertEqual([card["card_id"] for card in board_data["cards"]], result["child_card_ids"])
            self.assertEqual([card["card_id"] for card in board_data["owner_cards"]], [result["root_card_id"]])
            self.assertEqual(board_data["owner_cards"][0]["owner_target_name"], "Laser")
            self.assertEqual([card["card_id"] for card in board(self.path, actor_id="laser")["owner_cards"]], [result["root_card_id"]])
            self.assertEqual([card["card_id"] for card in board(self.path, actor_id="owner")["owner_cards"]], [result["root_card_id"]])
            self.assertEqual(card_details(self.path, result["child_card_ids"][0])["assigned_session_duties"]["assignment_scope"],
                             "العتاد الليزري والمواد والعمليات والسلامة والبرامج ومصادرها")
            retry = create_command(self.path, self.payload())
            self.assertFalse(retry["created"])
            self.assertEqual(retry["child_card_ids"], result["child_card_ids"])
        finally:
            db.close()

    def test_markdown_owner_title_is_derived_and_shown_in_owner_lane(self):
        payload = {
            "owner_request": "### نص المهمة لبطاقة التنفيذ\n\n**العنوان:** بوابة ويب محلية لطابعة xTool P2S\n\n**المطلوب:** إنشاء صفحة frontend dashboard كمرجع منظم للوثائق والمواد.",
            "idempotency_key": "cmd-title-from-markdown",
            "target_actor_ids": ["laser"],
        }
        result = create_command(self.path, payload)
        db = connect(self.path)
        try:
            title = db.execute("SELECT title FROM coordination_cards WHERE card_id=?", (result["root_card_id"],)).fetchone()[0]
            self.assertEqual(title, "بوابة ويب محلية لطابعة xTool P2S")
            owner_card = board(self.path)["owner_cards"][0]
            self.assertEqual(owner_card["display_title"], title)
        finally:
            db.close()

    def test_owner_can_select_session_for_a_general_task_without_keyword_routing(self):
        payload = self.payload()
        payload.update(title="عمل عام", owner_request="القيام بالمهمة المطلوبة", scope="عمل عام", idempotency_key="cmd-routing-2")
        result = create_command(self.path, payload)
        db = connect(self.path)
        try:
            actor = db.execute("SELECT assigned_actor_id FROM coordination_cards WHERE card_id=?", (result["child_card_ids"][0],)).fetchone()[0]
            self.assertEqual(actor, "laser")
        finally:
            db.close()

    def test_rejects_english_card_content(self):
        payload = self.payload()
        payload["title"] = "Fix dashboard interface"
        with self.assertRaisesRegex(ValueError, "باللغة العربية"):
            create_command(self.path, payload)

    def test_session_selection_is_required_and_must_be_single(self):
        payload = self.payload()
        payload.pop("target_actor_ids")
        with self.assertRaisesRegex(ValueError, "اختر جلسة واحدة"):
            create_command(self.path, payload)
        payload = self.payload()
        payload["target_actor_ids"] = ["laser", "laser"]
        with self.assertRaisesRegex(ValueError, "اختر جلسة واحدة"):
            create_command(self.path, payload)

    def test_selected_session_must_be_active_and_dispatchable(self):
        payload = self.payload()
        payload["target_actor_ids"] = ["missing-session"]
        with self.assertRaisesRegex(ValueError, "غير نشطة أو غير مهيأة"):
            create_command(self.path, payload)

        db = connect(self.path)
        try:
            now = utc_now()
            with db:
                db.execute("INSERT INTO coordination_actors(actor_id,display_name,charter,active) VALUES('offline','غير متصلة','عام',1)")
                db.execute("INSERT INTO coordination_actor_endpoints(actor_id,provider_code,thread_id,enabled,created_at,updated_at) VALUES('offline','codex_cli','thread-offline',0,?,?)", (now, now))
        finally:
            db.close()
        payload["target_actor_ids"] = ["offline"]
        with self.assertRaisesRegex(ValueError, "غير نشطة أو غير مهيأة"):
            create_command(self.path, payload)

    def test_board_marks_assignable_sessions(self):
        data = board(self.path)
        session = next(item for item in data["sessions"] if item["actor_id"] == "laser")
        self.assertEqual(session["dispatchable"], 1)
        self.assertIn("تسجيل المصادر والقيود", session["flow_responsibility"])

    def test_session_without_duty_profile_is_not_assignable(self):
        db = connect(self.path)
        try:
            now = utc_now()
            with db:
                db.execute("INSERT INTO coordination_actors(actor_id,display_name,active) VALUES('unprofiled','جلسة جديدة',1)")
                db.execute("INSERT INTO coordination_actor_endpoints(actor_id,provider_code,thread_id,enabled,created_at,updated_at) "
                           "VALUES('unprofiled','codex_cli','thread-new',1,?,?)", (now, now))
        finally:
            db.close()
        self.assertNotIn("unprofiled", {item["actor_id"] for item in board(self.path)["sessions"]})
        payload = self.payload()
        payload.update(target_actor_ids=["unprofiled"], idempotency_key="cmd-unprofiled-session")
        with self.assertRaisesRegex(ValueError, "غير نشطة أو غير مهيأة"):
            create_command(self.path, payload)

    def test_dispatch_prompt_loads_assigned_session_duties_from_database(self):
        create_command(self.path, self.payload())
        captured = {}

        def fake_runner(args, **kwargs):
            captured["message"] = args[-1]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        result = dispatch_one(self.path, codex_executable="codex", runner=fake_runner)
        self.assertEqual(result["state_code"], "sent")
        self.assertIn("مسؤوليتها في الفلو", captured["message"])
        self.assertIn("المخرجات المتوقعة منها", captured["message"])
        self.assertIn("العتاد الليزري والمواد والعمليات والسلامة والبرامج ومصادرها", captured["message"])
        self.assertIn("/api/workflow/proposals", captured["message"])
        self.assertIn("لا تنشئها ولا تحدد منفذها بنفسك", captured["message"])

    def test_review_lifecycle_completes_child_and_rolls_up_parent(self):
        payload = {"title": "مراجعة كود dashboard", "owner_request": "مراجعة كود dashboard وتقرير بالنتائج",
                   "scope": "مراجعة فقط", "idempotency_key": "cmd-review-lifecycle", "target_actor_ids": ["laser"]}
        result = create_command(self.path, payload)
        card_id = result["child_card_ids"][0]
        db = connect(self.path)
        try:
            card_type = db.execute("SELECT card_type_code FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()[0]
            self.assertEqual(card_type, "review")
        finally:
            db.close()
        transition_assigned_card(self.path, card_id, "laser", "in_progress")
        db = connect(self.path)
        try:
            now = utc_now()
            with db:
                db.execute("INSERT INTO coordination_quality_runs(card_id,profile_code,runner_name,runner_version,outcome,started_at,finished_at) VALUES(?,?,?,?,?,?,?)",
                           (card_id, "review", "unittest", "1", "conditional", now, now))
        finally:
            db.close()
        summary = "مراجعة مكتملة؛ سُجلت النتائج والفحوص، وبقيت توصيات مشروطة موضحة في التقرير."
        result_status = transition_assigned_card(self.path, card_id, "laser", "completed", summary)
        self.assertEqual(result_status["status_code"], "completed")
        self.assertEqual(transition_assigned_card(self.path, card_id, "laser", "completed", summary)["updated"], False)
        db = connect(self.path)
        try:
            statuses = dict(db.execute("SELECT card_id,current_status_code FROM coordination_cards"))
            self.assertEqual(statuses[result["root_card_id"]], "completed")
            self.assertEqual(statuses[card_id], "completed")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coordination_events WHERE card_id=? AND event_type='status_transition'", (card_id,)).fetchone()[0], 2)
            detail = card_details(self.path, card_id)
            self.assertEqual(detail["owner_command"]["card_id"], result["root_card_id"])
        finally:
            db.close()

    def test_implementation_card_cannot_be_closed_by_report_only(self):
        result = create_command(self.path, self.payload())
        card_id = result["child_card_ids"][0]
        transition_assigned_card(self.path, card_id, "laser", "in_progress")
        with self.assertRaisesRegex(ValueError, "إكمال بطاقة التنفيذ آلي"):
            transition_assigned_card(self.path, card_id, "laser", "completed", "مراجعة مكتملة مع نتائج مفصلة للفحص")

    def test_implementation_cannot_complete_before_github_merge_and_local_sync(self):
        result = create_command(self.path, self.payload())
        card_id = result["child_card_ids"][0]
        transition_assigned_card(self.path, card_id, "laser", "in_progress")
        db = connect(self.path)
        try:
            now = utc_now()
            criterion = db.execute("SELECT criterion_code FROM coordination_card_criteria WHERE card_id=? AND required=1", (card_id,)).fetchone()[0]
            with db:
                db.execute("""INSERT INTO coordination_delivery_attempts
                    (card_id,attempt_number,submitted_at,outcome,summary,branch_name,remote_name,commit_sha,remote_commit_sha,verified_at)
                    VALUES(?,1,?,'accepted','verified delivery','codex/test','origin',?,?,?)""",
                    (card_id, now, "a" * 40, "a" * 40, now))
                run_id = db.execute("""INSERT INTO coordination_quality_runs
                    (card_id,profile_code,runner_name,runner_version,outcome,started_at,finished_at)
                    VALUES(?,'focused','unittest','1','pass',?,?)""", (card_id, now, now)).lastrowid
                db.execute("INSERT INTO coordination_quality_checks(quality_run_id,check_code,outcome) VALUES(?,?,'pass')", (run_id, criterion))
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "مزامنة main"):
            transition_assigned_card(self.path, card_id, "laser", "completed", "تم الدفع والتحقق من جميع معايير الجودة المطلوبة بنجاح.")
        db = connect(self.path)
        try:
            transitions = [tuple(row) for row in db.execute("SELECT previous_status,next_status FROM coordination_events WHERE card_id=? AND event_type='status_transition' ORDER BY event_id", (card_id,))]
            self.assertEqual(transitions, [("assigned", "in_progress")])
            self.assertEqual(db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()[0], "in_progress")
        finally:
            db.close()

    def test_verified_delivery_and_quality_create_database_integration(self):
        result = create_command(self.path, self.payload())
        card_id = result["child_card_ids"][0]
        transition_assigned_card(self.path, card_id, "laser", "in_progress")
        sha = "a" * 40

        def git_result(args, **kwargs):
            if "ls-remote" in args:
                stdout = f"{sha}\trefs/heads/codex/card-delivery\n"
            elif "get-url" in args:
                stdout = "https://github.com/example/project.git\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(args, 0, stdout, "")

        with patch("workflow_api.subprocess.run", side_effect=git_result):
            delivery = submit_delivery(self.path, card_id, {
                "actor_id": "laser", "branch_name": "codex/card-delivery", "remote_name": "origin",
                "commit_sha": sha, "summary": "تم دفع التعديل المحدود إلى فرع البطاقة.",
                "changed_paths": ["docs/example.md"],
            })
        self.assertTrue(delivery["verified"])
        db = connect(self.path)
        try:
            criterion = db.execute("SELECT criterion_code FROM coordination_card_criteria WHERE card_id=? AND required=1", (card_id,)).fetchone()[0]
        finally:
            db.close()
        quality_body = {
            "actor_id": "laser", "attempt_id": delivery["attempt_id"], "commit_sha": sha,
            "outcome": "pass", "profile_code": "card_acceptance", "runner_name": "unittest",
            "runner_version": "1", "checks": [{"check_code": criterion, "outcome": "pass",
                                                      "evidence_ref": "docs/example.md"}],
        }
        with patch("workflow_api._github_repository", return_value="example/project"):
            quality = submit_quality(self.path, card_id, quality_body)
            duplicate = submit_quality(self.path, card_id, quality_body)
        self.assertTrue(quality["integration_queued"])
        self.assertTrue(duplicate["duplicate"])
        detail = card_details(self.path, card_id)
        self.assertEqual(detail["card"]["current_status_code"], "verifying")
        self.assertEqual(detail["git_integrations"][0]["state_code"], "pending")
        with self.assertRaisesRegex(ValueError, "مزامنة main"):
            transition_assigned_card(self.path, card_id, "laser", "completed", "تم الدفع والتحقق من جميع معايير الجودة المطلوبة بنجاح.")
        db = connect(self.path)
        try:
            transitions = [tuple(row) for row in db.execute("SELECT previous_status,next_status FROM coordination_events WHERE card_id=? AND event_type='status_transition' ORDER BY event_id", (card_id,))]
            self.assertEqual(transitions, [("assigned", "in_progress"), ("in_progress", "delivered"), ("delivered", "verifying")])
            self.assertEqual(db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?", (card_id,)).fetchone()[0], "verifying")
        finally:
            db.close()

    def test_session_cannot_transition_card_assigned_to_another_actor(self):
        result = create_command(self.path, self.payload())
        with self.assertRaisesRegex(ValueError, "ليست الجهة المسندة"):
            transition_assigned_card(self.path, result["child_card_ids"][0], "brainstorm", "in_progress")

    def test_owner_review_is_not_a_card_completion_criterion(self):
        payload = self.payload()
        payload["criteria"] = [
            {"criterion_code": "automated_check", "title": "الفحص الآلي", "check_method": "automated_quality_gate"},
            {"criterion_code": "owner_review", "title": "مراجعة المالك", "check_method": "owner_acceptance"},
            {"criterion_code": "manual_owner_step", "title": "خطوة المالك", "check_method": "owner_acceptance"},
        ]
        result = create_command(self.path, payload)
        db = connect(self.path)
        try:
            for card_id in result["child_card_ids"]:
                criteria = db.execute("SELECT criterion_code FROM coordination_card_criteria WHERE card_id=?", (card_id,)).fetchall()
                self.assertEqual([row[0] for row in criteria], ["automated_check"])
        finally:
            db.close()

    def test_criteria_templates_are_loaded_from_database_and_snapshotted_on_cards(self):
        catalog = criterion_catalog(self.path)["criteria"]
        template = next(item for item in catalog if item["criterion_code"] == "automated_delivery_qa")
        self.assertEqual(template["default_required"], 1)
        payload = self.payload()
        payload["criteria"] = [{"criterion_code": template["criterion_code"], "required": False}]
        result = create_command(self.path, payload)
        db = connect(self.path)
        try:
            for card_id in [result["root_card_id"], *result["child_card_ids"]]:
                row = db.execute("SELECT title,description,check_method,required FROM coordination_card_criteria WHERE card_id=? AND criterion_code=?",
                                 (card_id, template["criterion_code"])).fetchone()
                self.assertEqual(row[0], template["title"])
                self.assertEqual(row[1], template["description"])
                self.assertEqual(row[2], template["check_method"])
                self.assertEqual(row[3], 0)
        finally:
            db.close()

    def test_custom_owner_criterion_is_saved_as_card_specific_snapshot(self):
        payload = self.payload()
        payload["criteria"] = [{"title": "حفظ الروابط المرجعية", "description": "أرفق روابط جميع المراجع المستخدمة.",
                                 "check_method": "manual_evidence", "required": True}]
        result = create_command(self.path, payload)
        db = connect(self.path)
        try:
            for card_id in [result["root_card_id"], *result["child_card_ids"]]:
                row = db.execute("SELECT title,description,check_method,required,criterion_code FROM coordination_card_criteria WHERE card_id=?",
                                 (card_id,)).fetchone()
                self.assertEqual(tuple(row[:4]), ("حفظ الروابط المرجعية", "أرفق روابط جميع المراجع المستخدمة.", "manual_evidence", 1))
                self.assertTrue(row[4].startswith("custom_"))
        finally:
            db.close()

    def test_admin_audit_schema_is_created_by_migration(self):
        db = connect(self.path)
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_admin_audit'").fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coordination_git_integrations'").fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_criterion_catalog'").fetchone())
        finally:
            db.close()

    def test_board_counts_passing_quality_checks_once_per_criterion(self):
        db = connect(self.path)
        now = utc_now()
        try:
            with db:
                db.execute("INSERT INTO coordination_cards(card_id,title,owner_request,scope,status,created_at,updated_at) VALUES('CARD-1','Card','Request','Scope','in_progress',?,?)", (now, now))
                db.executemany("INSERT INTO coordination_card_criteria(card_id,criterion_code,title,created_at) VALUES('CARD-1',?,?,?)", [(f'criterion_{i}', f'Criterion {i}', now) for i in range(1, 7)])
                run_id = db.execute("INSERT INTO coordination_quality_runs(card_id,profile_code,runner_name,runner_version,outcome,started_at,finished_at) VALUES('CARD-1','focused','unittest','1','pass',?,?)", (now, now)).lastrowid
                db.executemany("INSERT INTO coordination_quality_checks(quality_run_id,check_code,outcome) VALUES(?,?,'pass')", [(run_id, f'criterion_{i}') for i in range(1, 6)])
                # Duplicate evidence for one criterion must not inflate the progress count.
                db.execute("INSERT INTO coordination_validation_results(card_id,outcome,criterion,recorded_at) VALUES('CARD-1','pass','criterion_1',?)", (now,))
            result = board(self.path)
            card = next(card for card in result['cards'] if card['card_id'] == 'CARD-1')
            self.assertEqual(card['criteria_total'], 6)
            self.assertEqual(card['criteria_passed'], 5)
        finally:
            db.close()

    def test_completed_owner_command_stays_visible_after_new_command_and_filters(self):
        completed = create_command(self.path, self.payload())
        db = connect(self.path)
        try:
            for card_id in [completed["root_card_id"], *completed["child_card_ids"]]:
                transition_card(
                    db,
                    card_id,
                    "completed",
                    actor_id="owner",
                    owner_actor_id="owner",
                    stage_code="verification",
                    note="Test completed command history.",
                    source_type="unittest",
                )
        finally:
            db.close()
        next_payload = self.payload()
        next_payload["idempotency_key"] = "cmd-next-after-completion"
        newer = create_command(self.path, next_payload)

        all_cards = board(self.path)
        summary = all_cards["completion_summary"]
        self.assertIn(completed["root_card_id"], {card["card_id"] for card in summary["completed_owner_commands"]})
        self.assertIn(completed["child_card_ids"][0], {card["card_id"] for card in all_cards["cards"]})
        self.assertIn(newer["child_card_ids"][0], {card["card_id"] for card in all_cards["cards"]})
        self.assertEqual(summary["owner_commands_completed"], 1)
        self.assertEqual(summary["session_cards_completed"], 1)
        self.assertEqual(summary["session_completions"][0]["completed_count"], 1)

        filtered = board(self.path, status="assigned")
        self.assertEqual(len(filtered["cards"]), 1)
        self.assertEqual(filtered["completion_summary"]["owner_commands_completed"], 1)
        self.assertEqual(len(filtered["completion_summary"]["completed_owner_commands"]), 1)

    def test_completed_and_terminal_groups_are_returned_independently_of_board_filters(self):
        db = connect(self.path)
        try:
            cards_by_status = {}
            for status in ("completed", "failed", "blocked", "archived"):
                payload = self.payload()
                payload["idempotency_key"] = f"terminal-{status}"
                result = create_command(self.path, payload)
                card_id = result["child_card_ids"][0]
                if status == "failed":
                    transition_card(db, card_id, "in_progress", actor_id="laser", stage_code="execution")
                transition_card(db, card_id, status, actor_id="owner", stage_code="owner_decision",
                                note="تحديث اختبار البطاقة", source_type="unittest")
                cards_by_status[status] = card_id
        finally:
            db.close()
        terminal_board = board(self.path, status="queued", actor_id="laser")
        group = next(item for item in terminal_board["session_history_groups"] if item["actor_id"] == "laser")
        self.assertEqual([item["card_id"] for item in group["cards"]], [cards_by_status["completed"]])
        for status, card_id in cards_by_status.items():
            if status == "completed":
                continue
            self.assertIn(card_id, {item["card_id"] for item in terminal_board["status_groups"][status]})

    def test_rejects_english_session_summary(self):
        result = create_command(self.path, self.payload())
        with self.assertRaisesRegex(ValueError, "باللغة العربية"):
            transition_assigned_card(self.path, result["child_card_ids"][0], "laser", "in_progress", "Starting implementation")


if __name__ == "__main__":
    unittest.main()
