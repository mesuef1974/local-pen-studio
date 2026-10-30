"""Two independent quality axes; never changes workflow approval or extraction rules."""
import hashlib
import json
import math
import subprocess
from pathlib import Path
import cv2
from path_fidelity import decode_image, ink_mask

ROOT=Path(__file__).resolve().parent
RUNTIME=Path.home()/'.codex/quality-runtime/Scripts/python.exe'


def evaluate(data):
    source=data.get('source');result=data.get('result')
    decode_image(source)
    rgb,gray=decode_image(result)
    if max(gray.shape)>1024:
        raise ValueError('أقصى ضلع للنتيجة في هذه الجولة 1024 بكسل؛ استخدم نسخة قياس أصغر.')
    width_mm=data.get('widthMm',180);pen=data.get('penMm',.2)
    if type(width_mm) not in (int,float) or not math.isfinite(width_mm) or not 10<=width_mm<=1000:
        raise ValueError('عرض الرسم بالمليمتر يجب أن يكون بين 10 و1000.')
    if type(pen) not in (int,float) or not math.isfinite(pen) or not .05<=pen<=1.2:
        raise ValueError('قطر القلم خارج النطاق.')
    response={'version':'prepath-quality/1.0','automaticApproval':False,
              'sourceHash':hashlib.sha256(source.encode()).hexdigest(),
              'resultHash':hashlib.sha256(result.encode()).hexdigest()}
    if RUNTIME.is_file():
        try:
            worker=subprocess.run([str(RUNTIME),str(ROOT/'quality_features.py')],
                input=json.dumps({'source':source,'result':result}),capture_output=True,
                text=True,encoding='utf-8',timeout=45,check=False)
            response['similarity']=json.loads(worker.stdout) if worker.returncode==0 else {
                'state':'unavailable','score':None,'reason':'تعذر تشغيل كاشف المعالم المحلي؛ لا تُستنتج نسبة.'}
        except (subprocess.TimeoutExpired,json.JSONDecodeError):
            response['similarity']={'state':'unavailable','score':None,'reason':'انتهت مهلة كاشف المعالم أو تعذر تفسير خرجه.'}
    else:response['similarity']={'state':'unavailable','score':None,'reason':'بيئة القياس المحلية غير متاحة.'}
    try:
        from faithful_paths import extract
        scale=(width_mm-pen)/gray.shape[1]
        mask,_=ink_mask(gray)
        if not mask.any():
            response['traceability']={'state':'not_applicable','score':None,'reason':'الصورة خالية من الحبر؛ لا تمثل رسمًا قابلًا للتقييم.'}
            return response
        extraction=extract({'image':result,'mmPerPixel':scale,'penMm':pen,'inkThreshold':0})
        metrics=extraction['fidelity'];mask,_=ink_mask(gray)
        count,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        areas=stats[1:,cv2.CC_STAT_AREA]
        area_mm2=gray.shape[0]*gray.shape[1]*scale**2
        precision,recall=metrics['inkPrecision'],metrics['inkRecall']
        response['traceability']={'version':'fixed-pen-audit/1.0','state':'measured','score':None,
            'reason':'مؤشرات وصفية لإعادة بناء الحبر؛ لا توجد عتبة معتمدة لقابلية التتبع بعد.',
            'inkPrecision':precision,'inkRecall':recall,'inkIoU':metrics['inkIoU'],
            'inkF1':round(2*precision*recall/(precision+recall),2) if precision+recall else 0,
            'connectedInkComponents':int(count-1),
            'largestComponentInkShare':float(areas.max()/areas.sum()) if areas.size else None,
            'paths':len(extraction['paths']),'points':extraction['outputPoints'],
            'pathsPerSquareMm':len(extraction['paths'])/area_mm2,
            'pointsPerSquareMm':extraction['outputPoints']/area_mm2,
            'widthMm':width_mm,'penMm':pen,'mmPerPixel':scale,
            'scope':'candidate thresholded ink only; separate from original/candidate similarity',
            'pathsUsedForAuditOnly':True}
    except ValueError as error:
        response['traceability']={'state':'unavailable','score':None,'reason':str(error)}
    return response
