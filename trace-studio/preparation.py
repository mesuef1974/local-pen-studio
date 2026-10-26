"""Explicit photo preparation before the installed Trace skill. Original bytes are not overwritten."""
import base64,binascii,io,json,math,subprocess,time
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageOps
from processing import decode,inspect

ROOT=Path(__file__).resolve().parent
CUTOUT_CACHE=OrderedDict()
DEFAULTS=dict(background='auto',style='tones',levels=12,denoise=45,contrast=110,brightness=0,tolerance=25)

def encoded(image):
    b=io.BytesIO();image.save(b,format='PNG');return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()

def import_image(data):
    value=data.get('image','')
    if not isinstance(value,str) or not value.startswith('data:') or ';base64,' not in value:raise ValueError('اختر صورة مدعومة.')
    try:raw=base64.b64decode(value.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):raise ValueError('بيانات الصورة غير صحيحة.')
    if not 0<len(raw)<=15_000_000:raise ValueError('الحد الأقصى للاستيراد 15 ميغابايت.')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ['PNG','JPEG','WEBP','BMP','TIFF','GIF']:raise ValueError('استخدم PNG أو JPG أو WebP أو BMP أو TIFF أو GIF.')
            if image.width*image.height>40_000_000 or min(image.size)<3:raise ValueError('استخدم صورة حتى 40 مليون بكسل وبأبعاد 3 بكسل أو أكثر.')
            size=image.size;animated=getattr(image,'n_frames',1)>1
            image=ImageOps.exif_transpose(image).convert('RGBA');image.thumbnail((2000,2000),Image.Resampling.LANCZOS)
            result=encoded(image)
            while len(result)>8_000_000:
                image.thumbnail((int(image.width*.9),int(image.height*.9)),Image.Resampling.LANCZOS);result=encoded(image)
    except (OSError,Image.DecompressionBombError):raise ValueError('الصورة تالفة أو لا يمكن قراءتها.')
    meta=inspect({'image':result})
    return dict(image=result,meta=meta,originalWidth=size[0],originalHeight=size[1],resized=size!=image.size,firstFrame=animated)

def validate(supplied):
    if not isinstance(supplied,dict) or set(supplied)-set(DEFAULTS):raise ValueError('إعدادات تجهيز غير صحيحة.')
    s=DEFAULTS|supplied
    if s['background'] not in ['auto','subject','keep','border'] or s['style'] not in ['tones','ink','gray']:raise ValueError('طريقة تجهيز غير صحيحة.')
    for key,lo,hi in [('levels',4,32),('denoise',0,100),('contrast',50,180),('brightness',-60,60),('tolerance',0,100)]:
        value=s[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi or int(value)!=value:raise ValueError('قيمة غير مناسبة: '+key)
        s[key]=int(value)
    return s

def remove_subject(image):
    python=ROOT.parent/'drawing-simulator/.venv-background/Scripts/python.exe'
    if not python.is_file():raise ValueError('بيئة إزالة الخلفية المحلية غير متاحة.')
    try:
        result=subprocess.run([str(python),str(ROOT/'background_worker.py')],input=json.dumps({'image':image}),capture_output=True,text=True,encoding='utf-8',timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired:raise ValueError('انتهت مهلة إزالة الخلفية. جرّب دقة أصغر أو خلفية بسيطة.')
    try:data=json.loads(result.stdout)
    except ValueError:raise ValueError('تعذر تشغيل إزالة الخلفية المحلية.')
    if result.returncode or data.get('error'):raise ValueError(data.get('error','تعذرت إزالة الخلفية.'))
    return data['image']

def border_alpha(image,tolerance):
    a=np.asarray(image).copy();rgb=a[:,:,:3].copy();h,w=rgb.shape[:2]
    flood=np.zeros((h+2,w+2),np.uint8)
    # Connected exterior color removal, not semantic object segmentation.
    for seed in [(0,0),(w-1,0),(0,h-1),(w-1,h-1)]:
        cv2.floodFill(rgb,flood,seed,(0,0,0),(tolerance,)*3,(tolerance,)*3,4|cv2.FLOODFILL_MASK_ONLY|cv2.FLOODFILL_FIXED_RANGE|(255<<8))
    a[:,:,3][flood[1:-1,1:-1]>0]=0
    return Image.fromarray(a)

def prepare(data,*,require_transparency=True):
    start=time.perf_counter();s=validate(data.get('settings',{}));source,_=decode(data.get('image'));source_url=data['image'];info=inspect({'image':source_url})
    method=s['background'];key=sha256((source_url+'|'+method+'|'+str(s['tolerance'] if method=='border' else 0)).encode()).hexdigest();cached=key in CUTOUT_CACHE
    if cached:
        cutout=CUTOUT_CACHE[key].copy();CUTOUT_CACHE.move_to_end(key)
    else:
        if method=='subject' or (method=='auto' and not info['transparent']):cutout,_=decode(remove_subject(source_url))
        elif method=='border':cutout=border_alpha(source,s['tolerance'])
        else:cutout=source.copy()
        alpha=np.asarray(cutout)[:,:,3]
        if not (alpha>127).any():raise ValueError('لم يبق موضوع ظاهر بعد إزالة الخلفية. جرّب طريقة أخرى أو خفّض تسامح الخلفية.')
        if require_transparency and not (alpha<128).any():raise ValueError('الخلفية ما زالت معتمة. اختر فصل الموضوع أو إزالة الخلفية البسيطة؛ لا تُضاف شفافية وهمية حول الصورة.')
        CUTOUT_CACHE[key]=cutout.copy()
        while len(CUTOUT_CACHE)>2:CUTOUT_CACHE.popitem(last=False)
    if require_transparency and not (np.asarray(cutout)[:,:,3]<128).any():raise ValueError('الخلفية ما زالت معتمة؛ تريس يحتاج شفافية فعلية.')
    a=np.asarray(cutout);gray=cv2.cvtColor(a[:,:,:3],cv2.COLOR_RGB2GRAY)
    if s['denoise']:gray=cv2.bilateralFilter(gray,7,5+s['denoise']*.9,5+s['denoise']*.1)
    gray=np.rint(np.clip((gray.astype(np.float32)-127.5)*s['contrast']/100+127.5+s['brightness'],0,255)).astype(np.uint8)
    if s['style']=='tones':gray=np.rint(np.rint(gray.astype(np.float32)/255*(s['levels']-1))*255/(s['levels']-1)).astype(np.uint8)
    elif s['style']=='ink':gray=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,9)
    # Alpha is retained exactly after the selected background extraction.
    rgba=np.dstack((gray,gray,gray,a[:,:,3]));out=encoded(Image.fromarray(rgba));meta=inspect({'image':out})
    return dict(image=out,meta=meta,seconds=round(time.perf_counter()-start,2),backgroundCached=cached,backgroundMethod=method,levels=s['levels'] if s['style']=='tones' else None)
