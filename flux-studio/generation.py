"""Validated FLUX jobs; same image-review contract as the existing workspace."""
import base64
import copy
import io
import json
import logging
import math
import subprocess
import sys
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
PYTHON = ROOT / '.venv-flux/Scripts/python.exe'
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


class Jobs:
    def __init__(self, gate):
        self.gate = gate
        self.lock = threading.Lock()
        self.job = None
        self.jobs = OrderedDict()

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
            return {'available': available, 'reason': reason, 'processing': self.gate.locked(),
                    'model': 'FLUX.2 Klein 4B Q5_K_M', 'job': copy.deepcopy(selected)}

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

    def _run(self, settings):
        process = None
        watchdog = None
        try:
            with self.lock:
                self.job['state'] = 'loading'
            # Stderr is diagnostic-only, kept outside HTTP responses and user images.
            with (ROOT / 'generation-runtime.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(PYTHON), str(ROOT / 'generation_service.py')],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                           text=True, encoding='utf-8',
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                watchdog = threading.Timer(1200, terminate_tree,args=(process,))
                watchdog.daemon = True
                watchdog.start()
                process.stdin.write(json.dumps(settings))
                process.stdin.close()
                result = None
                failure = None
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue  # a library printed to stdout; not a protocol event
                    if not isinstance(event, dict):
                        continue
                    with self.lock:
                        if event.get('state') in ('loading', 'running'):
                            self.job.update({key: event[key] for key in ('state', 'step', 'total')})
                    if 'result' in event:
                        result = event['result']
                    if 'error' in event:
                        failure = event['error']
                code = process.wait()
                if code or not result:
                    raise ValueError(failure or 'انتهت عملية التوليد قبل إخراج صورة. جرّب دقة أقل.')
                if not isinstance(result, dict) or not isinstance(result.get('image'), str) or not result['image'].startswith('data:image/png;base64,'):
                    raise ValueError('لم ينتج النموذج صورة PNG صالحة.')
                image_bytes(result['image'])
                with Image.open(io.BytesIO(base64.b64decode(result['image'].split(',', 1)[1])), formats=('PNG',)) as image:
                    if image.size != (result.get('width'), result.get('height')):
                        raise ValueError('أبعاد الصورة الناتجة غير متطابقة.')
                # Complete only after process exit: CUDA memory is now released.
                with self.lock:
                    self.job.update(state='complete', result=result)
        except Exception as error:
            if not isinstance(error, ValueError):
                LOG.exception('generation job failed')
            with self.lock:
                self.job.update(state='failed', error=str(error) if isinstance(error, ValueError) else 'تعذر تشغيل مهمة التوليد المحلية.')
        finally:
            if watchdog:
                watchdog.cancel()
            if process:
                if process.poll() is None:
                    terminate_tree(process)
                process.wait()
                if process.stdout:
                    process.stdout.close()
            self.gate.release()
