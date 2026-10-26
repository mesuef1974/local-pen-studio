"""Standalone localhost-only OpenCV workspace, independent of the drawing app."""
import argparse
import json
import threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
ASSETS={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/styles.css':'styles.css','/sample.png':'sample.png'}
GATE=threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):pass
    def host_ok(self):return self.headers.get('Host') in {f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}'}
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()
    def reply(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if not self.host_ok():self.reply(403,{'error':'عنوان محلي غير مسموح.'});return
        path=urlsplit(self.path).path
        if path=='/api/status':self.reply(200,{'service':'edge-studio'});return
        if path=='/favicon.ico':self.send_response(204);self.end_headers();return
        if path not in ASSETS:self.reply(404,{'error':'الصفحة غير موجودة.'});return
        self.path='/'+ASSETS[path];super().do_GET()
    def do_HEAD(self):
        if not self.host_ok() or urlsplit(self.path).path not in ASSETS:self.send_error(404);return
        self.path='/'+ASSETS[urlsplit(self.path).path];super().do_HEAD()
    def do_POST(self):
        if not self.host_ok() or self.headers.get('Origin') not in {f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'}:
            self.reply(403,{'error':'افتح الصفحة من السيرفر المحلي.'});return
        if self.path!='/api/edges':self.reply(404,{'error':'غير موجود.'});return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=9_000_000:raise ValueError('حجم الطلب غير مناسب.')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('طلب غير صحيح.')
        except (ValueError,UnicodeError):self.reply(400,{'error':'بيانات الطلب غير صحيحة أو تتجاوز الحجم المسموح.'});return
        if not GATE.acquire(blocking=False):self.reply(429,{'error':'هناك معالجة أخرى؛ أعد المحاولة بعد اكتمالها.'});return
        try:
            from processing import process
            self.reply(200,process(data))
        except ValueError as error:self.reply(400,{'error':str(error)})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.reply(500,{'error':'تعذرت المعالجة. جرّب دقة أقل أو طريقة أخرى.'})
        finally:GATE.release()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Edge Studio: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
