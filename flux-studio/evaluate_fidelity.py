"""Reproducible offline audit of saved raw FLUX samples. Does not invoke any model."""
import base64
import hashlib
import json
import time
from pathlib import Path
from faithful_paths import extract
from path_fidelity import decode_image,ink_mask,measure

ROOT=Path(__file__).resolve().parent
SAMPLES=ROOT/'comparison-review'
OUT=ROOT/'fidelity-review'
OUT.mkdir(exist_ok=True)


def save_images(name,result):
    result=dict(result)
    for key in ['reconstruction','difference','target']:
        (OUT/f'{name}-{key}.png').write_bytes(base64.b64decode(result.pop(key).split(',',1)[1]))
    return result


def main():
    rows=[];pen=.2
    for file in sorted(SAMPLES.glob('*-flux.png')):
        key=file.name.removesuffix('-flux.png');before=hashlib.sha256(file.read_bytes()).hexdigest()
        image='data:image/png;base64,'+base64.b64encode(file.read_bytes()).decode()
        rgb,gray=decode_image(image);h,w=gray.shape;scale=min((180-pen)/w,(267-pen)/h)
        started=time.perf_counter();result=extract(dict(image=image,mmPerPixel=scale,penMm=pen,inkThreshold=0))
        seconds=round(time.perf_counter()-started,3)
        scores=save_images(key,result.pop('fidelity'))
        (OUT/f'{key}-paths.json').write_text(json.dumps(result),encoding='utf-8')
        reference,_=ink_mask(gray)
        old=json.loads((SAMPLES/f'{key}-via-precise-paths.json').read_text())
        assert (old['width'],old['height'])==(w,h)
        old_score=measure(rgb,gray,reference,old['paths'],scale,pen)
        old_score=save_images(key+'-old',old_score)
        assert hashlib.sha256(file.read_bytes()).hexdigest()==before
        row=dict(key=key,width=w,height=h,penMm=pen,mmPerPixel=scale,sourceSHA256=before,
            sourceUnchanged=True,planningSeconds=seconds,score=scores,viaPrecise=old_score,
            count=len(result['paths']),points=result['outputPoints'],fillStrokes=result['fillPasses'])
        rows.append(row)
        (OUT/'audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(key,'IoU',scores['inkIoU'],'via precise',old_score['inkIoU'],'strokes',len(result['paths']),'seconds',seconds,flush=True)
    return rows


if __name__=='__main__':main()
