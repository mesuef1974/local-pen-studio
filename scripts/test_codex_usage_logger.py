"""Compatibility test entry point for the SQLite-backed usage monitor."""

from pathlib import Path
import importlib.util
import sys

usage_monitor = Path(__file__).resolve().parent / "usage_monitor"
sys.path.insert(0, str(usage_monitor))

spec = importlib.util.spec_from_file_location(
    "usage_monitor_test_suite", usage_monitor / "test_codex_usage_logger.py")
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)
UsageLoggerTests = suite.UsageLoggerTests

# unittest discovery still loads the imported TestCase; pytest collects the nested file once.
UsageLoggerTests.__test__ = False
