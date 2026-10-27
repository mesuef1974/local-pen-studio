import json
import tempfile
import unittest
from pathlib import Path

import codex_usage_logger as logger


class UsageLoggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions/2026/10/27"
        self.sessions.mkdir(parents=True)
        self.transcript = self.sessions / "rollout-test.jsonl"
        self.index = self.root / "session_index.jsonl"
        self.output = self.root / "output"
        self.state = self.root / "state.json"
        self.session = "00000000-0000-7000-8000-000000000001"
        self.index.write_text(json.dumps({"id": self.session, "thread_name": "جلسة اختبار"}) + "\n")

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, *rows):
        with self.transcript.open("a", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")

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

    def test_records_named_session_model_context_and_weekly_usage(self):
        self.write_rows(
            {"type": "session_meta", "payload": {"session_id": self.session,
                                                    "timestamp": "2026-10-27T00:00:00Z"}},
            {"type": "event_msg", "payload": {"type": "thread_settings_applied",
             "thread_settings": {"model": "gpt-6-luna", "reasoning_effort": "low",
                                 "service_tier": "default"}}},
            self.usage())
        result = logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        self.assertEqual(result["sessions_updated"], 1)
        path = next(self.output.glob(f"*--{self.session}.json"))
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["session_name"], "جلسة اختبار")
        current = document["samples"][0]
        self.assertEqual((current["model"], current["reasoning_effort"]), ("gpt-6-luna", "low"))
        self.assertEqual(current["context"]["used_percent"], 25.0)
        self.assertEqual(current["weekly"]["remaining_percent"], 82)

    def test_incremental_runs_do_not_duplicate_samples(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        self.write_rows(self.usage(total=80, cumulative=2000, weekly=19))
        logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        document = json.loads(next(self.output.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(len(document["samples"]), 2)
        self.assertEqual(document["samples"][-1]["weekly"]["used_percent"], 19)

    def test_ignores_initial_token_event_without_usage_info(self):
        self.write_rows(
            {"type": "session_meta", "payload": {"session_id": self.session}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
            self.usage())
        result = logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        self.assertEqual(result["sessions_updated"], 1)
        document = json.loads(next(self.output.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(len(document["samples"]), 1)

    def test_tracks_multiple_rollout_files_for_one_session_independently(self):
        self.write_rows({"type": "session_meta", "payload": {"session_id": self.session}}, self.usage())
        second = self.sessions / "rollout-second.jsonl"
        second.write_text("\n".join(json.dumps(row) for row in (
            {"type": "session_meta", "payload": {"session_id": self.session}},
            self.usage(total=80, cumulative=2000, weekly=19))) + "\n", encoding="utf-8")
        first = logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        second_run = logger.run(self.sessions.parents[2], self.index, self.output, self.state)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual((first["sessions_updated"], first["sessions_known"]), (1, 1))
        self.assertEqual(second_run["sessions_updated"], 0)
        self.assertEqual(len(state["files"]), 2)
        document = json.loads(next(self.output.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(len(document["samples"]), 2)


if __name__ == "__main__":
    unittest.main()
