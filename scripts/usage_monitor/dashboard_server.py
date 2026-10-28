"""Serve the token dashboard and a read-only SQLite-backed API on loopback."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from usage_database import dashboard_data


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "usage-logs" / "usage.sqlite3"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, database: Path, **kwargs):
        self.database = database
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/api/dashboard":
            return super().do_GET()
        try:
            payload = json.dumps(dashboard_data(self.database), ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
        except (OSError, RuntimeError, sqlite3.Error):
            self.send_error(503, "Dashboard database is not ready")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    os.chdir(ROOT)
    handler = lambda *a, **kw: Handler(*a, database=args.database, **kw)
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
