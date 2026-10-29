"""Standalone three-stage local workspace. Reuses existing engines, no remote services."""
import argparse,hashlib,json,subprocess,sys,threading
from collections import OrderedDict
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
DRAW=ROOT.parent/'drawing-simulator';TRACE=ROOT.parent/'trace-studio'
sys.path[:0]=[str(TRACE),str(DRAW)]
ASSETS={'/':ROOT/'index.html','/prepare':ROOT/'index.html','/model':ROOT/'index.html','/paths':ROOT/'index.html','/app.js':ROOT/'app.js','/styles.css':ROOT/'styles.css','/workflow.js':ROOT/'workflow.js','/geometry.js':ROOT/'geometry.js','/sample.png':DRAW/'photo-lineart-comparison/original.png','/sample-art.png':TRACE/'sample.png','/image-editor.js':DRAW/'image-editor.js','/image-editor.css':DRAW/'image-editor.css'}
for _shared_name in ("typography.css", "assets/fonts/fonts.css", *[f"assets/fonts/{p.name}" for p in (ROOT.parent/"assets/fonts").glob("*.woff2")]):
    ASSETS["/" + _shared_name] = ROOT.parent / _shared_name

GATE=threading.Lock();MODEL_CACHE=OrderedDict()
from generation import Jobs
GENERATION=Jobs(GATE)

def digest(image):return hashlib.sha256(image.encode()).hexdigest()

def infer(data):
    from lineart_processing import decode
    decode(data.get('image'))
    resolution=data.get('resolution',768)
    if isinstance(resolution,bool) or resolution not in [512,768,1024]:raise ValueError('اختر دقة 512 أو 768 أو 1024.')
    key=digest(data['image']+'|'+str(resolution))
    if key in MODEL_CACHE:
        MODEL_CACHE.move_to_end(key);return MODEL_CACHE[key]|{'cached':True}
    payload={'image':data['image'],'model':'realistic','resolution':resolution}
    try:
        result=subprocess.run([str(DRAW/'.venv-lineart/Scripts/python.exe'),str(DRAW/'lineart_service.py')],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):raise ValueError('تعذر تشغيل النموذج الدقيق أو انتهت مهلته. جرّب دقة أصغر.')
    try:output=json.loads(result.stdout)
    except ValueError:raise ValueError('استجابة النموذج غير صالحة.')
    if result.returncode or output.get('error'):raise ValueError(output.get('error','تعذر تشغيل النموذج الدقيق.'))
    output.update(inputHash=digest(data['image']),cached=False)
    MODEL_CACHE[key]=output
    while len(MODEL_CACHE)>2:MODEL_CACHE.popitem(last=False)
    return output

def process(path,data):
    if path=='/api/import':
        from preparation import import_image
        return import_image(data)
    if path=='/api/prepare':
        from preparation import prepare
        return prepare(data,require_transparency=False)|{'inputHash':digest(data.get('image',''))}
    if path=='/api/model':return infer(data)
    if path=='/api/post':
        from lineart_processing import process as post
        return post(data|{'action':'post'})
    if path=='/api/paths':
        from pen_paths import extract_paths
        return extract_paths(data)|{'inputHash':digest(data.get('image',''))}
    if path=='/api/editor':
        from editor_ops import operate
        return operate(data)
    if path=='/api/background':
        from preparation import remove_subject
        return {'image':remove_subject(data.get('image',''))}
    raise ValueError('مسار معالجة غير معروف.')

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def setup(self):
        super().setup();self.connection.settimeout(30)
    def log_message(self,*args):pass
    def valid_host(self):return self.headers.get('Host') in {f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}'}
    def end_headers(self):
        for k,v in {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():self.send_header(k,v)
        super().end_headers()
    def reply(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def asset(self,head=False):
        if not self.valid_host():self.reply(403,{'error':'عنوان المضيف غير مسموح.'});return
        path=urlsplit(self.path).path
        if path=='/api/status':self.reply(200,{'service':'pipeline-studio','stages':['preparation','precise-lineart','pen-paths']});return
        if path=='/api/generation':self.reply(200,GENERATION.status());return
        if path=='/favicon.ico':self.send_response(204);self.end_headers();return
        file=ASSETS.get(path)
        if not file or not file.is_file():self.reply(404,{'error':'غير موجود.'});return
        raw=file.read_bytes();self.send_response(200);self.send_header('Content-Type',self.guess_type(str(file)));self.send_header('Content-Length',str(len(raw)));self.end_headers()
        if not head:self.wfile.write(raw)
    def do_GET(self):self.asset()
    def do_HEAD(self):self.asset(True)
    def do_POST(self):
        port=self.server.server_port
        if not self.valid_host() or self.headers.get('Origin') not in {f'http://localhost:{port}',f'http://127.0.0.1:{port}'}:self.reply(403,{'error':'افتح مساحة العمل المحلية.'});return
        path=urlsplit(self.path).path
        if path not in ['/api/import','/api/prepare','/api/model','/api/post','/api/paths','/api/editor','/api/background','/api/generate']:self.reply(404,{'error':'غير موجود.'});return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if self.headers.get_content_type()!='application/json' or not 0<size<=(22_000_000 if path=='/api/import' else 9_000_000):raise ValueError()
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError()
        except (ValueError,UnicodeError):self.reply(400,{'error':'بيانات الطلب غير صالحة أو أكبر من الحد.'});return
        if path=='/api/generate':
            try:self.reply(202,GENERATION.start(data))
            except BlockingIOError as error:self.reply(429,{'error':str(error)})
            except ValueError as error:self.reply(400,{'error':str(error)})
            return
        locked=path in ['/api/prepare','/api/model','/api/paths','/api/background']
        if locked and not GATE.acquire(blocking=False):self.reply(429,{'error':'هناك معالجة محلية أخرى. أعد المحاولة بعد اكتمالها.'});return
        try:status,result=200,process(path,data)
        except ValueError as error:status,result=400,{'error':str(error)}
        except Exception:status,result=500,{'error':'تعذرت المعالجة. جرّب إعدادات أخف أو دقة أصغر.'}
        finally:
            if locked:GATE.release()
        # A cancelled/slow browser must not keep the compute gate locked while writing.
        try:self.reply(status,result)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8769);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);print(f'Pipeline Studio: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
