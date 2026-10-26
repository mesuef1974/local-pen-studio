"""Separate localhost page for the installed trace skill. Never exposes arbitrary paths."""
import argparse,json,mimetypes,re,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from processing import OUTPUT_FILES

ROOT=Path(__file__).resolve().parent
ASSETS={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/preparation-ui.js':'preparation-ui.js','/styles.css':'styles.css','/sample.png':'sample.png','/photo.png':'photo.png'}
GATE=threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):pass
    def host_ok(self):return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
    def end_headers(self):
        for k,v in {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():self.send_header(k,v)
        super().end_headers()
    def reply(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def route(self):
        path=urlsplit(self.path).path
        if path in ASSETS:return ASSETS[path]
        match=re.fullmatch(r'/output/([0-9a-f]{32})/(trace-(?:vector\.svg|master\.svg|preview\.png|validation\.json))',path)
        if match and match[2] in OUTPUT_FILES.values():return 'output/'+match[1]+'/'+match[2]
    def do_GET(self):
        if not self.host_ok():self.reply(403,{'error':'عنوان غير مسموح.'});return
        if urlsplit(self.path).path=='/api/status':self.reply(200,{'service':'trace-studio','skill':'trace-mascot-svg'});return
        if urlsplit(self.path).path=='/favicon.ico':self.send_response(204);self.end_headers();return
        target=self.route()
        if not target:self.reply(404,{'error':'غير موجود.'});return
        if target.startswith('output/'):
            file=ROOT/target
            if not file.is_file():self.reply(404,{'error':'النتيجة غير موجودة.'});return
            raw=file.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream');self.send_header('Content-Disposition',f'attachment; filename="{file.name}"');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        self.path='/'+target;super().do_GET()
    def do_HEAD(self):
        target=self.route()
        if not self.host_ok() or not target:self.send_error(404);return
        self.path='/'+target;super().do_HEAD()
    def do_POST(self):
        if not self.host_ok() or self.headers.get('Origin') not in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}:self.reply(403,{'error':'استخدم الصفحة المحلية.'});return
        if self.path not in ['/api/inspect','/api/grayscale','/api/trace','/api/import','/api/prepare']:self.reply(404,{'error':'غير موجود.'});return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=(22_000_000 if self.path=='/api/import' else 9_000_000):raise ValueError()
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError()
        except (ValueError,UnicodeError):self.reply(400,{'error':'بيانات الطلب غير صحيحة أو أكبر من الحد.'});return
        if not GATE.acquire(blocking=False):self.reply(429,{'error':'تريس ينفذ طلبًا الآن. انتظر ثم أعد المحاولة.'});return
        try:
            from processing import inspect,grayscale,run_trace
            from preparation import import_image,prepare
            action={'/api/inspect':inspect,'/api/grayscale':grayscale,'/api/trace':run_trace,'/api/import':import_image,'/api/prepare':prepare}[self.path]
            self.reply(200,action(data))
        except ValueError as error:self.reply(400,{'error':str(error)})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.reply(500,{'error':'تعذر إكمال تحويل تريس. جرّب تفضيلًا يحفظ تفاصيل أقل أو دقة أصغر.'})
        finally:GATE.release()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8767);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);print(f'Trace Studio: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
