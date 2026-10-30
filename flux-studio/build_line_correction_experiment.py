"""Standalone correction pilot using existing paired samples, never production extraction."""
import argparse
import base64
import io
import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from conservative_line_corrector import VERSION, correct, source_evidence


def decode(uri):
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1]))).convert('RGB'))


def png(array):
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format='PNG')
    return buf.getvalue()


def feature_regions(shape, face):
    h,w = shape
    regions = np.zeros(shape, np.uint8)
    protected = np.zeros(shape, np.uint8)
    groups = [[33,159,133,145],[263,386,362,374],[168,4,1,98,327],[61,37,0,267,291,314,17,84]]
    boxes = []
    for region_id, group in enumerate(groups, 1):
        points = np.array(face)[group,:2]*[w,h]
        low,high = points.min(axis=0),points.max(axis=0)
        padding = np.maximum(4, (high-low)*.2)
        low = np.maximum(0,np.floor(low-padding)).astype(int)
        high = np.minimum([w,h],np.ceil(high+padding)+1).astype(int)
        regions[low[1]:high[1],low[0]:high[0]] = region_id
        boxes.append([int(low[0]),int(low[1]),int(high[0]),int(high[1])])
        for x,y in np.rint(points).astype(int):
            cv2.circle(protected,(int(x),int(y)),3,1,-1)
    # Iris locations, if present, are protected, not used for similarity or line generation.
    for point in np.array(face)[468:478,:2]*[w,h]:
        cv2.circle(protected,tuple(np.rint(point).astype(int)),4,1,-1)
    return regions, protected > 0, boxes


def transparent(rgb):
    # Remove the white matte without changing subtle colour/antialiasing in untouched pixels.
    rgb = np.asarray(rgb,np.uint8)
    matte = rgb.min(axis=2).astype(float)
    alpha = 255-matte
    rgba = np.zeros((*matte.shape,4),np.uint8)
    foreground = np.divide((rgb.astype(float)-matte[:,:,None])*255,
                           alpha[:,:,None],out=np.zeros_like(rgb,dtype=float),where=alpha[:,:,None]>0)
    rgba[:,:,:3] = np.rint(foreground).clip(0,255).astype('uint8')
    rgba[:,:,3] = alpha.astype('uint8')
    return rgba


