"""Controlled-size diagnostic. No generated detail, detection-based ranking, or calibrated score."""
import argparse
import base64
import copy
import hashlib
import io
import json
import re
from pathlib import Path

import mediapipe as mp
import numpy as np
from PIL import Image
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from essential_face import compare
from quality_features import verified_model

SIZES = (384, 512, 768)


def fit_square(image, size):
    scale = size / max(image.size)
    dimensions = tuple(max(1, round(v*scale)) for v in image.size)
    resized = image.resize(dimensions, Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', (size, size), 'white')
    offset = ((size-dimensions[0])//2, (size-dimensions[1])//2)
    canvas.paste(resized, offset)
    return canvas, {'nativeCropSize': list(image.size), 'scale': scale,
                    'upscaled': scale > 1, 'offset': list(offset), 'resizedSize': list(dimensions)}


def build(source, output):
    html = source.read_text(encoding='utf8')
    match = re.search(r"atob\('([^']+)'\)", html)
    data = json.loads(base64.b64decode(match[1]))
    crops = [r for r in data['samples'] if r.get('cropBox')]
    uncut = [r for r in data['samples'] if not r.get('cropBox') and r.get('cropUnavailable')]
    rows, images, cache = [], {}, {}
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=verified_model('face_landmarker.task')),
        num_faces=2, min_face_detection_confidence=.7, min_face_presence_confidence=.7)
    with vision.FaceLandmarker.create_from_options(options) as detector:
        for row in crops:
            for size in SIZES:
                candidate = copy.deepcopy(row)
                candidate.update(id=f"{row['id']}-size-{size}",
                                 label=f"{row['label']} · مدخل {size}×{size}", inputSize=size)
                for role in ('source', 'result'):
                    item = row[role]
                    key = (item['imageId'], size)
                    if key not in cache:
                        raw = base64.b64decode(data['images'][item['imageId']].split(',')[1])
                        original = Image.open(io.BytesIO(raw)).convert('RGB')
                        image, metadata = fit_square(original, size)
                        found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                         data=np.ascontiguousarray(image)))
                        buf = io.BytesIO()
                        image.save(buf, format='PNG')
                        uri = 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
                        image_id = hashlib.sha256(uri.encode()).hexdigest()
                        images[image_id] = uri
                        cache[key] = dict(item, imageId=image_id, width=size, height=size,
                            normalization=metadata,
                            faces=[[[p.x,p.y,p.z] for p in face] for face in found.face_landmarks])
                    candidate[role] = copy.deepcopy(cache[key])
                candidate['comparison'] = {'state': 'unavailable', 'score': None}
                if len(candidate['source']['faces']) == len(candidate['result']['faces']) == 1:
                    points = [np.array(candidate[role]['faces'][0])[:,:2]*size for role in ('source','result')]
                    candidate['comparison'] = compare(*points)
                rows.append(candidate)
    # Keep unsuccessful original-face crops visible; do not discard hard cases.
    for row in uncut:
        row = copy.deepcopy(row)
        row['label'] += ' · تعذر توحيد القص تلقائيًا'
        row['comparison'] = {'state': 'unavailable', 'score': None}
        rows.append(row)
        for role in ('source', 'result'):
            image_id = row[role]['imageId']
            images[image_id] = data['images'][image_id]
    data.update(samples=rows, images=images, experimentVersion='controlled-input-size/1.0')
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    html = html[:match.start(1)] + encoded + html[match.end(1):]
    html = html.replace('الأصل والرسم · 21 نقطة أساسية', 'تجربة مدخلات موحّدة · العينان والأنف والفم')
    notice = '<p class="note">تجربة ضبط المدخلات: قص الوجه من التجربة السابقة بهامش 45%، ثم تحجيم موحّد يحفظ النسب مع حواف بيضاء إلى 384 و512 و768 بكسل. عتبة الكشف 0.70 ثابتة. تظهر جميع الأحجام، دون انتقاء أفضل نتيجة. التكبير لا يستعيد التفاصيل المفقودة، واختلافات جودة المصدر وحجم الوجه النسبي لم تُلغَ بالكامل. تعذّر الكشف ليس رفضًا للرسم.</p>'
    html = html.replace('<div class="tools">', notice+'<div class="tools">', 1)
    html = html.replace("function refresh(){", """function showInputMetadata(){for(const role of ['source','result']){const row=data.samples.find(r=>r.id===$('sample').value),n=row[role].normalization;if(n)$(role+'Status').textContent+=' · القص الأصلي '+n.nativeCropSize.join('×')+' بكسل · معامل التحجيم '+n.scale.toFixed(2)+(n.upscaled?' · جرى تكبيره؛ دون استعادة التفاصيل':' · تصغير موحّد');}}
function refresh(){""")
    html = html.replace("return draw().catch", "return draw().then(showInputMetadata).catch")
    output.write_bytes(html.encode('utf8'))
    summary = {'version': data['experimentVersion'], 'threshold': .7, 'sizes': SIZES,
        'normalizedPairs': len(crops), 'unavailableCropPairs': len(uncut), 'views': len(rows),
        'pointGroups': data['pointGroups'], 'score': None,
        'limitations': ['No ground-truth landmark labels.', 'Upscaling does not restore detail.',
                       'Same crop coordinates do not guarantee equal face occupancy after generation.',
                       'Detection failure does not measure drawing quality.'],
        'cases': [{'id': r['id'], 'comparison': r['comparison'],
                   'normalization': {role:r[role].get('normalization') for role in ('source','result')}} for r in rows]}
    output.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'cases'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)
