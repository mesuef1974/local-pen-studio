"""Validated FLUX jobs; same image-review contract as the existing workspace."""
import base64
import copy
import io
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from PIL import Image
from setup_flux import MODEL_DIR, MODEL_ID, REVISION, QUANT_FILE

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('flux-studio')
sys.path.insert(0,str(ROOT.parent))
from process_guard import terminate_tree
# The environment lives beside the app; only the interpreter's place inside it depends on the system.
PYTHON = ROOT / '.venv-flux' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
CATALOG = json.loads((ROOT / 'flux-catalog.json').read_text(encoding='utf-8'))
PRESETS = {item['id']: item for item in CATALOG['presets']}
STYLES = {key: item['prompt'] for key, item in PRESETS.items()}
ASPECTS = {'source': None, 'square': (1, 1), 'portrait': (4, 5),
           'tall': (2, 3), 'landscape': (3, 2), 'wide': (16, 9)}


def prompts(settings):
    parts = [settings['prompt'] or STYLES[settings['style']]]
    if settings['mode'] != 'generate':
        parts += [rule[1] for key, rule in CATALOG['preserve'].items() if settings['preserve'][key]]
        for index, reference in enumerate(settings['references'], 2):
            parts.append(f"Reference image {index}: " + CATALOG['roles'][reference['role']][1])
    parts += [group['options'][settings['controls'][key]][1] for key, group in CATALOG['controls'].items()]
    return ' '.join(part for part in parts if part)


IMAGE_FORMATS = ('PNG', 'JPEG', 'WEBP')


def image_bytes(image):
    if not isinstance(image, str) or not image.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
        raise ValueError('اختر صورة صالحة أولًا.')
    try:
        raw = base64.b64decode(image.split(',', 1)[1], validate=True)
        if len(raw) > 6_000_000:
            raise ValueError()
        with Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS) as im:
            if im.width * im.height > 4_000_000:
                raise ValueError()
            im.verify()
        return raw
    except Exception:
        raise ValueError('الصورة غير صالحة أو أكبر من 6 ميغابايت و4 ملايين بكسل.') from None


