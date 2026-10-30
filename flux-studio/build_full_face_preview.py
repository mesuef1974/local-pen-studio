"""Offline full-mesh inspection; no point filtering and no similarity score."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path

import mediapipe as mp
import numpy as np
from PIL import Image, ImageOps
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from quality_features import verified_model


def build(manifest, output, crop_experiment=False):
    from mediapipe.tasks.python.vision import FaceLandmarksConnections as C
    edges = sorted({(e.start, e.end) for name in ('FACE_LANDMARKS_TESSELATION',
        'FACE_LANDMARKS_LEFT_IRIS', 'FACE_LANDMARKS_RIGHT_IRIS') for e in getattr(C, name)})
    rows = []
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=verified_model('face_landmarker.task')),
        num_faces=2, min_face_detection_confidence=.7, min_face_presence_confidence=.7)
    with vision.FaceLandmarker.create_from_options(options) as detector:
        inputs = json.loads(manifest.read_text(encoding='utf-8-sig'))
        expanded = []
        for item in inputs:
            item = dict(item, label=item.get('label') or ('رائدة الفضاء' if item['id']=='astronaut' else 'صورتك / الرسم '+item['id'].split('-')[-1]))
            expanded.append(item)
            if crop_experiment:
                source = ImageOps.exif_transpose(Image.open(item['reference'])).convert('RGB')
                found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(source)))
                if len(found.face_landmarks) != 1:
                    item['cropUnavailable'] = 'لم يُكشف وجه أصلي واحد؛ تعذر تحديد قص تلقائي.'
                    continue
                face = found.face_landmarks[0]
                xs, ys = [p.x for p in face], [p.y for p in face]
                left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
                dx, dy = (right-left)*.45, (bottom-top)*.45
                box = [max(0,left-dx),max(0,top-dy),min(1,right+dx),min(1,bottom+dy)]
                expanded.append(dict(item, id=item['id']+'-crop', cropBox=box))
        for item in expanded:
            pair = {'id': item['id'], 'label': item.get('label', item['id']) + (' · قص الوجه' if 'cropBox' in item else ' · الصورة الكاملة'), 'cropBox': item.get('cropBox'), 'cropUnavailable': item.get('cropUnavailable')}

            for role, field in [('source', 'reference'), ('result', 'path')]:
                path = Path(item[field])
                image = ImageOps.exif_transpose(Image.open(path)).convert('RGBA')
                white = Image.new('RGBA', image.size, 'white')
                white.alpha_composite(image)
                image = white.convert('RGB')
                if item.get('cropBox'):
                    l,t,r,b = item['cropBox']
                    w,h = image.size
                    image = image.crop((int(l*w),int(t*h),int(r*w),int(b*h)))
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(image)))
                points = [[[p.x, p.y, p.z] for p in face] for face in found.face_landmarks]
                buf = io.BytesIO()
                image.save(buf, format='PNG')
                pair[role] = {'image': 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode(),
                    'faces': points, 'width': image.width, 'height': image.height,
                    'fileSHA256': hashlib.sha256(path.read_bytes()).hexdigest()}
            pair['comparison'] = {'state': 'unavailable', 'reason': 'يلزم وجه واحد مكتشف في الصورتين.', 'score': None}
            if len(pair['source']['faces']) == len(pair['result']['faces']) == 1:
                a,b = [np.array(pair[role]['faces'][0])[:,:2]*[pair[role]['width'],pair[role]['height']] for role in ['source','result']]
                if len(a) == len(b) == 478:
                    def normalized(v):
                        return (v-v.min(axis=0))/np.ptp(v,axis=0).max()
                    errors = np.linalg.norm(normalized(a)-normalized(b),axis=1)
                    pair['comparison'] = {'state': 'raw_only', 'points': 478, 'rms': float(np.sqrt(np.mean(errors**2))), 'median': float(np.median(errors)), 'maximum': float(errors.max()), 'score': None}
            rows.append(pair)
    data = {'version': 'full-face-preview/1.0', 'threshold': .7, 'edges': edges, 'samples': rows}
    images = {}
    for row in rows:
        for role in ['source', 'result']:
            uri = row[role].pop('image')
            image_id = hashlib.sha256(uri.encode()).hexdigest()
            images.setdefault(image_id, uri)
            row[role]['imageId'] = image_id
    data['images'] = images
    template = (Path(__file__).parent/'full-face-preview.html').read_text(encoding='utf8')
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(template.replace('__BUNDLE__', encoded).encode('utf8'))
    summary = {'version': data['version'], 'threshold': .7, 'pointFiltering': False,
        'score': None, 'cropPolicy': 'source face bounds plus 45 percent margin each side, identical normalized box for both images; no point transfer' if crop_experiment else None,
        'samples': [{'id': r['id'], 'cropBox': r['cropBox'], 'comparison': r['comparison'], 'cropUnavailable': r['cropUnavailable'], **{role: {'faces': len(r[role]['faces']),
        'pointsPerFace': [len(f) for f in r[role]['faces']], 'fileSHA256': r[role]['fileSHA256']}
        for role in ['source', 'result']}} for r in rows]}
    output.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--crop-experiment', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.output, args.crop_experiment), ensure_ascii=False, indent=2))
