"""Local adapter for the user's installed trace-mascot-svg skill, not a substitute tracer."""
import base64
import binascii
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parent
SKILL_ROOT=Path.home()/'.codex/plugins/cache/created-by-me-remote/trace-mascot-svg/0.1.0/skills/trace-mascot-svg'
DEFAULTS=dict(alphaSigma=.55,graySigma=.65,median=3,component=80,turdsize=9,alphamax=1.15,tolerance=.45,resolution=2000)
OUTPUT_FILES={'vector.svg':'trace-vector.svg','master.svg':'trace-master.svg','preview.png':'trace-preview.png','validation.json':'trace-validation.json'}


def decode(value):
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,'):raise ValueError('استخدم صورة PNG فقط.')
    try:raw=base64.b64decode(value.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):raise ValueError('بيانات الصورة غير صحيحة.')
    if not 0<len(raw)<=6_000_000:raise ValueError('الحد الأقصى لملف PNG هو 6 ميغابايت.')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG' or image.width*image.height>4_000_000 or min(image.size)<3:raise ValueError('استخدم PNG حتى أربعة ملايين بكسل وبأبعاد 3 بكسل أو أكثر.')
            rgba=ImageOps.exif_transpose(image).convert('RGBA')
    except (OSError,Image.DecompressionBombError):raise ValueError('تعذر قراءة الصورة.')
    return rgba,raw


def inspect(data):
    image,_=decode(data.get('image'));a=np.asarray(image);visible=a[:,:,3]>127
    alpha=bool(visible.any() and (a[:,:,3]<128).any())
    rgb=a[:,:,:3][visible].astype(np.int16)
    colored=bool(len(rgb) and np.mean(rgb.max(axis=1)-rgb.min(axis=1)>12)>.01)
    return dict(width=image.width,height=image.height,transparent=alpha,colored=colored,ready=alpha and not colored)