def dimensions(settings, source_size=None):
    width, height = ASPECTS[settings['aspect']] or source_size or (1, 1)
    ratio = settings['resolution'] / max(width, height)
    return max(64, round(width * ratio / 32) * 32), max(64, round(height * ratio / 32) * 32)


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('طلب التوليد غير صالح.')
    allowed = {'image', 'style', 'prompt', 'resolution', 'seed', 'mode', 'references', 'aspect', 'controls', 'preserve'}
    if set(data) - allowed:
        raise ValueError('هذا النموذج يدعم الوصف والدقة والبذرة فقط؛ لا توجد قوة تحويل وهمية.')
    result = {'style': 'ink', 'prompt': '', 'resolution': 768, 'seed': 42,
              'mode': 'edit', 'references': [], 'aspect': 'source'} | data
    if not isinstance(result['style'], str) or result['style'] not in STYLES:
        raise ValueError('اختر أسلوبًا معروفًا.')
    if not isinstance(result['prompt'], str) or len(result['prompt']) > 1200:
        raise ValueError('الوصف يجب ألا يتجاوز 1200 حرف.')
    result['prompt'] = result['prompt'].strip()
    if result['style'] == 'custom' and not result['prompt']:
        raise ValueError('اكتب تعليمات التعديل المخصص.')
    if result['mode'] not in ('edit', 'generate', 'multi'):
        raise ValueError('اختر وضع توليد معروفًا.')
    if not isinstance(result['aspect'], str) or result['aspect'] not in ASPECTS:
        raise ValueError('نسبة الأبعاد غير صالحة.')
    for name, groups, default in [('controls', CATALOG['controls'], 'auto'), ('preserve', CATALOG['preserve'], True)]:
        supplied = data.get(name, {})
        if not isinstance(supplied, dict) or set(supplied) - set(groups):
            raise ValueError('خيارات التوجيه غير صالحة.')
        values = {key: default for key in groups} | supplied
        for key, value in values.items():
            if name == 'preserve':
                if type(value) is not bool:
                    raise ValueError('خيارات الحفاظ يجب أن تكون صحيحة أو خاطئة.')
            elif not isinstance(value, str) or value not in groups[key]['options']:
                raise ValueError('قيمة توجيه غير معروفة.')
        result[name] = values
    if type(result['resolution']) is not int or result['resolution'] not in (512, 768, 1024):
        raise ValueError('اختر دقة 512 أو 768 أو 1024.')
    if type(result['seed']) is not int or not 0 <= result['seed'] <= 2147483647:
        raise ValueError('بذرة النتيجة خارج النطاق المسموح.')
    references = result['references']
    if not isinstance(references, list) or len(references) > 2:
        raise ValueError('الحد الأقصى مرجعان إضافيان إلى الصورة الرئيسية.')
    if result['mode'] == 'generate':
        if references:
            raise ValueError('التوليد من النص لا يستخدم مراجع.')
        result['image'] = None
    else:
        total = len(image_bytes(result.get('image')))
        if result['mode'] == 'edit' and references:
            raise ValueError('اختر وضع المراجع المتعددة لاستخدام صور إضافية.')
        if result['mode'] == 'multi' and not references:
            raise ValueError('أضف مرجعًا واحدًا على الأقل بجانب الصورة الرئيسية.')
        for reference in references:
            if (not isinstance(reference, dict) or set(reference) != {'image', 'role'}
                    or not isinstance(reference['role'], str) or reference['role'] not in CATALOG['roles']):
                raise ValueError('بيانات المرجع غير صالحة.')
            total += len(image_bytes(reference['image']))
        if total > 12_000_000:
            raise ValueError('مجموع أحجام المراجع يتجاوز 12 ميغابايت.')
    return result


def availability():
    if not PYTHON.is_file():
        return False, 'بيئة FLUX المحلية غير جاهزة.'
    try:
        manifest = json.loads((MODEL_DIR / 'verified.json').read_text())
        if manifest['model'] != MODEL_ID or manifest['revision'] != REVISION or QUANT_FILE not in manifest['files']:
            raise ValueError()
        for name, details in manifest['files'].items():
            if (MODEL_DIR / name).stat().st_size != details['bytes']:
                raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        return False, 'جارٍ تجهيز أوزان FLUX؛ يتاح التوليد بعد اكتمال التنزيل والتحقق.'
    return True, 'FLUX.2 Klein 4B · Q5_K_M · أوزان محلية مكتملة'


def keep_warm_seconds():
    """Idle seconds the loaded model is kept after a job; 0 restores one process per job."""
    try:
        value = float(os.environ.get('FLUX_KEEP_WARM_S', '300'))
    except ValueError:
        return 300.0
    return value if math.isfinite(value) and 0 <= value <= 3600 else 300.0


ACTIVE = ('queued', 'loading', 'running')


class JobCancelled(Exception):
    pass


