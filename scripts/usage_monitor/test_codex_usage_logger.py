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
import usage_database
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

    def test_approved_identity_stylesheet_and_fonts_are_served(self):
        client = Client(HTTP_HOST="127.0.0.1")
        stylesheet = client.get("/identity.css")
        self.assertEqual(stylesheet.status_code, 200)
        stylesheet_content = b"".join(stylesheet.streaming_content)
        self.assertIn(b'font-family: "Cairo"', stylesheet_content)
        for font_name in ("cairo-arabic.woff2", "ibm-plex-sans-arabic.woff2",
                          "manrope-latin.woff2", "plus-jakarta-sans-latin.woff2"):
            with self.subTest(font=font_name):
                response = client.get(f"/fonts/{font_name}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "font/woff2")
                self.assertGreater(len(b"".join(response.streaming_content)), 1000)

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
        self.assertIsNotNone(data["freshness"]["context"]["observed_at"])
        self.assertIsNotNone(data["freshness"]["context"]["recorded_at"])
        self.assertEqual(data["freshness"]["weekly"]["observed_at"], data["weekly"]["timestamp"])
        self.assertIsNotNone(data["freshness"]["weekly"]["recorded_at"])
        self.assertEqual(data["freshness"]["collector"]["latest_run"]["status"], "success")
        self.assertEqual(self.fetchone("PRAGMA user_version")[0], usage_database.SCHEMA_VERSION)
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
        self.assertIn("coordination_actor_duties", tables)
        duties = self.fetchone("SELECT COUNT(*) FROM coordination_actor_duties")[0]
        self.assertEqual(duties, 4)
        self.assertGreater(
            len(self.fetchone("SELECT flow_responsibility FROM coordination_actor_duties "
                              "WHERE actor_id='laser'")[0]), 0)
        connection = connect(self.database)
        try:
            connection.execute("INSERT INTO coordination_actors(actor_id,display_name) VALUES('new-session','جلسة جديدة')")
            connection.execute("INSERT INTO coordination_actor_duties(actor_id,assignment_scope,flow_responsibility,"
                               "required_outputs,verification_guidance) VALUES(?,?,?,?,?)",
                               ("new-session", "اختصاص جديد", "مسؤولية محددة في الفلو", "مخرج موثق", "فحص وفق البطاقة"))
            self.assertEqual(connection.execute("SELECT assignment_scope FROM coordination_actor_duties "
                                                "WHERE actor_id='new-session'").fetchone()[0], "اختصاص جديد")
        finally:
            connection.close()
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
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], usage_database.SCHEMA_VERSION)
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

    def test_initial_scan_captures_early_event_in_large_transcript_and_reports_invalid_lines(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        with self.transcript.open("ab") as stream:
            stream.write(b"x" * (9 * 1024 * 1024) + b"\n")
        self.assertGreater(self.transcript.stat().st_size, 8 * 1024 * 1024)
        result = self.run_logger()
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_samples")[0], 1)
        self.assertEqual(result["samples_inserted"], 1)
        self.assertEqual(result["malformed_lines"], 1)
        run = self.fetchone("SELECT status,malformed_lines FROM usage_collector_runs ORDER BY run_id DESC LIMIT 1")
        self.assertEqual(tuple(run), ("success", 1))

    def test_older_collector_refuses_newer_database_schema_without_writing(self):
        connection = connect(self.database)
        connection.close()
        supported = usage_database.SCHEMA_VERSION
        try:
            usage_database.SCHEMA_VERSION = supported - 1
            with self.assertRaises(RuntimeError) as raised:
                connect(self.database)
            self.assertIn(str(supported - 1), str(raised.exception))
            self.assertIn(str(supported), str(raised.exception))
        finally:
            usage_database.SCHEMA_VERSION = supported
        self.assertEqual(self.fetchone("PRAGMA user_version")[0], supported)
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_collector_runs")[0], 0)

    def test_schema_nine_upgrade_preserves_quota_and_marks_old_record_time_unknown(self):
        older = self.root / "schema-nine.sqlite3"
        connection = sqlite3.connect(older)
        connection.executescript("""
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,
                checksum_sha256 TEXT NOT NULL,applied_at TEXT NOT NULL);
            CREATE TABLE usage_samples(sample_id INTEGER PRIMARY KEY,sampled_at TEXT NOT NULL,
                weekly_used_percent REAL,weekly_remaining_percent REAL,weekly_resets_at INTEGER,
                weekly_window_minutes INTEGER,weekly_plan_type TEXT);
            INSERT INTO usage_samples(sampled_at,weekly_used_percent,weekly_remaining_percent)
                VALUES('2026-10-29T12:00:00Z',31,69);
            PRAGMA user_version=9;
        """)
        connection.close()
        migrated = connect(older)
        try:
            row = migrated.execute("SELECT sampled_at,recorded_at,weekly_used_percent,weekly_remaining_percent "
                                   "FROM usage_samples").fetchone()
            self.assertEqual(tuple(row), ("2026-10-29T12:00:00Z", None, 31, 69))
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], usage_database.SCHEMA_VERSION)
            self.assertEqual(migrated.execute("SELECT COUNT(*) FROM usage_collector_runs").fetchone()[0], 0)
        finally:
            migrated.close()

    def test_two_writers_do_not_duplicate_the_same_sample(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        connect(self.database).close()

        def run_once():
            try:
                return self.run_logger()
            except RuntimeError as exc:
                # A concurrent run may be rejected by the collector lease. That is
                # the expected outcome; the winning run must still record the sample.
                self.assertIn("run_id=", str(exc))
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run_once(), range(2)))
        self.assertTrue(any(result is not None for result in results))
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_samples")[0], 1)

    def test_weekly_snapshot_rejects_out_of_range_and_non_finite_values(self):
        for value in (-1, 100.01, float("nan"), float("inf")):
            measured = logger.sample(self.usage(weekly=value), {})
            self.assertIsNotNone(measured)
            self.assertIsNone(measured["weekly"], msg=f"accepted invalid weekly value: {value}")
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}},
                        self.usage(weekly=101))
        self.run_logger()
        self.assertIsNone(self.fetchone("SELECT weekly_used_percent FROM usage_samples")[0])

    def test_database_rejects_inconsistent_weekly_snapshot_updates(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        self.run_logger()
        connection = connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE usage_samples SET weekly_used_percent=101 WHERE session_id=?",
                                   (self.session,))
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE usage_samples SET weekly_used_percent=NULL WHERE session_id=?",
                                   (self.session,))
            connection.rollback()
        finally:
            connection.close()

    def test_live_run_lease_prevents_interruption_and_duplicate_start(self):
        connection = connect(self.database)
        try:
            now = usage_database.utc_now()
            connection.execute(
                "INSERT INTO usage_collector_runs(started_at,heartbeat_at,status,collector_version,schema_version) "
                "VALUES(?,?,'running','4',12)", (now, now))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "تشغيل جامع نشط"):
            self.run_logger()
        row = self.fetchone("SELECT status FROM usage_collector_runs")
        self.assertEqual(row[0], "running")
        self.assertEqual(self.fetchone("SELECT COUNT(*) FROM usage_collector_runs")[0], 1)

    def test_expired_run_lease_is_marked_interrupted_before_new_run(self):
        connection = connect(self.database)
        try:
            connection.execute(
                "INSERT INTO usage_collector_runs(started_at,heartbeat_at,status,collector_version,schema_version) "
                "VALUES('2000-01-01T00:00:00+00:00','2000-01-01T00:00:00+00:00','running','4',12)")
            connection.commit()
        finally:
            connection.close()
        result = self.run_logger()
        self.assertEqual(result["run_id"], 2)
        self.assertEqual(self.fetchone("SELECT status FROM usage_collector_runs WHERE run_id=1")[0], "interrupted")
        self.assertEqual(self.fetchone("SELECT status FROM usage_collector_runs WHERE run_id=2")[0], "success")

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
