"""Bounded, in-memory OpenCV preparation and masked line-art cleanup."""
import base64, binascii, io, math
import cv2
import numpy as np
from PIL import Image, ImageOps

def decode(value,*,preserve_alpha=False):
    if not isinstance(value,str) or not value.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):raise ValueError('صيغة الصورة غير مناسبة.')
    try:raw=base64.b64decode(value.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):raise ValueError('بيانات الصورة غير صحيحة.')
    if not 0<len(raw)<=6_000_000:raise ValueError('تجاوز حجم الصورة الحد.')
    try:
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        if im.width*im.height>4_000_000:raise ValueError('الصورة تتجاوز أربعة ملايين بكسل.')
        rgba=im.convert('RGBA')
        if preserve_alpha:return np.array(rgba)
        bg=Image.new('RGBA',rgba.size,'white');bg.alpha_composite(rgba)
        return np.array(bg.convert('RGB'))
    except OSError:raise ValueError('تعذر قراءة الصورة.')

def encode(image):
    buffer=io.BytesIO();Image.fromarray(image).save(buffer,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()

def process(data):
    rgb=decode(data.get('image'));s=data.get('settings',{})
    if not isinstance(s,dict):raise ValueError('إعدادات غير مناسبة.')
    def number(key,default,lo,hi):
        value=s.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('قيمة غير مناسبة: '+key)
        return float(value)
    if data.get('action')=='pre':
        x=number('cropX',0,0,95)/100;y=number('cropY',0,0,95)/100
        cw=number('cropW',100,5,100)/100;ch=number('cropH',100,5,100)/100
        if x+cw>1.00001 or y+ch>1.00001:raise ValueError('القص يتجاوز حدود الصورة.')
        h,w=rgb.shape[:2];rgb=rgb[int(y*h):max(int(y*h)+2,int((y+ch)*h)),int(x*w):max(int(x*w)+2,int((x+cw)*w))]
        original_near_white=np.all(rgb>=245,axis=2)
        denoise=number('denoise',0,0,100)
        if denoise:rgb=cv2.bilateralFilter(rgb,9,denoise,35)
        exposure=number('exposure',0,-2,2)
        brightness=number('brightness',0,-60,60)
        gamma=number('gamma',100,50,200)
        tonal_contrast=number('tonalContrast',100,50,180)
        shadows=number('shadows',0,-100,100)/100
        highlights=number('highlights',0,-100,100)/100
        blacks=number('blacks',0,-100,100)/100
        whites=number('whites',0,-100,100)/100
        saturation=number('saturation',100,0,180)/100
        warmth=number('warmth',0,-100,100)/100
        sharpness=number('sharpness',0,0,100)/100
        if any((exposure,brightness,gamma!=100,tonal_contrast!=100,shadows,highlights,blacks,whites,saturation!=1,warmth,sharpness)):
            pixels=rgb.astype(np.float32)/255
            if exposure:
                # Exposure is measured in stops, applied in linear light.
                linear=np.where(pixels<=.04045,pixels/12.92,((pixels+.055)/1.055)**2.4)
                linear=np.clip(linear*(2**exposure),0,1)
                pixels=np.where(linear<=.0031308,linear*12.92,1.055*linear**(1/2.4)-.055)
            pixels=np.clip(pixels+brightness/255,0,1)**(100/gamma)
            luma=pixels@np.array([.2126,.7152,.0722],dtype=np.float32)
            # Smooth tonal masks avoid hard region boundaries; all channels receive the same offset.
            adjustment=.35*(shadows*(1-luma)**2+highlights*luma**2)+.20*(blacks*(1-luma)**4+whites*luma**4)
            pixels=np.clip(pixels+adjustment[:,:,None],0,1)
            pixels=np.clip((pixels-.5)*(tonal_contrast/100)+.5,0,1)
            luma=(pixels@np.array([.2126,.7152,.0722],dtype=np.float32))[:,:,None]
            pixels=np.clip(luma+(pixels-luma)*saturation,0,1)
            pixels=np.clip(pixels+np.array([.08,0,-.08],dtype=np.float32)*warmth,0,1)
            if sharpness:
                blurred=cv2.GaussianBlur(pixels,(0,0),1.2)
                pixels=np.clip(pixels+(pixels-blurred)*sharpness*1.5,0,1)
            rgb=np.rint(pixels*255).astype(np.uint8)
        contrast=number('contrast',0,0,100)
        if contrast:
            lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);lab[:,:,0]=cv2.createCLAHE(clipLimit=1+contrast/35,tileGridSize=(8,8)).apply(lab[:,:,0]);rgb=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)
        newly_clipped=np.all(rgb>=250,axis=2)&~original_near_white
        return {'image':encode(rgb),'width':rgb.shape[1],'height':rgb.shape[0],
                'newlyClippedHighlightsPercent':round(float(newly_clipped.mean()*100),2)}
    if data.get('action')!='post':raise ValueError('مرحلة غير مناسبة.')
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);base=gray.copy()
    strength=number('strength',100,25,200)/100;weak=number('weak',0,0,100)/100
    ink=(1-gray.astype(np.float32)/255)*strength
    ink=np.clip((ink-weak)/max(.01,1-weak),0,1)
    out=np.rint(255*(1-ink)).astype(np.uint8)
    threshold=number('threshold',180,30,245);binary=s.get('binary',False)
    if not isinstance(binary,bool):raise ValueError('خيار الحبر غير مناسب.')
    if binary:out=cv2.threshold(out,threshold,255,cv2.THRESH_BINARY)[1]
    weight=round(number('weight',0,-2,2))
    if weight:
        kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
        out=(cv2.erode if weight>0 else cv2.dilate)(out,kernel,iterations=abs(weight))
    minimum=round(number('specks',0,0,150));removed=0
    if minimum:
        count,labels,stats,_=cv2.connectedComponentsWithStats((out<200).astype(np.uint8),8)
        small=np.where(stats[:,cv2.CC_STAT_AREA]<minimum)[0];small=small[small!=0];removed=len(small)
        out[np.isin(labels,small)]=255
    protected=0
    if data.get('mask'):
        mask=decode(data['mask'])
        if mask.shape!=rgb.shape:raise ValueError('قناع الفرشاة لا يطابق الصورة.')
        # Mask uses black background; R=protect, G=lighten, B=erase.
        protect=(mask[:,:,0]>127)&(mask[:,:,1]<127)&(mask[:,:,2]<127)
        lighten=(mask[:,:,1]>127)&(mask[:,:,0]<127)
        erase=(mask[:,:,2]>127)&(mask[:,:,0]<127)
        protected=int(protect.sum());original=cv2.threshold(base,threshold,255,cv2.THRESH_BINARY)[1] if binary else base
        out[protect]=original[protect]
        reduction=number('localReduction',65,0,100)/100
        out[lighten]=np.round(out[lighten]+(255-out[lighten].astype(float))*reduction).astype(np.uint8)
        if binary:out[lighten]=np.where(out[lighten]<threshold,0,255)
        out[erase]=255
    return {'image':encode(out),'width':out.shape[1],'height':out.shape[0],'removedComponents':removed,'protectedPixels':protected,'inkPixelsBefore':int((base<200).sum()),'inkPixelsAfter':int((out<200).sum())}
