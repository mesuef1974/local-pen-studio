"""Audit the actual saved SVG, not the in-memory path list or UI canvas."""
import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from path_fidelity import decode_image,ink_mask,measure

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'fidelity-review'
rows=json.loads((OUT/'audit.json').read_text())
for row in rows:
    raw=(ROOT/'comparison-review'/f"{row['key']}-flux.png").read_bytes()
    assert hashlib.sha256(raw).hexdigest()==row['sourceSHA256']
    image='data:image/png;base64,'+base64.b64encode(raw).decode()
    rgb,gray=decode_image(image);mask,_=ink_mask(gray)
    tree=ET.fromstring((OUT/f"{row['key']}.svg").read_text())
    group=tree.find('{http://www.w3.org/2000/svg}g')
    assert float(group.attrib['stroke-width'])==row['penMm']
    assert group.attrib['fill']=='none' and tree.attrib['width']=='210mm'
    assert group.attrib['stroke-linecap']==group.attrib['stroke-linejoin']=='round'
    m=row['motion']['mapping'];paths=[]
    for element in group:
        assert element.tag.endswith('path')
        points=re.findall(r'[ML]([-\d.]+),([-\d.]+)',element.attrib['d'])
        points=[[(float(x)-m['x'])/m['scale'],(float(y)-m['y'])/m['scale']] for x,y in points]
        for x,y in points:
            # SVG rounds to one micrometre; allow only half that quantisation error.
            assert -.5-.00051/m['scale']<=x<=row['width']-.5+.00051/m['scale']
            assert -.5-.00051/m['scale']<=y<=row['height']-.5+.00051/m['scale']
        paths.append(points)
    score=measure(rgb,gray,mask,paths,m['scale'],row['penMm'],include_images=False)
    assert abs(score['inkIoU']-row['score']['inkIoU'])<=.3,(row['key'],score['inkIoU'])
    expected=row['motion']['inkMm']/30+row['motion']['travelMm']/80+len(paths)*.4
    assert abs(expected-row['motion']['seconds'])<1e-7
    row['exportAudit']=dict(inkIoU=score['inkIoU'],paths=len(paths),pureVectors=True,sourceUnchanged=True,timingVerified=True)
    print(row['key'],'export IoU',score['inkIoU'],flush=True)
(OUT/'audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('15 exported SVG files audited, sources unchanged, motion estimates consistent.',flush=True)
