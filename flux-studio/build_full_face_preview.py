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


def build(manifest, output):
    from mediapipe.tasks.python.vision import FaceLandmarksConnections as C
    edges = sorted({(e.start, e.end) for name in ('FACE_LANDMARKS_TESSELATION',
        'FACE_LANDMARKS_LEFT_IRIS', 'FACE_LANDMARKS_RIGHT_IRIS') for e in getattr(C, name)})
    rows = []
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=verified_model('face_landmarker.task')),
        num_faces=2, min_face_detection_confidence=.7, min_face_presence_confidence=.7)
    with vision.FaceLandmarker.create_from_options(options) as detector:
        for item in json.loads(manifest.read_text(encoding='utf-8-sig')):
            pair = {'id': item['id']}
            for role, field in [('source', 'reference'), ('result', 'path')]:
                path = Path(item[field])
                image = ImageOps.exif_transpose(Image.open(path)).convert('RGBA')
                white = Image.new('RGBA', image.size, 'white')
                white.alpha_composite(image)
                image = white.convert('RGB')
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(image)))
                points = [[[p.x, p.y, p.z] for p in face] for face in found.face_landmarks]
                buf = io.BytesIO()
                image.save(buf, format='PNG')
                pair[role] = {'image': 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode(),
                    'faces': points, 'width': image.width, 'height': image.height,
                    'fileSHA256': hashlib.sha256(path.read_bytes()).hexdigest()}
            rows.append(pair)
    data = {'version': 'full-face-preview/1.0', 'threshold': .7, 'edges': edges, 'samples': rows}
    template = (Path(__file__).parent/'full-face-preview.html').read_text(encoding='utf8')
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(template.replace('__BUNDLE__', encoded).encode('utf8'))
    summary = {'version': data['version'], 'threshold': .7, 'pointFiltering': False,
        'score': None, 'samples': [{'id': r['id'], **{role: {'faces': len(r[role]['faces']),
        'pointsPerFace': [len(f) for f in r[role]['faces']], 'fileSHA256': r[role]['fileSHA256']}
        for role in ['source', 'result']}} for r in rows]}
    output.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.output), ensure_ascii=False, indent=2))
