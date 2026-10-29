import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard_project.settings")
import django
django.setup()

from django.test import Client, override_settings

import codex_usage_logger as logger
from usage_database import SCHEMA_V1, connect, dashboard_data, insert_sample
from backup_usage_database import backup
from coordination_repository import (assign_card, create_card, record_delivery_attempt,
                                     record_issue, record_opinion, record_owner_decision,
                                     record_validation, transition_card, upsert_actor)


class UsageLoggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions/2026/10/27"
        self.sessions.mkdir(parents=True)
        self.transcript = self.sessions / "rollout-test.jsonl"
        self.index = self.root / "session_index.jsonl"
        self.legacy = self.root / "legacy-sessions"
        self.legacy.mkdir()
        self.state = self.root / "state.json"
        self.database = self.root / "usage.sqlite3"
        self.session = "00000000-0000-7000-8000-000000000001"
        self.index.write_text(json.dumps({"id": self.session, "thread_name": "جلسة اختبار"}) + "\n",
                              encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def usage(self, total=50, cumulative=1000, weekly=18):
        def tokens(value):
            return {"input_tokens": value - 10, "cached_input_tokens": value - 20,
                    "cache_write_input_tokens": 0, "output_tokens": 10,
                    "reasoning_output_tokens": 2, "total_tokens": value}
        return {"timestamp": f"2026-10-27T00:00:{cumulative % 60:02d}Z", "type": "event_msg",
                "payload": {"type": "token_count", "info": {
                    "last_token_usage": tokens(total), "total_token_usage": tokens(cumulative),
                    "model_context_window": 200}, "rate_limits": {"plan_type": "prolite",
                    "primary": {"used_percent": weekly, "window_minutes": 10080,
                                "resets_at": 1793696221}}}}

    def write_rows(self, *rows):
        with self.transcript.open("a", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")

    def run_logger(self):
        return logger.run(self.sessions.parents[2], self.index, self.database, self.legacy, self.state)

    def fetchone(self, query, parameters=()):
        connection = connect(self.database)
        try:
            return connection.execute(query, parameters).fetchone()
        finally:
            connection.close()

    def test_records_metrics_and_dashboard_reads_database(self):
        self.write_rows(
            {"type": "session_meta", "payload": {"session_id": self.session,
                                                    "timestamp": "2026-10-27T00:00:00Z"}},
            {"type": "event_msg", "payload": {"type": "thread_settings_applied",
             "thread_settings": {"model": "gpt-6-luna", "reasoning_effort": "low",
                                 "service_tier": "default"}}},
            self.usage())
        result = self.run_logger()
        self.assertEqual(result["sessions_updated"], 1)
        data = dashboard_data(self.database)
        self.assertEqual(data["sessions"][0]["session_name"], "جلسة اختبار")
        self.assertEqual(data["sessions"][0]["model"], "gpt-6-luna")
        self.assertEqual(data["sessions"][0]["samples"][0]["context"]["used_percent"], 25)
        self.assertEqual(data["weekly"]["remaining_percent"], 82)
        self.assertEqual(self.fetchone("PRAGMA user_version")[0], 9)
        connection = connect(self.database)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            sample_fields = {row[1] for row in connection.execute("PRAGMA table_info(usage_samples)")}
        finally:
            connection.close()
        self.assertIn("coordination_cards", tables)
        self.assertIn("coordination_opinions", tables)
        self.assertIn("owner_decisions", tables)
        self.assertIn("coordination_deliverables", tables)
        self.assertIn("usage_samples", tables)
        self.assertIn("coordination_card_id", sample_fields)
        self.assertIn("workflow_stage_code", sample_fields)
        self.assertEqual(tuple(self.fetchone("SELECT coordination_card_id,workflow_stage_code FROM usage_samples")),
                         (None, None))
        self.assertIn("usage_sources", tables)
        self.assertIn("coordination_assignments", tables)
        self.assertIn("coordination_validation_results", tables)
        self.assertIn("coordination_issues", tables)
        self.assertIn("owner_decision_history", tables)
        self.assertIn("coordination_opinion_history", tables)

    def test_v1_database_upgrades_without_losing_data_and_event_log_is_append_only(self):
        legacy_db = self.root / "version-one.sqlite3"
        connection = sqlite3.connect(legacy_db)
        connection.executescript(SCHEMA_V1)
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO usage_sessions(session_id,session_name) VALUES('kept','بيانات سابقة')")
        connection.commit()
        connection.close()

        connection = connect(legacy_db)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 9)
            self.assertEqual(connection.execute("SELECT session_name FROM usage_sessions WHERE session_id='kept'").fetchone()[0],
                             "بيانات سابقة")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=2").fetchone()[0], 1)
            connection.execute("INSERT INTO coordination_actors(actor_id,display_name) VALUES('owner','المالك')")
            connection.execute("INSERT INTO coordination_cards(card_id,title,owner_request,scope,status,created_at,updated_at) "
                               "VALUES('CARD-1','اختبار','طلب','نطاق','accepted','2026-10-28T00:00:00Z','2026-10-28T00:00:00Z')")
            connection.execute("INSERT INTO coordination_events(card_id,event_type,details,recorded_at,actor_id,owner_actor_id, "
                               "previous_status,next_status,stage_code,reason_code,reason_resolution,source_type,sensitivity) "
                               "VALUES('CARD-1','accepted','استلام','2026-10-28T00:00:01Z','owner','owner','draft','accepted', "
                               "'intake','unknown','unresolved','owner_card','internal')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE coordination_events SET details='تعديل صامت'")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM coordination_events")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM coordination_events").fetchone()[0], 1)
        finally:
            connection.close()

    def test_coordination_repository_records_flow_and_preserves_event_history(self):
        connection = connect(self.database)
        try:
            upsert_actor(connection, "owner", "المالك")
            upsert_actor(connection, "coordinator", "عصف ذهني")
            upsert_actor(connection, "laser", "ليزر")
            create_card(connection, card_id="FLOW-1", title="بطاقة اختبار",
                        owner_request="سجل أحداث منظم", scope="نطاق تجريبي",
                        coordinator_actor_id="coordinator", owner_actor_id="owner")
            linked_sample = logger.sample(self.usage(), {})
            linked_sample["coordination_card_id"] = "FLOW-1"
            linked_sample["workflow_stage_code"] = "execution"
            self.assertTrue(insert_sample(connection, self.session, "جلسة اختبار", None, linked_sample))
            transition_card(connection, "FLOW-1", "in_progress", actor_id="coordinator",
                            owner_actor_id="owner", stage_code="execution")
            assign_card(connection, "FLOW-1", "laser", assigned_by_actor_id="coordinator",
                        owner_actor_id="owner", reason_code="scope_mismatch")
            record_opinion(connection, "FLOW-1", "laser", "رأي استشاري موجز", "SQLite محلية")
            record_owner_decision(connection, "FLOW-1", "architecture", "sqlite_local_api",
                                  owner_actor_id="owner", notes="اعتماد التوجه المحلي")
            record_issue(connection, "FLOW-1", stage_code="verification", cause_resolution="unresolved",
                         impact_summary="سجل تعثر تجريبي", cause_code="unknown", actor_id="laser")
            attempt_id = record_delivery_attempt(connection, "FLOW-1",
                                                 submitted_by_actor_id="laser", summary="محاولة تسليم")
            record_validation(connection, "FLOW-1", outcome="pass", criterion="الفحوص",
                              evidence_ref="test-output", validator_actor_id="coordinator",
                              attempt_id=attempt_id)
            current = connection.execute("SELECT current_status_code FROM coordination_cards WHERE card_id='FLOW-1'").fetchone()[0]
            self.assertEqual(current, "in_progress")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM coordination_events WHERE card_id='FLOW-1'").fetchone()[0], 8)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM coordination_opinion_history").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM owner_decision_history").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT cause_resolution FROM coordination_issues").fetchone()[0], "unresolved")
            self.assertEqual(tuple(connection.execute("SELECT coordination_card_id,workflow_stage_code "
                                                       "FROM usage_samples").fetchone()),
                             ("FLOW-1", "execution"))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE coordination_cards SET current_status_code='completed' WHERE card_id='FLOW-1'")
        finally:
            connection.close()

    def test_terminal_status_closes_active_assignment(self):
        connection = connect(self.database)
        try:
            upsert_actor(connection, "laser", "ليزر")
            create_card(connection, card_id="FLOW-TERMINAL", title="بطاقة نهائية",
                        owner_request="طلب", scope="نطاق", status_code="assigned",
                        assigned_actor_id="laser")
            transition_card(connection, "FLOW-TERMINAL", "completed", actor_id=None,
                            stage_code="quality", note="اكتملت الفحوص الآلية")
            assignment = connection.execute(
                "SELECT ended_at FROM coordination_assignments WHERE card_id='FLOW-TERMINAL'"
            ).fetchone()
            self.assertIsNotNone(assignment[0])
        finally:
            connection.close()

    def test_incremental_runs_are_idempotent(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        self.run_logger()
        self.run_logger()
        self.write_rows(self.usage(), self.usage(total=80, cumulative=2000, weekly=19))
        result = self.run_logger()
        self.assertEqual(result["sessions_updated"], 1)
        count = self.fetchone("SELECT COUNT(*) FROM usage_samples")[0]
        self.assertEqual(count, 2)

    def test_imports_legacy_json_and_cursors_once_without_modifying_sources(self):
        item = {"session_id": self.session, "session_name": "جلسة قديمة",
                "created_at": "2026-10-27T00:00:00Z", "samples": [
                logger.sample(self.usage(), {})]}
        legacy_file = self.legacy / "session.json"
        legacy_file.write_text(json.dumps(item), encoding="utf-8")
        original = legacy_file.read_bytes()
        self.state.write_text(json.dumps({"files": {"C:/rollout.jsonl": {
            "session_id": self.session, "offset": 123,
            "settings": {"model": "gpt-6-luna", "reasoning_effort": "low"}}}}), encoding="utf-8")
        first = self.run_logger()
        second = self.run_logger()
        self.assertEqual((first["legacy_samples"], first["legacy_cursors"]), (1, 1))
        self.assertEqual((second["legacy_samples"], second["legacy_cursors"]), (0, 0))
        self.assertEqual(legacy_file.read_bytes(), original)
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_samples")[0], 1)
        self.assertEqual(self.fetchone("SELECT offset_bytes FROM usage_sources")[0], 123)

    def test_incomplete_jsonl_line_is_reprocessed_when_completed(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}})
        with self.transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self.usage()))
        self.run_logger()
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_samples")[0], 0)
        with self.transcript.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        self.run_logger()
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_samples")[0], 1)

    def test_two_writers_do_not_duplicate_the_same_sample(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        connect(self.database).close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.run_logger(), range(2)))
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_samples")[0], 1)

    def test_dashboard_api_serves_database_data_on_loopback(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        self.run_logger()
        with override_settings(USAGE_DATABASE=self.database):
            response = Client(HTTP_HOST="127.0.0.1").get("/api/dashboard")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Content-Type", "").split(";")[0], "application/json")
            payload = response.json()
        self.assertEqual(payload["sessions"][0]["session_id"], self.session)
        self.assertEqual(len(payload["sessions"][0]["samples"]), 1)

    def test_backup_api_produces_integral_copy(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        self.run_logger()
        target = backup(self.database, self.root / "backups")
        self.assertTrue(target.is_file())
        connection = sqlite3.connect(target)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM usage_samples").fetchone()[0], 1)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
