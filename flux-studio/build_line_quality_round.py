"""Original photographic references paired with controlled line-only candidates."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageOps
from build_quality_round import build
from export_quality_round import export


def line_baseline(path):
    with Image.open(path) as opened:
        image=ImageOps.exif_transpose(opened).convert('RGB')
    rgb=np.asarray(image);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    if np.mean(rgb.max(axis=2)-rgb.min(axis=2)>12)>.01 or np.mean((gray>40)&(gray<215))>.1 or np.mean(gray>=225)<.65:
        raise ValueError('يلزم رسم خطي موجود بخلفية بيضاء؛ لا تقبل صورة فوتوغرافية كمخرج.')
    result=np.where(gray<225,0,255).astype('uint8')
    verify_line(result)
    return result


def verify_line(array):
    if array.ndim!=2 or not set(np.unique(array)).issubset({0,255}):
        raise ValueError('المخرج يجب أن يكون خطوطًا سوداء وبيضاء فقط.')
    fraction=float(np.mean(array==0))
    if not .001<=fraction<=.3:raise ValueError('كثافة الحبر غير مناسبة لعينة الخطوط.')
    return {'binary':True,'inkFraction':fraction,'whiteFraction':1-fraction}


def variants(base,roi):
    h,w=base.shape;cx,cy,rx,ry=roi
    if not (0<cx<1 and 0<cy<1 and .02<=rx<=.5 and .02<=ry<=.5):raise ValueError('منطقة ضبط الوجه غير صالحة.')
    yy,xx=np.mgrid[:h,:w].astype('float32')
    weight=np.exp(-(((xx-cx*w)/(rx*w))**2+((yy-cy*h)/(ry*h))**2)*2)
    outputs={'baseline':base.copy()}
    for label,dx,dy in [('local-small',.025,0),('local-large',.09,.035)]:
        outputs[label]=cv2.remap(base,xx-dx*w*weight,yy-dy*h*weight,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
    outputs['frame-shift']=cv2.warpAffine(base,np.float32([[1,0,.1*w],[0,1,.06*h]]),(w,h),flags=cv2.INTER_NEAREST,borderValue=255)
    broken=base.copy()
    for ratio in [.2,.32,.45,.58,.72]:
        top=round(h*ratio);broken[top:top+max(3,round(h*.007)),:]=255
    outputs['line-gaps']=broken
    return outputs


def create(manifest,output,downloads):
    if output.exists():raise ValueError('اختر مجلدًا جديدًا؛ لا تستبدل جولة موجودة.')
    samples=output/'samples';samples.mkdir(parents=True)
    kinds={};provenance=[];strata={}
    for entry in manifest:
        name=entry['id']
        if not name.isascii() or not name.replace('-','').isalnum():raise ValueError('معرف مصدر غير صالح.')
        path=Path(entry['path']);base=line_baseline(path)
        reference=Path(entry['reference'])
        with Image.open(reference) as original:ImageOps.exif_transpose(original).save(samples/f'{name}-source.png')
        strata[name]='photo-to-line-controls'
        for kind,array in variants(base,entry['roi']).items():
            metrics=verify_line(array);filename=f'{name}-{kind}-flux.png'
            Image.fromarray(array).save(samples/filename);kinds[filename]='controlled-line-transform:'+kind
            provenance.append({'file':filename,'kind':kind,'baselineSHA256':hashlib.sha256(path.read_bytes()).hexdigest(),
                               'referenceSHA256':hashlib.sha256(reference.read_bytes()).hexdigest(),
                               'faceRegion':entry['roi'],'toneCheck':metrics,'changedPixels':int(np.sum(array!=base))})
    round_result=build(samples,output/'round',seed=1,strata=strata,candidate_kinds=kinds)
    page=output/'round/review.html';html=page.read_text(encoding='utf8')
    html=html.replace('قارن النتيجة بالأصل دون الرجوع إلى أسماء الأساليب أو البرومبتات.',
        'المرجع هو الصورة الأصلية، والنتيجة فقط رسم خطي معالج ينتظر تقييمك. قارن الملامح والمحيط والتكوين بالأصل. بعض النتائج تحتوي تغييرات ضبط مقصودة لاختبار حساسية القياس؛ لا تحدد الصفحة تقييمك بالنيابة عنك.')
    page.write_bytes(html.encode('utf8'))
    (output/'private-transforms.json').write_text(json.dumps(provenance,indent=2),encoding='utf8')
    destination=downloads/f"flux-original-lines-{round_result['roundId'][:8]}.html"
    portable=export(output/'round',destination)
    summary={'roundId':round_result['roundId'],'cases':round_result['cases'],'sources':round_result['sources'],
        'allCandidatesAreLineArt':True,'referenceType':'original photograph; pixels preserved after EXIF orientation',
        'generatedByFlux':False,'variantOrigin':'controlled transforms of existing FLUX lineart',
        'purpose':'original-to-line diagnostic comparison; calibration not yet validated',
        'humanRatings':'pending','privateKeyIncluded':False,'portable':portable['path']}
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--downloads',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(create(json.loads(args.manifest.read_text(encoding='utf8')),args.output,args.downloads),ensure_ascii=False))
