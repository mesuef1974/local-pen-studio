from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from usage_database import connect, utc_now
from workflow_api import create_command


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


if __name__ == "__main__":
    unittest.main()