def validated(values):
    if not isinstance(values,dict) or set(values)-set(DEFAULTS):raise ValueError('إعدادات تريس غير صحيحة.')
    s=DEFAULTS|values
    bounds=dict(alphaSigma=(0,1.5),graySigma=(0,2),median=(1,5),component=(0,300),turdsize=(0,50),alphamax=(0,1.334),tolerance=(0,1),resolution=(256,2000))
    for key,(lo,hi) in bounds.items():
        v=s[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('قيمة خارج النطاق: '+key)
        if key in ['median','component','turdsize','resolution']:
            if v!=int(v):raise ValueError('يلزم عدد صحيح: '+key)
            s[key]=int(v)
    if s['median'] not in [1,3,5]:raise ValueError('اختر نافذة Median بحجم 1 أو 3 أو 5.')
    return s


def invoke(script_name,raw,arguments,output_names,timeout=180):
    script=SKILL_ROOT/'scripts'/script_name
    if not script.is_file():raise ValueError('برنامج مهارة تريس المثبتة غير موجود.')
    # WSL does not mount this user's Windows workspace. Transfer fixed scripts and
    # request bytes over stdin; filenames and command arguments never form shell code.
    runner='''import base64,json,pathlib,subprocess,sys,tempfile
p=json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix='trace-studio-') as t:
 d=pathlib.Path(t);script=d/'skill.py';src=d/'source.png'
 script.write_bytes(base64.b64decode(p['script']));src.write_bytes(base64.b64decode(p['image']))
 args=[str(d/x[1:]) if x.startswith('@') else x for x in p['args']]
 r=subprocess.run(['python3',str(script),str(src),*args],capture_output=True,timeout=160)
 if r.returncode:sys.exit(2)
 print(json.dumps({name:base64.b64encode((d/name).read_bytes()).decode() for name in p['outputs']}))
'''
    payload=dict(script=base64.b64encode(script.read_bytes()).decode(),image=base64.b64encode(raw).decode(),args=arguments,outputs=output_names)
    try:
        done=subprocess.run(['wsl.exe','-e','python3','-c',runner],input=json.dumps(payload).encode(),capture_output=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (subprocess.TimeoutExpired,FileNotFoundError):raise ValueError('تعذر تشغيل بيئة تريس المحلية أو انتهت المهلة. جرّب دقة أقل.')
    if done.returncode:raise ValueError('فشل تشغيل مهارة تريس. تحقق من WSL وlibpotrace وInkscape، أو خفّف الدقة.')
    try:return {key:base64.b64decode(value,validate=True) for key,value in json.loads(done.stdout).items()}
    except (ValueError,TypeError):raise ValueError('استجابة غير متوقعة من مهارة تريس.')


def grayscale(data):
    meta=inspect(data)
    if not meta['transparent']:raise ValueError('تحويل الرمادي لا يزيل الخلفية. استخدم رسمًا بخلفية شفافة أولًا.')
    _,raw=decode(data.get('image'))
    result=invoke('prepare_grayscale.py',raw,['--output','@prepared.png','--median','1'],['prepared.png'],60)
    return {'image':'data:image/png;base64,'+base64.b64encode(result['prepared.png']).decode()}


def run_trace(data):
    start=time.perf_counter();s=validated(data.get('settings',{}));meta=inspect(data)
    if not meta['transparent']:raise ValueError('تريس يحتاج رسمًا بخلفية شفافة؛ الصورة المعتمة لا تُحوّل هنا.')
    if meta['colored']:raise ValueError('المصدر ملوّن. اختر «إعداد نسخة رمادية» صراحةً ثم راجعها قبل التحويل.')
    image,original=decode(data.get('image'));image.thumbnail((s['resolution'],s['resolution']),Image.Resampling.LANCZOS)
    buffer=io.BytesIO();image.save(buffer,format='PNG');raw=buffer.getvalue()
    if not inspect({'image':'data:image/png;base64,'+base64.b64encode(raw).decode()})['transparent']:raise ValueError('الرسم فارغ عند هذه الدقة.')
    args=['--out-dir','@.','--prefix','trace','--render','--alpha-sigma',str(s['alphaSigma']),'--gray-sigma',str(s['graySigma']),'--median-size',str(s['median']),'--min-component',str(s['component']),'--turdsize',str(s['turdsize']),'--alphamax',str(s['alphamax']),'--opttolerance',str(s['tolerance'])]
    files=invoke('vectorize.py',raw,args,list(OUTPUT_FILES.values()))
    final=ET.fromstring(files['trace-vector.svg']);master=ET.fromstring(files['trace-master.svg']);ns='{http://www.w3.org/2000/svg}'
    if final.findall('.//'+ns+'image'):raise ValueError('التحقق فشل: SVG النهائي يتضمن صورة نقطية.')
    reference=master.find(f"{ns}g[@id='reference-png']")
    if reference is None or reference.get('style')!='display:none' or reference.get('{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}insensitive')!='true':raise ValueError('التحقق فشل: طبقة المرجع ليست مقفلة ومخفية.')
    paths=final.findall('.//'+ns+'path')
    if not paths:raise ValueError('لم يبق رسم بعد التنقية. خفّض حذف المكونات والبقع.')
    report=json.loads(files['trace-validation.json'])
    report.update(actual_tonal_layers=len(final.findall(ns+'g')),source_sha256=hashlib.sha256(original).hexdigest(),skill='trace-mascot-svg 0.1.0')
    report['source']='approved-input.png';report['settings'].pop('input',None);report['settings'].pop('out_dir',None)
    report['settings']['source_resolution_limit']=s['resolution']
    job=uuid.uuid4().hex;folder=ROOT/'output'/job;folder.mkdir(parents=True)
    (folder/'approved-input.png').write_bytes(original)
    for name,value in files.items():(folder/name).write_bytes(value)
    (folder/'trace-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(job=job,preview='data:image/png;base64,'+base64.b64encode(files['trace-preview.png']).decode(),width=image.width,height=image.height,segments=report['bezier_segments'],layers=report['actual_tonal_layers'],vectorBytes=len(files['trace-vector.svg']),rasters=0,seconds=round(time.perf_counter()-start,2),downloads={key:f'/output/{job}/{value}' for key,value in OUTPUT_FILES.items()})
