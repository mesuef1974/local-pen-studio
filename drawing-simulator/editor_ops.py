"""Bounded image-editor operations. All pixels stay local and in memory."""
import base64, io, math
import cv2
import numpy as np
from PIL import Image, ImageOps, ImageFilter
from lineart_processing import decode, encode


def operate(data):
    image=decode(data.get('image'));h,w=image.shape[:2]
    op=data.get('operation');s=data.get('settings',{})
    if not isinstance(s,dict):raise ValueError('إعدادات غير صحيحة.')
    def number(name,default,low,high):
        value=s.get(name,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('قيمة غير مناسبة: '+name)
        return value
    pil=Image.fromarray(image)
    geometry=False
    if op=='crop':
        x=int(number('x',0,0,w-2));y=int(number('y',0,0,h-2))
        cw=int(number('width',w,2,w));ch=int(number('height',h,2,h))
        if x+cw>w or y+ch>h:raise ValueError('القص خارج الصورة.')
        out=image[y:y+ch,x:x+cw].copy();geometry=True
    elif op=='resize':
        width=int(number('width',w,2,2000));height=int(number('height',h,2,2000))
        out=np.array(pil.resize((width,height),Image.Resampling.LANCZOS));geometry=True
    elif op in ('rotate','flipX','flipY'):
        out=np.array(pil.rotate(-int(number('angle',90,-270,270)),expand=True) if op=='rotate' else ImageOps.mirror(pil) if op=='flipX' else ImageOps.flip(pil));geometry=True
    elif op=='gray':out=cv2.cvtColor(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),cv2.COLOR_GRAY2RGB)
    elif op=='invert':out=255-image
    elif op=='autocontrast':out=np.array(ImageOps.autocontrast(pil,cutoff=.5,preserve_tone=True))
    elif op=='blur':out=np.array(pil.filter(ImageFilter.GaussianBlur(number('amount',2,.1,15))))
    elif op=='median':out=cv2.medianBlur(image,3)
    elif op=='sharpen':out=np.array(pil.filter(ImageFilter.UnsharpMask(radius=1.2,percent=120,threshold=3)))
    elif op=='threshold':
        gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
        out=cv2.cvtColor(cv2.threshold(gray,int(number('amount',180,0,255)),255,cv2.THRESH_BINARY)[1],cv2.COLOR_GRAY2RGB)
    elif op=='wand':
        x=int(number('x',0,0,w-1));y=int(number('y',0,0,h-1));tol=int(number('tolerance',25,0,100))
        mask=np.zeros((h+2,w+2),np.uint8)
        cv2.floodFill(image.copy(),mask,(x,y),(0,0,0),(tol,)*3,(tol,)*3,flags=cv2.FLOODFILL_MASK_ONLY|cv2.FLOODFILL_FIXED_RANGE|(255<<8)|4)
        return {'mask':encode(mask[1:-1,1:-1]),'width':w,'height':h}
    elif op=='inpaint':
        if not data.get('selection'):raise ValueError('حدد المنطقة المراد ترميمها أولًا.')
        mask=decode(data['selection'])
        if mask.shape!=image.shape:raise ValueError('التحديد لا يطابق الصورة.')
        out=cv2.inpaint(image,cv2.cvtColor(mask,cv2.COLOR_RGB2GRAY),3,cv2.INPAINT_TELEA)
    elif op=='export':out=image
    else:raise ValueError('أداة غير معروفة.')
    if data.get('selection') and not geometry and op not in ('inpaint','export'):
        mask=decode(data['selection'])
        if mask.shape!=image.shape:raise ValueError('التحديد لا يطابق الصورة.')
        alpha=cv2.cvtColor(mask,cv2.COLOR_RGB2GRAY).astype(np.float32)[:,:,None]/255
        out=np.rint(out*alpha+image*(1-alpha)).astype(np.uint8)
    dpi=int(number('dpi',300,36,1200));buffer=io.BytesIO()
    Image.fromarray(out).save(buffer,format='PNG',dpi=(dpi,dpi))
    return {'image':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),'width':out.shape[1],'height':out.shape[0],'dpi':dpi,'geometry':geometry}
