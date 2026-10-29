"""Backward-compatible entry point for the SQLite-backed usage logger."""

from pathlib import Path
import sys

usage_monitor = Path(__file__).resolve().parent / "usage_monitor"
sys.path.insert(0, str(usage_monitor))

from codex_usage_logger import main  # noqa: E402


if __name__ == "__main__":
    main()
