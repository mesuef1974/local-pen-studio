from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coordination_repository import transition_card
from usage_database import connect, utc_now
from workflow_api import board, card_details, create_command, transition_assigned_card


class WorkflowCommandRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "usage.sqlite3"
        db = connect(self.path)
        now = utc_now()
        with db:
            db.execute("INSERT INTO coordination_actors(actor_id,display_name,charter,active) VALUES('owner','Owner','owner',1)")
            db.execute("INSERT INTO coordination_actors(actor_id,display_name,charter,active) VALUES('laser','Laser','frontend interface',1)")
            db.execute("INSERT INTO coordination_actor_endpoints(actor_id,provider_code,thread_id,enabled,created_at,updated_at) VALUES('laser','codex_cli','thread-laser',1,?,?)", (now, now))
            db.execute("INSERT INTO coordination_actor_capabilities(actor_id,capability) VALUES('laser','frontend')")
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def payload(self):
        return {"title": "Improve dashboard frontend interface", "owner_request": "Fix the dashboard UI", "scope": "HTML and CSS", "idempotency_key": "cmd-routing-1", "criteria": []}

    def test_routes_and_returns_compatible_child_id_fields(self):
        result = create_command(self.path, self.payload())
        self.assertEqual(result["child_card_ids"], result["session_card_ids"])
        db = connect(self.path)
        try:
            row = db.execute("SELECT assigned_actor_id FROM coordination_cards WHERE card_id=?", (result["child_card_ids"][0],)).fetchone()
            self.assertEqual(row[0], "laser")
            root = db.execute("SELECT current_status_code FROM coordination_cards WHERE card_id=?", (result["root_card_id"],)).fetchone()
            self.assertEqual(root[0], "assigned")
            self.assertEqual([card["card_id"] for card in board(self.path)["cards"]], result["child_card_ids"])
            retry = create_command(self.path, self.payload())
            self.assertFalse(retry["created"])
            self.assertEqual(retry["child_card_ids"], result["child_card_ids"])
        finally:
            db.close()

    def test_rejects_task_without_specialty_signal(self):
        payload = self.payload()
        payload.update(title="Work on something", owner_request="Please do it", scope="General", idempotency_key="cmd-routing-2")
        with self.assertRaisesRegex(ValueError, "لم تتضح تخصصات"):
            create_command(self.path, payload)

    def test_browser_cannot_override_backend_routing(self):
        payload = self.payload()
        payload["target_actor_ids"] = ["laser"]
        with self.assertRaisesRegex(ValueError, "يحدد المصنع الجلسة المختصة"):
            create_command(self.path, payload)

    def test_review_lifecycle_completes_child_and_rolls_up_parent(self):
        payload = {"title": "مراجعة كود dashboard", "owner_request": "مراجعة كود dashboard وتقرير بالنتائج",
                   "scope": "مراجعة فقط", "idempotency_key": "cmd-review-lifecycle"}
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
        with self.assertRaisesRegex(ValueError, "إثبات الدفع إلى origin"):
            transition_assigned_card(self.path, card_id, "laser", "completed", "مراجعة مكتملة مع نتائج مفصلة للفحص")

    def test_implementation_closes_after_verified_push_and_all_required_checks_pass(self):
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
        result_status = transition_assigned_card(self.path, card_id, "laser", "completed", "تم الدفع والتحقق من جميع معايير الجودة المطلوبة بنجاح.")
        self.assertEqual(result_status["status_code"], "completed")
        db = connect(self.path)
        try:
            transitions = [tuple(row) for row in db.execute("SELECT previous_status,next_status FROM coordination_events WHERE card_id=? AND event_type='status_transition' ORDER BY event_id", (card_id,))]
            self.assertEqual(transitions, [("assigned", "in_progress"), ("in_progress", "delivered"), ("delivered", "verifying"), ("verifying", "completed")])
        finally:
            db.close()

    def test_session_cannot_transition_card_assigned_to_another_actor(self):
        result = create_command(self.path, self.payload())
        with self.assertRaisesRegex(ValueError, "ليست الجهة المسندة"):
            transition_assigned_card(self.path, result["child_card_ids"][0], "brainstorm", "in_progress")

    def test_owner_review_is_not_a_card_completion_criterion(self):
        payload = self.payload()
        payload["criteria"] = [
            {"criterion_code": "automated_check", "title": "Automated check", "check_method": "automated_quality_gate"},
            {"criterion_code": "owner_review", "title": "Owner review", "check_method": "owner_acceptance"},
            {"criterion_code": "manual_owner_step", "title": "Owner step", "check_method": "owner_acceptance"},
        ]
        result = create_command(self.path, payload)
        db = connect(self.path)
        try:
            for card_id in result["child_card_ids"]:
                criteria = db.execute("SELECT criterion_code FROM coordination_card_criteria WHERE card_id=?", (card_id,)).fetchall()
                self.assertEqual([row[0] for row in criteria], ["automated_check"])
        finally:
            db.close()

    def test_admin_audit_schema_is_created_by_migration(self):
        db = connect(self.path)
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_admin_audit'").fetchone())
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


if __name__ == "__main__":
    unittest.main()