class Jobs:
    def __init__(self, gate, keep_warm=None):
        self.gate = gate
        self.lock = threading.Lock()
        self.job = None
        self.jobs = OrderedDict()
        self.keep_warm = keep_warm_seconds() if keep_warm is None else keep_warm
        self.worker = None
        self.worker_log = None
        self.idle_token = 0
        # The id of the job to stop; a warm worker reads it at its checkpoints.
        self.cancel_file = Path(tempfile.gettempdir()) / f'flux-studio-cancel-{os.getpid()}.txt'

    def status(self, job_id=None, summary=False):
        available, reason = availability()
        with self.lock:
            if job_id:
                selected = self.jobs.get(job_id)
                if selected and summary:
                    selected = {key: value for key, value in selected.items() if key != 'result'}
            elif self.job:
                # Without the job id expose progress only: never the id, image, prompt or error text.
                selected = {key: self.job[key] for key in ('state', 'step', 'total')}
            else:
                selected = None
            worker = self.worker
            return {'available': available, 'reason': reason, 'processing': self.gate.locked(),
                    'model': 'FLUX.2 Klein 4B Q5_K_M', 'job': copy.deepcopy(selected),
                    'modelLoaded': bool(worker and worker.poll() is None)}

    def start(self, data):
        settings = validate(data)
        available, reason = availability()
        if not available:
            raise ValueError(reason)
        if not self.gate.acquire(blocking=False):
            raise BlockingIOError('هناك معالجة محلية أخرى. انتظر اكتمالها.')
        job_id = uuid.uuid4().hex
        with self.lock:
            self.job = {'id': job_id, 'state': 'queued', 'step': 0, 'total': 0}
            self.jobs[job_id] = self.job
            while len(self.jobs) > 8:
                self.jobs.popitem(last=False)
        try:
            threading.Thread(target=self._run, args=(settings,), daemon=True).start()
        except Exception:
            with self.lock:
                self.job.update(state='failed', error='تعذر بدء عملية التوليد.')
            self.gate.release()
            raise
        return {'job': job_id}

    def cancel(self, job_id):
        """Stop the running job. A warm worker past model loading stops at its next step and
        keeps the model; otherwise the process ends, which is also the fallback after 20 s."""
        with self.lock:
            job = self.job
            if not job or job['id'] != job_id or job['state'] not in ACTIVE:
                return {'cancelled': False}
            if job.get('cancelling'):
                return {'cancelled': True}
            job['cancelling'] = True
            queued = job['state'] == 'queued'
            cooperative = bool(self.keep_warm) and job.get('phase') in ('prompt', 'draw')
        process = self.worker
        if queued or not process:
            return {'cancelled': True}  # _run sees the flag before it sends the job
        if cooperative:
            try:
                self.cancel_file.write_text(job_id, encoding='utf-8')
                timer = threading.Timer(20, self._force_cancel, args=(job_id, process))
                timer.daemon = True
                timer.start()
                return {'cancelled': True}
            except OSError:
                pass  # no cancel file: end the process instead
        terminate_tree(process)
        return {'cancelled': True}

    def _force_cancel(self, job_id, process):
        with self.lock:
            stuck = bool(self.job and self.job['id'] == job_id and self.job['state'] in ACTIVE)
        if stuck:
            terminate_tree(process)

    # Apart from cancel(), the worker is touched only by the thread that holds the compute gate.
    def _spawn(self):
        # Stderr is diagnostic-only, kept outside HTTP responses and user images.
        log = ROOT / 'generation-runtime.log'
        try:
            log.replace(ROOT / 'generation-runtime.previous.log')  # keep the last crash trace
        except OSError:
            pass
        self.worker_log = log.open('w', encoding='utf-8')
        try:
            self.worker = subprocess.Popen([str(PYTHON), str(ROOT / 'generation_service.py')],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.worker_log,
                                           text=True, encoding='utf-8',
                                           env=os.environ | {'FLUX_CANCEL_FILE': str(self.cancel_file)},
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except BaseException:
            self.worker_log.close()
            self.worker_log = None
            raise
        return self.worker

    def _discard_worker(self):
        """End the worker process; the driver returns its VRAM once it has exited."""
        process, log = self.worker, self.worker_log
        self.worker = self.worker_log = None
        if process:
            try:
                process.stdin.close()  # EOF is the worker's normal exit signal
            except OSError:
                pass
            try:
                process.wait(timeout=5 if process.poll() is None else 0)
            except subprocess.TimeoutExpired:
                terminate_tree(process)
                process.wait()
            if process.stdout:
                process.stdout.close()
        if log:
            log.close()

    def _unload_if_idle(self, token):
        if not self.gate.acquire(blocking=False):
            # Another stage holds the card. Only a generation job re-arms the timer itself, so retry.
            if token == self.idle_token and self.worker:
                self._arm_idle(token, min(self.keep_warm, 30))
            return
        try:
            if token == self.idle_token:
                self._discard_worker()
        finally:
            self.gate.release()

    def _arm_idle(self, token, delay):
        timer = threading.Timer(delay, self._unload_if_idle, args=(token,))
        timer.daemon = True
        timer.start()

    def unload(self):
        """Free the model now. The caller must hold the compute gate."""
        self.cancel_file.unlink(missing_ok=True)
        self.idle_token += 1
        self._discard_worker()

    def _run(self, settings):
        watchdog = None
        keep = False
        job = self.job
        try:
            with self.lock:
                if job.get('cancelling'):
                    raise JobCancelled()
                job['state'] = 'loading'
            self.idle_token += 1  # invalidates any pending idle unload
            process = self.worker if self.worker and self.worker.poll() is None else None
            if not process:
                self._discard_worker()
                process = self._spawn()
            watchdog = threading.Timer(1200, terminate_tree,args=(process,))
            watchdog.daemon = True
            watchdog.start()
            with self.lock:
                if job.get('cancelling'):  # cancelled while the process was still starting
                    raise JobCancelled()
            process.stdin.write(json.dumps(settings | {'jobId': job['id']}) + '\n')
            process.stdin.flush()
            if not self.keep_warm:
                process.stdin.close()
            result = None
            failure = None
            done = False
            for line in iter(process.stdout.readline, ''):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # a library printed to stdout; not a protocol event
                if not isinstance(event, dict):
                    continue
                with self.lock:
                    if event.get('state') in ('loading', 'running'):
                        job.update({key: event[key] for key in ('state', 'step', 'total')})
                        if 'phase' in event:
                            job['phase'] = event['phase']
                if 'result' in event:
                    result = event['result']
                if 'error' in event:
                    failure = event['error']
                if event.get('done'):
                    done = not event.get('exiting')  # a worker that announced its exit is not kept
                    break
            # A worker that answered and is still alive keeps the model for the next job.
            keep = bool(self.keep_warm) and done and process.poll() is None
            if not keep:
                self._discard_worker()
            if job.get('cancelling'):
                raise JobCancelled()
            if not result:
                raise ValueError(failure or 'انتهت عملية التوليد قبل إخراج صورة. جرّب دقة أقل.')
            if not isinstance(result, dict) or not isinstance(result.get('image'), str) or not result['image'].startswith('data:image/png;base64,'):
                raise ValueError('لم ينتج النموذج صورة PNG صالحة.')
            image_bytes(result['image'])
            with Image.open(io.BytesIO(base64.b64decode(result['image'].split(',', 1)[1])), formats=('PNG',)) as image:
                if image.size != (result.get('width'), result.get('height')):
                    raise ValueError('أبعاد الصورة الناتجة غير متطابقة.')
            # Without keep-warm the process has exited and CUDA memory is released;
            # with it the model stays loaded until the idle timer or unload() ends the worker.
            with self.lock:
                if job.get('cancelling'):
                    raise JobCancelled()
                job.update(state='complete', result=result)
        except JobCancelled:
            with self.lock:
                job.update(state='cancelled')
        except Exception as error:
            with self.lock:
                cancelling = bool(job.get('cancelling'))
            if not isinstance(error, ValueError):
                keep = False
                if not cancelling:
                    LOG.exception('generation job failed')
            with self.lock:
                job.update(state='cancelled') if cancelling else job.update(state='failed', error=str(error) if isinstance(error, ValueError) else 'تعذر تشغيل مهمة التوليد المحلية.')
        finally:
            if watchdog:
                watchdog.cancel()
            if keep:
                self._arm_idle(self.idle_token, self.keep_warm)
            else:
                self._discard_worker()
            self.gate.release()
