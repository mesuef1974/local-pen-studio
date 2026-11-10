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
SHARED_ASSETS = ROOT.parent.parent / "docs" / "coordination" / "assets"
IDENTITY_ASSETS = {
    "/identity.css": SHARED_ASSETS / "identity.css",
    "/fonts/cairo-arabic.woff2": SHARED_ASSETS / "fonts" / "cairo-arabic.woff2",
    "/fonts/ibm-plex-sans-arabic.woff2": SHARED_ASSETS / "fonts" / "ibm-plex-sans-arabic.woff2",
    "/fonts/manrope-latin.woff2": SHARED_ASSETS / "fonts" / "manrope-latin.woff2",
    "/fonts/plus-jakarta-sans-latin.woff2": SHARED_ASSETS / "fonts" / "plus-jakarta-sans-latin.woff2",
}
DEFAULT_DATABASE = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "usage-logs" / "usage.sqlite3"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, database: Path, **kwargs):
        self.database = database
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self._serve_identity_asset():
            return
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

    def do_HEAD(self):
        if self._serve_identity_asset(head_only=True):
            return
        return super().do_HEAD()

    def _serve_identity_asset(self, *, head_only: bool = False) -> bool:
        asset_path = IDENTITY_ASSETS.get(self.path.split("?", 1)[0])
        if asset_path is None:
            return False
        try:
            payload = asset_path.read_bytes()
        except OSError:
            self.send_error(404)
            return True
        content_type = "text/css; charset=utf-8" if asset_path.suffix == ".css" else "font/woff2"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)
        return True

    def log_message(self, format, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8772)
    args = parser.parse_args()
    os.chdir(ROOT)
    handler = lambda *a, **kw: Handler(*a, database=args.database, **kw)
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
