"""Serve the token dashboard and a read-only SQLite-backed API on loopback."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from usage_database import SCHEMA_VERSION, connect, dashboard_data
import workflow_service


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "usage-logs" / "usage.sqlite3"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, database: Path, **kwargs):
        self.database = database
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/health":
            try:
                db=self._connect()
                routes=db.execute("SELECT COUNT(*) FROM coordination_actor_endpoints WHERE enabled=1").fetchone()[0]
                pending=db.execute("SELECT COUNT(*) FROM coordination_outbox WHERE state_code IN ('pending','retry')").fetchone()[0]
                data={"version":1,"schema_version":SCHEMA_VERSION,"dispatcher_enabled":True,
                      "registered_sessions":routes,"queued_assignments":pending}
                return self._json(200,data)
            except (OSError,RuntimeError,sqlite3.Error) as exc:
                return self._json(503,{"error":{"code":"database_unavailable","message":str(exc)}})
            finally:
                if 'db' in locals(): db.close()
        if parsed.path == "/api/dashboard":
            try:
                payload = json.dumps(dashboard_data(self.database), ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")
            except (OSError, RuntimeError, sqlite3.Error):
                return self._json(503, {"error":{"code":"database_unavailable","message":"Dashboard database is not ready"}})
            return self._bytes(200, payload)
        if parsed.path not in {"/api/workflow/board", "/api/workflow/metrics"} and not parsed.path.startswith("/api/workflow/cards/"):
            return super().do_GET()
        try:
            db = self._connect()
            if parsed.path == "/api/workflow/board":
                query=parse_qs(parsed.query)
                data=workflow_service.board(db,status=query.get("status",[""])[0],actor_id=query.get("actor_id",[""])[0],q=query.get("q",[""])[0])
            elif parsed.path == "/api/workflow/metrics": data=workflow_service.metrics(db)
            else:
                card_id=parsed.path.removeprefix("/api/workflow/cards/")
                if not card_id or "/" in card_id: return self._json(404,{"error":{"code":"not_found","message":"Unknown route"}})
                data=workflow_service.detail(db,card_id)
            return self._json(200,data)
        except KeyError:
            return self._json(404,{"error":{"code":"not_found","message":"Card not found"}})
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            return self._json(503,{"error":{"code":"database_unavailable","message":str(exc)}})
        finally:
            if 'db' in locals(): db.close()

    def do_POST(self):
        if not self.path.startswith("/api/workflow/"):
            return self._json(404,{"error":{"code":"not_found","message":"Unknown route"}})
        if not self._same_origin(): return self._json(403,{"error":{"code":"request_origin_rejected","message":"Same-origin workflow requests only"}})
        try:
            length=int(self.headers.get("Content-Length","0"))
        except ValueError: return self._json(400,{"error":{"code":"invalid_length","message":"Invalid Content-Length"}})
        if length < 1 or length > 1_000_000: return self._json(413,{"error":{"code":"payload_size","message":"JSON body must be between 1 byte and 1 MB"}})
        if self.headers.get_content_type() != "application/json": return self._json(415,{"error":{"code":"content_type","message":"application/json required"}})
        try:
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError("JSON object required")
            parsed=urlsplit(self.path); db=self._connect()
            if parsed.path == "/api/workflow/commands":
                for field in ("idempotency_key","title","owner_request","scope"):
                    if not isinstance(body.get(field),str) or not body[field].strip(): raise ValueError(f"{field} is required")
                with db: data,created=workflow_service.create_command(db,body)
                return self._json(201 if created else 200,data)
            prefix="/api/workflow/cards/"
            if not parsed.path.startswith(prefix): return self._json(404,{"error":{"code":"not_found","message":"Unknown route"}})
            parts=parsed.path[len(prefix):].split("/")
            if len(parts)==4 and parts[1]=="deliveries" and parts[3]=="verify":
                with db: data=workflow_service.verify_delivery(db,parts[0],int(parts[2]))
                return self._json(200,data)
            if len(parts)==4 and parts[1]=="issues" and parts[3]=="resolve":
                with db: workflow_service.resolve_issue(db,parts[0],int(parts[2]),body)
                return self._json(200,{"resolved":True})
            if len(parts)!=2: return self._json(404,{"error":{"code":"not_found","message":"Unknown route"}})
            card_id,action=parts
            if action=="deliveries":
                with db: attempt=workflow_service.add_delivery(db,card_id,body)
                with db: verification=workflow_service.verify_delivery(db,card_id,attempt)
                return self._json(201,{"attempt_id":attempt,"created":True,"verification":verification})
            with db:
                if action=="events": result=workflow_service.add_event(db,card_id,body)
                elif action=="blockers": result=workflow_service.add_blocker(db,card_id,body)
                elif action=="quality-runs": result=workflow_service.add_quality_run(db,card_id,body)
                else: return self._json(404,{"error":{"code":"not_found","message":"Unknown route"}})
            return self._json(201,{"id":result,"created":True})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return self._json(400,{"error":{"code":"invalid_request","message":str(exc)}})
        except sqlite3.IntegrityError as exc:
            return self._json(409,{"error":{"code":"constraint_conflict","message":str(exc)}})
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            return self._json(503,{"error":{"code":"database_unavailable","message":str(exc)}})
        finally:
            if 'db' in locals(): db.close()

    def _connect(self):
        from usage_database import connect
        return connect(self.database)

    def _same_origin(self):
        if self.headers.get("X-Workflow-Request") != "1": return False
        host=self.headers.get("Host","")
        origin=self.headers.get("Origin","")
        return host in {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"} and origin in {f"http://{host}"}

    def _json(self,status,data):
        return self._bytes(status,json.dumps(data,ensure_ascii=False,separators=(",",":")).encode("utf-8"))

    def _bytes(self,status,payload):
        self.send_response(status)
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
    # Apply schema migrations once before the dispatcher thread and HTTP workers start.
    bootstrap=connect(args.database)
    bootstrap.close()
    handler = lambda *a, **kw: Handler(*a, database=args.database, **kw)
    server=ThreadingHTTPServer((args.host, args.port), handler)
    stop=threading.Event()
    from codex_session_dispatcher import dispatch_loop
    worker=threading.Thread(target=dispatch_loop,args=(args.database,stop),daemon=True,name="codex-session-outbox")
    worker.start()
    try: server.serve_forever()
    finally:
        stop.set(); server.server_close(); worker.join(timeout=3)


if __name__ == "__main__":
    main()
