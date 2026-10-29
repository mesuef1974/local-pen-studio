"""Compatibility entry point for the Django-backed local dashboard."""

from __future__ import annotations

import argparse
import os
import threading
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
    os.environ["WORKFLOW_BASE_URL"] = f"http://{args.host}:{args.port}"

    # Apply additive usage/workflow schema migrations before the admin or API starts.
    from usage_database import connect
    database = connect(args.database.expanduser().resolve())
    database.close()

    from django.core.management import execute_from_command_line

    from codex_session_dispatcher import dispatch_loop
    from git_integration_worker import integration_loop
    stop_dispatcher = threading.Event()
    dispatcher = threading.Thread(target=dispatch_loop, args=(args.database.expanduser().resolve(), stop_dispatcher),
                                  name="workflow-outbox-dispatcher", daemon=True)
    dispatcher.start()
    integrator = threading.Thread(target=integration_loop,
                                  args=(args.database.expanduser().resolve(), stop_dispatcher),
                                  name="workflow-git-integration", daemon=True)
    integrator.start()
    try:
        execute_from_command_line([
            "manage.py", "runserver", f"{args.host}:{args.port}", "--noreload",
        ])
    finally:
        stop_dispatcher.set()
        dispatcher.join(timeout=10)
        integrator.join(timeout=10)


if __name__ == "__main__":
    main()
