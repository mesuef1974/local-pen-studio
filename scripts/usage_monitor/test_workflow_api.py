from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from usage_database import connect, utc_now
from workflow_api import board, create_command


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

    def test_admin_audit_schema_is_created_by_migration(self):
        db = connect(self.path)
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
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


if __name__ == "__main__":
    unittest.main()
