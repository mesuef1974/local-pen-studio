"""Standalone three-stage local workspace. Reuses existing engines, no remote services."""
import argparse,hashlib,http.client,json,logging,logging.handlers,sys,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

ROOT=Path(__file__).resolve().parent
DRAW=ROOT.parent/'drawing-simulator';TRACE=ROOT.parent/'trace-studio'
# Tracebacks only (no request bodies): two rotated 512 KB files, created on the first failure.
LOG=logging.getLogger('flux-studio')
if not LOG.handlers:
    _handler=logging.handlers.RotatingFileHandler(ROOT/'server-errors.log',maxBytes=512_000,backupCount=2,encoding='utf-8',delay=True)
    _handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));LOG.addHandler(_handler);LOG.setLevel(logging.INFO)
sys.path[:0]=[str(TRACE),str(DRAW)]
import account_proxy,engine_pipe
ASSETS={'/':ROOT/'index.html','/prepare':ROOT/'index.html','/review':ROOT/'index.html','/adoption':ROOT/'platform-adoption.html','/paths':ROOT/'index.html','/output':ROOT/'index.html','/app.js':ROOT/'app.js','/webgpu-audit.js':ROOT/'webgpu-audit.js','/webgpu-path-raster.js':ROOT/'webgpu-path-raster.js','/workspace.css':ROOT/'workspace.css','/paper.js':ROOT/'paper.js','/workflow.js':ROOT/'workflow.js','/geometry.js':ROOT/'geometry.js','/sample-ink.png':ROOT/'sample-ink.png','/sample.png':DRAW/'photo-lineart-comparison/original.png','/sample-art.png':TRACE/'sample.png','/image-editor.js':DRAW/'image-editor.js','/image-editor.css':DRAW/'image-editor.css'}
ASSETS['/swot']=ROOT/'ui-swot-report-ar.html'
ASSETS['/swot-samples/horse-style-transfer.png']=ROOT/'reference-style-samples'/'horse-style-transfer.png'
ASSETS['/swot-samples/pen-style-transfer.png']=ROOT/'reference-style-samples'/'pen-style-transfer.png'
ASSETS['/swot-samples/coverage-cpu-gpu-1.png']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'visual-comparison'/'contact-sheet-1.png'
ASSETS['/swot-samples/coverage-cpu-gpu-2.png']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'visual-comparison'/'contact-sheet-2.png'
ASSETS['/gpu-cpu-measurement-2026-10-28/measurement-summary.json']=ROOT/'gpu-cpu-measurement-2026-10-28'/'measurement-summary.json'
ASSETS['/gpu-cpu-measurement-2026-10-28/filter-comparison/results.json']=ROOT/'gpu-cpu-measurement-2026-10-28'/'filter-comparison'/'results.json'
ASSETS['/gpu-cpu-measurement-2026-10-28/filter-comparison/cpu-bilateral.png']=ROOT/'gpu-cpu-measurement-2026-10-28'/'filter-comparison'/'cpu-bilateral.png'
ASSETS['/gpu-cpu-measurement-2026-10-28/filter-comparison/cuda-bilateral.png']=ROOT/'gpu-cpu-measurement-2026-10-28'/'filter-comparison'/'cuda-bilateral.png'
ASSETS['/gpu-cpu-measurement-2026-10-28/path-profile/results.json']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'results.json'
ASSETS['/gpu-cpu-measurement-2026-10-28/path-profile/largest-case-cprofile.txt']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'largest-case-cprofile.txt'
ASSETS['/gpu-cpu-measurement-2026-10-28/path-profile/cuda-results.json']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'cuda-results.json'
ASSETS['/gpu-cpu-measurement-2026-10-28/path-profile/webgpu-direct-fixed-heldout-comparison.json']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'webgpu-direct-fixed-heldout-comparison.json'
ASSETS['/gpu-cpu-measurement-2026-10-28/path-profile/benchmark_cuda_path.py']=ROOT/'gpu-cpu-measurement-2026-10-28'/'path-profile'/'benchmark_cuda_path.py'
GATE=threading.Lock()
CARD=engine_pipe.Card()
CARD_WAIT=15
ASSETS.update({'/session-gate.js':ROOT/'session-gate.js','/projects':ROOT/'projects.html','/projects.js':ROOT/'projects.js','/projects.css':ROOT/'projects.css','/account-api.js':ROOT/'account-api.js','/project-state.js':ROOT/'project-state.js','/project-session.js':ROOT/'project-session.js'})
ASSETS['/api-client.js']=ROOT/'api-client.js'
ASSETS['/job-queue.js']=ROOT/'job-queue.js'
ASSETS.update({'/tool-settings.js':ROOT/'tool-settings.js','/path-canvas.js':ROOT/'path-canvas.js'})
ASSETS.update({'/'+name:ROOT/name for name in ('plan-export.js','stage-metrics.js','fidelity-panel.js','paper-preview.js','laser-export.js','laser-template.js','theme.js','ui-text.js','lens.js','screens.css','output-stage.js','work-store.js','export-actions.js','laser-worker.js','work-gate.js','paths-stage.js','generation-stage.js')})
# Shared identity: index.html links ../typography.css, which imports the local font faces.
ASSETS.update({'/typography.css':ROOT.parent/'typography.css','/assets/fonts/fonts.css':ROOT.parent/'assets/fonts/fonts.css'})
ASSETS.update({f'/assets/fonts/{font.name}':font for font in (ROOT.parent/'assets/fonts').glob('*.woff2')})
ASSETS['/audit']=ROOT/'pipeline-review-ar.html'
for audit_asset in ['raw-flux.png','verified-paths.svg','verified-paths.json','review-results.json']:
    ASSETS['/pipeline-audit/'+audit_asset]=ROOT/'pipeline-audit'/audit_asset
