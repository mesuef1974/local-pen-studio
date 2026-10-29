"""Serve the token dashboard and a read-only SQLite-backed API on loopback."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from usage_database import dashboard_data
from workflow_api import board as workflow_board, card_details, create_command, metrics as workflow_metrics


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
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/workflow/"):
            try:
                if parsed.path == "/api/workflow/board":
                    params = parse_qs(parsed.query)
                    data = workflow_board(self.database,
                        status=(params.get("status") or [""])[0],
                        actor_id=(params.get("actor_id") or [""])[0],
                        query=(params.get("q") or [""])[0].strip()[:200])
                elif parsed.path == "/api/workflow/metrics":
                    data = workflow_metrics(self.database)
                elif parsed.path.startswith("/api/workflow/cards/"):
                    card_id = parsed.path.removeprefix("/api/workflow/cards/")
                    data = card_details(self.database, card_id)
                    if data is None:
                        self._send_json(404, {"error": {"message": "البطاقة غير موجودة."}})
                        return
                else:
                    self._send_json(404, {"error": {"message": "مسار API غير موجود."}})
                    return
                self._send_json(200, data)
            except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
                self._send_json(503, {"error": {"message": f"تعذر قراءة بيانات مصنع البطاقات: {exc}"}})
            return
        if parsed.path != "/api/dashboard":
            return super().do_GET()
        try:
            payload = json.dumps(dashboard_data(self.database), ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
        except (OSError, RuntimeError, sqlite3.Error):
            self.send_error(503, "Dashboard database is not ready")
            return
        self._send_bytes(200, payload)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/workflow/commands":
            self._send_json(404, {"error": {"message": "مسار API غير موجود."}})
            return
        expected_origin = f"http://{self.headers.get('Host', '')}"
        if (self.headers.get("Origin") != expected_origin
                or self.headers.get("X-Workflow-Request") != "1"):
            self._send_json(403, {"error": {"message": "الطلب المحلي غير موثّق."}})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 128_000:
                raise ValueError("حجم الطلب غير صالح.")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("صيغة الأمر غير صالحة.")
            result = create_command(self.database, payload)
            self._send_json(201 if result.get("created") else 200, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": {"message": str(exc)}})
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            self._send_json(503, {"error": {"message": f"تعذر تسجيل الأمر في قاعدة البيانات: {exc}"}})

    def _send_json(self, status: int, data: dict) -> None:
        self._send_bytes(status, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _send_bytes(self, status: int, payload: bytes) -> None:
        self.send_response(status)
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
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    os.chdir(ROOT)
    handler = lambda *a, **kw: Handler(*a, database=args.database, **kw)
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
