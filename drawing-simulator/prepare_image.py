"""Local deterministic preparation. No models, network calls, or saved images."""
import base64, binascii, io, math, time, threading
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

GATE = threading.BoundedSemaphore(2)

def prepare(data):
    encoded = data.get('image', '')
    if not isinstance(encoded,str) or not encoded.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):
        raise ValueError('صيغة الصورة غير مناسبة.')
    try:
        raw=base64.b64decode(encoded.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):
        raise ValueError('بيانات الصورة غير صحيحة.')
    if not 0<len(raw)<=5_000_000: raise ValueError('الصورة المرسلة تتجاوز 5 MB.')
    settings=data.get('settings',{})
    if not isinstance(settings,dict):raise ValueError('إعدادات التجهيز غير صحيحة.')
    def number(key,default,lo,hi):
        value=settings.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError('قيمة غير مناسبة للإعداد: '+key)
        return float(value)
    brightness=number('brightness',0,-50,50)
    contrast=number('contrast',100,50,180)/100
    gamma=number('gamma',100,50,200)/100
    local=number('local',0,0,100)/100
    denoise=number('denoise',0,0,100)/100
    sharp=number('sharp',0,0,100)/100
    detail=number('enhance',0,0,100)/100
    morphology=number('morphology',0,-100,100)
    edge_strength=number('edgeStrength',50,0,100)/100
    x=number('cropX',0,0,99)/100;y=number('cropY',0,0,99)/100
    width=number('cropW',100,1,100)/100;height=number('cropH',100,1,100)/100
    if x+width>1.000001 or y+height>1.000001:raise ValueError('القص يتجاوز حدود الصورة؛ عدّل العرض أو الارتفاع.')
    rotation=number('rotation',0,0,270)
    if rotation not in [0,90,180,270]:raise ValueError('زاوية الدوران غير مناسبة.')
    style=settings.get('style','photo')
    if style not in ['photo','gray','pencil','edges','binary','stylized']:raise ValueError('أسلوب التجهيز غير معروف.')
    if not GATE.acquire(blocking=False):raise ValueError('هناك عمليتا تجهيز جاريتان. حاول بعد اكتمالهما.')
    try:
        start=time.perf_counter()
        try:
            with Image.open(io.BytesIO(raw)) as original:
                if original.width*original.height>16_000_000:raise ValueError('استخدم صورة حتى 16 مليون بكسل.')
                im=ImageOps.exif_transpose(original).convert('RGBA')
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise ValueError('تعذر قراءة الصورة.')
        im.thumbnail((1800,1800),Image.Resampling.LANCZOS)
        background=Image.new('RGBA',im.size,'white');background.alpha_composite(im);im=background.convert('RGB')
        w,h=im.size;im=im.crop((round(x*w),round(y*h),round((x+width)*w),round((y+height)*h)))
        if min(im.size)<8:raise ValueError('منطقة القص أصغر من الحد المناسب.')
        if rotation:im=im.rotate(-rotation,expand=True)
        image=cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2BGR)
        if denoise:image=cv2.bilateralFilter(image,7,10+denoise*65,10+denoise*65)
        image=np.clip((image.astype(np.float32)-127.5)*contrast+127.5+brightness*2,0,255).astype(np.uint8)
        if gamma!=1:
            lut=np.clip((np.arange(256)/255)**(1/gamma)*255,0,255).astype(np.uint8);image=cv2.LUT(image,lut)
        if local:
            lab=cv2.cvtColor(image,cv2.COLOR_BGR2LAB);l=lab[:,:,0]
            enhanced=cv2.createCLAHE(clipLimit=2.5,tileGridSize=(8,8)).apply(l)
            lab[:,:,0]=cv2.addWeighted(l,1-local,enhanced,local,0);image=cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)
        if detail:
            enhanced=cv2.detailEnhance(image,sigma_s=10,sigma_r=.15);image=cv2.addWeighted(image,1-detail,enhanced,detail,0)
        if sharp:
            soft=cv2.GaussianBlur(image,(0,0),1.2);image=cv2.addWeighted(image,1+sharp*1.5,soft,-sharp*1.5,0)
        if style=='gray':image=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        elif style=='pencil':image,_=cv2.pencilSketch(image,sigma_s=60,sigma_r=.07,shade_factor=.04)
        elif style=='edges':
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);median=float(np.median(gray));image=255-cv2.Canny(gray,max(3,int(median*(.9-edge_strength*.8))),max(10,int(median*(1.8-edge_strength*1.5))))
        elif style=='binary':
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);image=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,8)
        elif style=='stylized':image=cv2.stylization(image,sigma_s=60,sigma_r=.4)
        if morphology:
            size=3+2*int(abs(morphology)/34);kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(size,size))
            image=cv2.morphologyEx(image,cv2.MORPH_CLOSE if morphology>0 else cv2.MORPH_OPEN,kernel)
        ok,buffer=cv2.imencode('.png',image)
        if not ok:raise ValueError('تعذر ترميز النتيجة.')
        return {'image':'data:image/png;base64,'+base64.b64encode(buffer).decode(),'width':image.shape[1],'height':image.shape[0],
                'milliseconds':round((time.perf_counter()-start)*1000),'libraries':{'OpenCV':cv2.__version__,'Pillow':Image.__version__},'settings':settings}
    finally:GATE.release()