def build(source, output):
    raw = source.read_text(encoding='utf8')
    data = json.loads(base64.b64decode(re.search(r"atob\('([^']+)'\)",raw)[1]))
    inputs = [r for r in data['samples'] if not r.get('cropBox')]
    assets = output.with_name(output.stem+'-files')
    if output.exists() or assets.exists():
        raise ValueError('Use a new experiment output path; existing outputs are preserved.')
    assets.mkdir(parents=True)
    images, rows, evidence_cache = {}, [], {}
    def store(array):
        import hashlib
        encoded = png(array)
        key = hashlib.sha256(encoded).hexdigest()
        images.setdefault(key,'data:image/png;base64,'+base64.b64encode(encoded).decode())
        return key
    for row in inputs:
        sample_id = row['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',sample_id):
            raise ValueError('Unsafe sample id.')
        before = decode(data['images'][row['result']['imageId']])
        source_rgb = decode(data['images'][row['source']['imageId']])
        h,w = before.shape[:2]
        aligned = abs((source_rgb.shape[1]/source_rgb.shape[0])/(w/h)-1) <= .01
        if aligned:
            source_rgb = np.asarray(Image.fromarray(source_rgb).resize((w,h),Image.Resampling.LANCZOS))
        else:
            from PIL import ImageOps
            source_rgb = np.asarray(ImageOps.pad(Image.fromarray(source_rgb),(w,h),color='white'))
        regions, protection, boxes = np.zeros((h,w),np.uint8),np.zeros((h,w),bool),[]
        faces = row['source']['faces']
        if aligned and len(faces) == 1:
            regions, protection, boxes = feature_regions((h,w),faces[0])
        evidence_key = (row['source']['imageId'],w,h)
        if evidence_key not in evidence_cache:
            evidence_cache[evidence_key] = source_evidence(source_rgb)
        evidence = evidence_cache[evidence_key]
        mask = cv2.cvtColor(before,cv2.COLOR_RGB2GRAY) < 200
        after_mask, report = correct(mask,evidence,regions,protection)
        report.update(sourceRegions='cached original face coordinates for ROI only; no result-face detection required',
                      alignment='same relative frame; uniform resize only; no local warp',
                      aspectCompatible=aligned, inkThreshold=200, maxOperations=6,
                      sourceFileSHA256=row['source'].get('fileSHA256'),
                      resultFileSHA256=row['result'].get('fileSHA256'))
        if not boxes:
            report['reason'] = 'No configured source feature region, or incompatible frame aspect; unchanged.'
        changed = mask != after_mask
        assert not (changed & (regions == 0)).any()
        assert not (changed & protection).any()
        after = before.copy()
        after[mask & ~after_mask] = 255
        after[~mask & after_mask] = 0
        assert np.array_equal(after[~changed],before[~changed])
        delta = np.zeros((h,w,4),np.uint8)
        delta[mask & ~after_mask] = (210,35,55,255)
        delta[~mask & after_mask] = (0,135,95,255)
        focus = [0,0,w,h]
        if len(faces) == 1:
            coords = np.array(faces[0])[:,:2]*[w,h]
            low,high=coords.min(axis=0),coords.max(axis=0)
            padding=(high-low)*.25
            focus=[max(0,int(low[0]-padding[0])),max(0,int(low[1]-padding[1])),min(w,int(high[0]+padding[0])),min(h,int(high[1]+padding[1]))]
        item = {'id':sample_id,'label':row['label'],'width':w,'height':h,'report':report,
                'regions':boxes,'focus':focus,'images':{}}
        exports = {'source':source_rgb,'before':before,'after':after,
                   'beforeTransparent':transparent(before),'afterTransparent':transparent(after),
                   'finalBlack':np.repeat(after.min(axis=2)[:,:,None],3,axis=2),
                   'changes':delta,'evidence':(evidence.astype('uint8')*255)}
        for name,array in exports.items():
            item['images'][name] = store(array)
        report.update(beforePNG_SHA256=item['images']['before'],afterPNG_SHA256=item['images']['after'],
                      referencePNG_SHA256=item['images']['source'],finalBlackPNG_SHA256=item['images']['finalBlack'])
        folder = assets/sample_id
        folder.mkdir()
        for name in ('source','before','after','afterTransparent','finalBlack','changes'):
            (folder/(name+'.png')).write_bytes(png(exports[name]))
        (folder/'operations.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        rows.append(item)
        print(sample_id,report['state'],report['changedPixels'],flush=True)
    summary = {'version':VERSION,'samples':len(rows),'edited':sum(r['report']['state']=='edited' for r in rows),
        'unchanged':sum(r['report']['state']!='edited' for r in rows),
        'changedPixels':sum(r['report']['changedPixels'] for r in rows),
        'operations':dict(Counter(op['kind'] for r in rows for op in r['report']['operations'])),
        'limitations':['Classical multiscale edges are not semantic ground truth.',
                       'No independent labels or blinded comparison establish improvement.',
                       'Source landmarks cached previously only locate ROIs; unavailable ROIs abstain.',
                       'Same frame is assumed; substantial generation reframing requires alignment first.',
                       'Not calibrated, not production approval, no new SVG or path extraction.'],
        'cases':[{'id':r['id'],'report':r['report']} for r in rows]}
    payload={'version':VERSION,'images':images,'samples':rows,'summary':summary}
    template=(Path(__file__).parent/'line-correction-preview.html').read_text(encoding='utf8')
    encoded=base64.b64encode(json.dumps(payload).encode()).decode()
    output.write_bytes(template.replace('__BUNDLE__',encoded).encode('utf8'))
    output.with_suffix('.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k!='cases'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args.source,args.output)
