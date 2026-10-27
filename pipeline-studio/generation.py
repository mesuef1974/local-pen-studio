"""Validated local SDXL jobs with real diffusion-step progress and shared compute gate."""
import base64
import copy
import io
import json
import math
import subprocess
import threading
import uuid
from pathlib import Path

from PIL import Image
from setup_generation import FILES, MODEL_DIR, MODEL_ID, REVISION

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv-generation/Scripts/python.exe'
STYLES = {
    'caricature': 'hand drawn editorial caricature illustration of the subject, playful exaggerated proportions, expressive recognizable features, exaggerated head proportions, simple bold contour lines, white background',
    'cartoon': 'flat vector cartoon drawing, comic book illustration, two dimensional cel shading, bold thick black outlines, solid flat color shapes, simplified expressive face, cartoon character on white background',
    'ink': 'black and white pen and ink lineart, hand drawn coloring book illustration, sparse clean black contour lines on pure white paper, unfilled white shapes, precise eyes and mouth, monochrome outline drawing',
    'pencil': 'black and white graphite pencil sketch, monochrome hand drawn sketchbook portrait, visible fine graphite strokes, rough white paper texture, delicate outlines, pencil crosshatching, expressive eyes and mouth',
    'watercolor': 'traditional watercolor painting of the subject on textured white paper, loose visible brushstrokes, soft bleeding edges, diluted colorful pigments, delicate transparent color washes, recognizable features',
}
STYLE_DEFAULTS = {
    'caricature': {'strength': .70, 'steps': 30, 'guidance': 8},
    'cartoon': {'strength': .85, 'steps': 40, 'guidance': 10},
    'ink': {'strength': .85, 'steps': 40, 'guidance': 10},
    'pencil': {'strength': .45, 'steps': 28, 'guidance': 7},
    'watercolor': {'strength': .70, 'steps': 30, 'guidance': 7.5},
}
STYLE_NEGATIVES = {
    'caricature': 'photograph, photorealistic, realistic skin texture, 3D render',
    'cartoon': 'photograph, photorealistic, realistic skin texture, skin pores, 3D render, pencil, watercolor, crosshatching, gradient shading',
    'ink': 'photograph, color, grayscale fills, shaded areas, heavy shading, hatching, paint, watercolor, charcoal',
    'pencil': 'photograph, photorealistic, color, colored paint, watercolor, thick marker, 3D render',
    'watercolor': 'photograph, photorealistic, 3D render, flat vector art, thick black outlines, graphite pencil',
}


def prompts(settings):
    positive = STYLES[settings['style']] + (', ' + settings['prompt'] if settings['prompt'] else '')
    negative = 'watermark, text, extra eyes, distorted face, excessive tiny details, ' + STYLE_NEGATIVES[settings['style']]
    if settings['negativePrompt']:
        negative += ', ' + settings['negativePrompt']
    return positive, negative


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('طلب التوليد غير صالح.')
    result = dict(data)
    style = data.get('style', 'caricature')
    if not isinstance(style, str) or style not in STYLES:
        raise ValueError('اختر أسلوب تحويل معروفًا.')
    result['style'] = style
    result['stylePrompt'] = STYLES[style]
    preserve = data.get('preserveSource', False)
    if not isinstance(preserve, bool) or (preserve and style != 'watercolor'):
        raise ValueError('حفظ محتوى الصورة متاح حاليًا لمعالجة الألوان المائية فقط.')
    result['preserveSource'] = preserve
    data = STYLE_DEFAULTS[style] | data
    for key, default, low, high, integer in [('strength', .5, .1, .85, False), ('steps', 24, 10, 40, True),
                                          ('guidance', 6, 1, 12, False), ('seed', 42, 0, 2147483647, True),
                                          ('resolution', 1024, 512, 1024, True)]:
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high or (integer and not isinstance(value, int)):
            raise ValueError('قيم التحكم في التوليد خارج النطاق المسموح.')
        result[key] = value
    if result['resolution'] not in (512, 768, 1024):
        raise ValueError('اختر دقة 512 أو 768 أو 1024 للتوليد.')
    for key, limit in [('prompt', 1200), ('negativePrompt', 1000)]:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('وصف التعديل أطول من الحد المسموح.')
        result[key] = value.strip()
    image = data.get('image')
    if not isinstance(image, str) or not image.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
        raise ValueError('اختر صورة محملة صالحة أولًا.')
    try:
        raw = base64.b64decode(image.split(',', 1)[1], validate=True)
        if len(raw) > 6_000_000:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 4_000_000:
                raise ValueError()
            im.verify()
    except Exception:
        raise ValueError('الصورة غير صالحة أو تتجاوز حد 6 ميغابايت و4 ملايين بكسل.') from None
    return result


def availability():
    if not PYTHON.is_file():
        return False, 'بيئة التوليد المحلية غير جاهزة.'
    try:
        manifest = json.loads((MODEL_DIR / 'verified.json').read_text(encoding='utf-8'))
        if manifest['model'] != MODEL_ID or manifest['revision'] != REVISION:
            raise ValueError()
        for name in FILES:
            if (MODEL_DIR / name).stat().st_size != manifest['files'][name]['bytes']:
                raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        return False, 'أوزان SDXL لم يكتمل تنزيلها والتحقق منها بعد.'
    return True, ''


class Jobs:
    def __init__(self, gate):
        self.gate = gate
        self.lock = threading.Lock()
        self.job = None

    def status(self):
        available, reason = availability()
        with self.lock:
            return {'available': available, 'reason': reason, 'model': 'SDXL 1.0', 'job': copy.deepcopy(self.job)}

    def start(self, data):
        settings = validate(data)
        available, reason = ((PYTHON.is_file(), 'بيئة معالجة الصورة غير جاهزة.')
                             if settings['preserveSource'] else availability())
        if not available:
            raise ValueError(reason)
        if not self.gate.acquire(blocking=False):
            raise BlockingIOError('هناك معالجة محلية أخرى. انتظر اكتمالها.')
        job_id = uuid.uuid4().hex
        with self.lock:
            self.job = {'id': job_id, 'state': 'queued', 'step': 0, 'total': 0}
        try:
            threading.Thread(target=self._run, args=(settings,), daemon=True).start()
        except Exception:
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
                watchdog = threading.Timer(1200, process.kill)
                watchdog.daemon = True
                watchdog.start()
                process.stdin.write(json.dumps(settings))
                process.stdin.close()
                result = None
                failure = None
                for line in process.stdout:
                    event = json.loads(line)
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
                validate({'image': result['image']})
                with Image.open(io.BytesIO(base64.b64decode(result['image'].split(',', 1)[1]))) as image:
                    if image.size != (result.get('width'), result.get('height')):
                        raise ValueError('أبعاد الصورة الناتجة غير متطابقة.')
                # Complete only after process exit: CUDA memory is now released.
                with self.lock:
                    self.job.update(state='complete', result=result)
        except Exception as error:
            with self.lock:
                self.job.update(state='failed', error=str(error) if isinstance(error, ValueError) else 'تعذر تشغيل مهمة التوليد المحلية.')
        finally:
            if watchdog:
                watchdog.cancel()
            if process:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdout:
                    process.stdout.close()
            self.gate.release()
