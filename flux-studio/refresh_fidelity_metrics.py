"""Remeasure saved paths after an audit definition change; never rerun planning."""
import base64
import json
from pathlib import Path
from evaluate_fidelity import save_images
from path_fidelity import decode_image,ink_mask,measure

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'fidelity-review'
rows=json.loads((OUT/'audit.json').read_text())
for row in rows:
    key=row['key'];image='data:image/png;base64,'+base64.b64encode((ROOT/'comparison-review'/f'{key}-flux.png').read_bytes()).decode()
    rgb,gray=decode_image(image);mask,_=ink_mask(gray)
    for field,suffix,pathfile in [('score','',OUT/f'{key}-paths.json'),('viaPrecise','-old',ROOT/'comparison-review'/f'{key}-via-precise-paths.json')]:
        paths=json.loads(pathfile.read_text())['paths']
        score=save_images(key+suffix,measure(rgb,gray,mask,paths,row['mmPerPixel'],row['penMm']))
        for metric in ['inkIoU','inkRecall','inkPrecision']:
            assert score[metric]==row[field][metric], 'Tone audit must not alter any ink score'
        row[field].update(score)
    # Historical seed metadata keeps only the unchanged ink scores.
    row['score']['baselineCenterline']={k:v for k,v in row['score']['baselineCenterline'].items() if k not in ['grayErrorInkRegion','grayMeasurement']}
    print(key,'native tone error',row['score']['grayErrorInkRegion'],flush=True)
(OUT/'audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
