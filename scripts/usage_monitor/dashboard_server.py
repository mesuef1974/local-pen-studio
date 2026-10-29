"""Compatibility entry point for the Django-backed local dashboard."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "usage-logs" / "usage.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard_project.settings")
    os.environ["USAGE_DATABASE"] = str(args.database.expanduser().resolve())

    # Apply additive usage/workflow schema migrations before the admin or API starts.
    from usage_database import connect
    database = connect(args.database.expanduser().resolve())
    database.close()

    from django.core.management import execute_from_command_line

    execute_from_command_line([
        "manage.py", "runserver", f"{args.host}:{args.port}", "--noreload",
    ])


if __name__ == "__main__":
    main()