ASSETS.update({'/flux-controls.js':ROOT/'flux-controls.js','/flux-prompts.js':ROOT/'flux-prompts.js','/flux-catalog.json':ROOT/'flux-catalog.json'})
# Brand identity delivered by Sima; icons sit at the root because site.webmanifest names them there.
BRAND=ROOT/'brand'/'masar'
ASSETS.update({'/'+name:BRAND/name for name in ('favicon.svg','favicon.ico','favicon-32.png','apple-touch-icon.png','icon-192.png','icon-512.png','maskable-512.png','site.webmanifest')})
ASSETS.update({'/brand/masar/identity/'+name:BRAND/'identity'/name for name in ('tokens/tokens.css','fonts/Almarai-Regular.ttf','fonts/Almarai-ExtraBold.ttf')})
# The Windows registry does not reliably know these types.
TYPES={'.woff2':'font/woff2','.ttf':'font/ttf','.svg':'image/svg+xml','.ico':'image/x-icon','.webmanifest':'application/manifest+json'}
from generation import Jobs
GENERATION=Jobs(GATE)

def content_type(kind):
    textual=kind.startswith('text/') or kind.endswith(('javascript','json','+json','+xml'))
    return kind+'; charset=utf-8' if textual else kind

def digest(image):return hashlib.sha256(image.encode()).hexdigest()

def process(path,data):
    if path=='/api/import':
        from preparation import import_image
        return import_image(data)
    if path=='/api/prepare':
        from preparation import prepare
        return prepare(data,require_transparency=False)|{'inputHash':digest(data.get('image',''))}
    if path=='/api/paths':
        if data.get('lineMode')=='faithful':
            from faithful_paths import extract
            return extract(data)|{'inputHash':digest(data.get('image',''))}
        from pen_paths import extract_paths
        return extract_paths(data)|{'inputHash':digest(data.get('image',''))}
    if path=='/api/path-audit':
        from path_fidelity import audit
        return audit(data)
    if path=='/api/path-audit-target':
        from path_fidelity import webgpu_target
        return webgpu_target(data)
    if path=='/api/editor':
        from editor_ops import operate
        return operate(data)
    if path=='/api/background':
        from preparation import remove_subject
        return {'image':remove_subject(data.get('image',''))}
    raise ValueError('مسار معالجة غير معروف.')

class Handler(SimpleHTTPRequestHandler):
    server_version='FluxStudio';sys_version=''
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
        if not head and account_proxy.matches(path):self.account('GET',path);return
        if path=='/api/status':self.reply(200,{'service':'flux-studio','stages':['flux-editing','image-approval','pen-paths'],'imageModel':'FLUX.2 Klein 4B Q5_K_M','optionalBackgroundModel':'BiRefNet','approvalRequired':True,'retiredEngines':['SDXL','Lineart']});return
        if path=='/api/generation':
            query=parse_qs(urlsplit(self.path).query)
            self.reply(200,GENERATION.status(job_id=query.get('job',[None])[0],summary=query.get('summary')==['1']));return
        file=ASSETS.get(path)
        if not file or not file.is_file():self.reply(404,{'error':'غير موجود.'});return
        raw=file.read_bytes();self.send_response(200);self.send_header('Content-Type',content_type(TYPES.get(file.suffix) or self.guess_type(str(file))));self.send_header('Content-Length',str(len(raw)));self.end_headers()
        if not head:self.wfile.write(raw)
    def account(self,method,path,body=None):
        try:status,headers,raw=account_proxy.forward(method,path,urlsplit(self.path).query,self.headers,body)
        except (OSError,http.client.HTTPException):self.reply(503,{'detail':'خادم الحسابات غير مشغَّل.','code':'accounts_unavailable'});return
        try:
            self.send_response(status)
            for name,value in headers:self.send_header(name,value)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
    def account_post(self,path):
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:size=-1
        if not 0<=size<=account_proxy.body_limit(path):self.refuse(413,'بيانات الطلب غير صالحة أو أكبر من الحد.');return
        try:body=self.rfile.read(size)
        except OSError:self.close_connection=True;return
        if len(body)<size:self.close_connection=True;return  # never forward a truncated body
        self.account('POST',path,body)
    def authorized(self):
        try:verdict=account_proxy.verify(self.headers)
        except (OSError,http.client.HTTPException):verdict=None
        if verdict==204:return True
        if verdict in (401,403):self.reply(verdict,{'error':'سجّل الدخول من «مشاريعي» ثم أعد المحاولة.','code':'auth_required'})
        else:self.reply(503,{'error':'خادم الحسابات غير مشغَّل؛ المعالجة تحتاج دخولًا.','code':'accounts_unavailable'})
        return False
    def do_GET(self):self.asset()
    def do_HEAD(self):self.asset(True)
    def refuse(self,status,message):
        # A reply sent before the body is read leaves it unread, and closing a socket with unread data makes Windows
        # reset the connection, which can reach the client before the reply does. A small body is read and dropped
        # first so the refusal arrives; a larger one is not read, and the connection closes after the reply.
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:size=-1
        if 0<=size<=65_536:
            try:self.rfile.read(size)
            except OSError:self.close_connection=True;return
        else:self.close_connection=True
        self.reply(status,{'error':message})
    def do_POST(self):
        port=self.server.server_port
        if not self.valid_host() or self.headers.get('Origin') not in {f'http://localhost:{port}',f'http://127.0.0.1:{port}'}:self.refuse(403,'افتح مساحة العمل المحلية.');return
        path=urlsplit(self.path).path
        if account_proxy.matches(path):self.account_post(path);return
        if path not in ['/api/import','/api/prepare','/api/paths','/api/path-audit','/api/path-audit-target','/api/editor','/api/background','/api/generate','/api/generation/cancel']:self.refuse(404,'غير موجود.');return
        size=None
        try:
            size=int(self.headers.get('Content-Length','0'))
            if self.headers.get_content_type()!='application/json' or not 0<size<=(22_000_000 if path in ['/api/import','/api/generate','/api/path-audit','/api/path-audit-target'] else 9_000_000):raise ValueError()
            raw=self.rfile.read(size);size=None
            # Nothing is parsed or computed before the account server accepts the session.
            if not self.authorized():return
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError()
        except (ValueError,UnicodeError,RecursionError):
            message='بيانات الطلب غير صالحة أو أكبر من الحد.'
            if size is None:self.reply(400,{'error':message})  # the body was read
            else:self.refuse(400,message)
            return
        except OSError:self.close_connection=True;return  # body shorter than declared or client gone
        if path=='/api/generation/cancel':
            # Only the page that holds the job id can cancel it; the id is never exposed without it.
            if not isinstance(data.get('job'),str):self.reply(400,{'error':'بيانات الطلب غير صالحة أو أكبر من الحد.'});return
            self.reply(200,GENERATION.cancel(data['job']));return
        if path=='/api/generate':
            try:self.reply(202,GENERATION.start(data))
            except BlockingIOError as error:self.reply(429,{'error':str(error)})
            except ValueError as error:self.reply(400,{'error':str(error)})
            return
        locked=path in ['/api/prepare','/api/paths','/api/path-audit','/api/path-audit-target','/api/background']
        if locked and not GATE.acquire(blocking=False):self.reply(429,{'error':'هناك معالجة محلية أخرى. أعد المحاولة بعد اكتمالها.'});return
        try:
            # Background removal runs its own GPU model; give it the VRAM a warm FLUX worker holds.
            if path=='/api/background':
                GENERATION.unload()
                if not CARD.borrow(CARD_WAIT):raise BlockingIOError('الكرت مشغول بمهمة توليد. أعد المحاولة بعد اكتمالها.')
            status,result=200,process(path,data)
        except BlockingIOError as error:status,result=429,{'error':str(error)}
        except ValueError as error:status,result=400,{'error':str(error)}
        except Exception:
            LOG.exception('processing failed: %s',path);status,result=500,{'error':'تعذرت المعالجة. جرّب إعدادات أخف أو دقة أصغر.'}
        finally:
            if path=='/api/background':CARD.release()
            if locked:GATE.release()
        # A cancelled/slow browser must not keep the compute gate locked while writing.
        try:self.reply(status,result)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):pass

class StudioServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second studio bind a port that is already being served.
    allow_reuse_address=sys.platform!='win32'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8770);args=parser.parse_args()
    server=StudioServer(('127.0.0.1',args.port),Handler);print(f'FLUX Studio: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.server_close()
        if GATE.acquire(timeout=5):GENERATION.unload()
