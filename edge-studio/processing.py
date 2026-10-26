"""OpenCV edge pipeline. Images stay in memory; no weights or remote calls."""
import base64
import binascii
import io
import math
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

DEFAULTS = dict(method='canny', resolution=1600, channel='gray', brightness=0,
                contrast=100, gamma=100, equalize='none', clip=2, grid=8,
                noise='gaussian', kernel=3, sigma=1.2, sigmaColor=45,
                sigmaSpace=9, nlm=8, low=60, high=150, aperture=3, l2=True,
                autoThreshold=False, autoSpread=33, gradientThreshold=24,
                anchor=4, scan=1, minPath=12, edSigma=1, edOperator=0,
                pf=False, sumFlag=True, direction='xy', derivativeKernel=3,
                edgeThreshold=45, normalizeGradient=True, morphKernel=3,
                close=0, opening=0, component=0, thin=False, thickness=1,
                ink='#142b42', background='white', overlayOpacity=70)


def decode(value):
    if not isinstance(value, str) or not value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
        raise ValueError('اختر صورة PNG أو JPG أو WebP.')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('تعذر قراءة بيانات الصورة.')
    if not 0 < len(raw) <= 6_000_000:
        raise ValueError('حجم الصورة المعالجة يتجاوز 6 ميغابايت.')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 4_000_000:
                raise ValueError('الحد الأقصى للصورة أربعة ملايين بكسل.')
            rgba = ImageOps.exif_transpose(image).convert('RGBA')
            background = Image.new('RGBA', rgba.size, 'white')
            background.alpha_composite(rgba)
            return np.asarray(background.convert('RGB'))
    except (OSError, Image.DecompressionBombError):
        raise ValueError('الصورة تالفة أو غير مدعومة.')


def encode(image):
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def settings(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError('إعدادات معالجة غير معروفة.')
    s = DEFAULTS | values
    choices = dict(method=['canny','ed','sobel','scharr','laplacian','morph'],
                   channel=['gray','lab','value','red','green','blue'],
                   equalize=['none','histogram','clahe'],
                   noise=['none','gaussian','bilateral','median','nlm'],
                   direction=['xy','x','y'], background=['white','black','transparent'])
    for key, allowed in choices.items():
        if not isinstance(s[key], str) or s[key] not in allowed:
            raise ValueError('خيار غير صحيح: ' + key)
    for key in ['l2','autoThreshold','pf','sumFlag','normalizeGradient','thin']:
        if not isinstance(s[key], bool):
            raise ValueError('خيار غير صحيح: ' + key)
    bounds = dict(resolution=(256,2000),brightness=(-100,100),contrast=(20,250),
                  gamma=(25,250),clip=(0.5,8),grid=(2,32),kernel=(3,11),sigma=(0.1,5),
                  sigmaColor=(1,150),sigmaSpace=(1,30),nlm=(1,20),low=(0,255),
                  high=(1,255),aperture=(3,7),autoSpread=(1,90),gradientThreshold=(1,120),
                  anchor=(0,50),scan=(1,8),minPath=(2,100),edSigma=(0.1,4),
                  edOperator=(0,3),derivativeKernel=(1,7),edgeThreshold=(0,255),
                  morphKernel=(3,11),close=(0,3),opening=(0,3),component=(0,500),
                  thickness=(1,5),overlayOpacity=(0,100))
    fractional = {'clip','sigma','edSigma'}
    for key, (lo, hi) in bounds.items():
        value = s[key]
        if isinstance(value, bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError('قيمة خارج النطاق: ' + key)
        if key not in fractional and value != int(value):
            raise ValueError('يلزم عدد صحيح: ' + key)
        if key not in fractional:
            s[key] = int(value)
    for key in ['kernel','morphKernel','derivativeKernel','aperture']:
        if s[key] % 2 != 1:
            raise ValueError('حجم المرشح يجب أن يكون فرديًا: ' + key)
    if s['aperture'] not in [3,5,7]:
        raise ValueError('فتحة Canny غير صحيحة.')
    if s['method']=='canny' and not s['autoThreshold'] and s['low'] >= s['high']:
        raise ValueError('اجعل العتبة العليا أكبر من العتبة الدنيا.')
    ink = s['ink']
    if not isinstance(ink,str) or len(ink)!=7 or ink[0]!='#' or any(c not in '0123456789abcdefABCDEF' for c in ink[1:]):
        raise ValueError('لون الحواف غير صحيح.')
    return s


def process(data):
    start = time.perf_counter()
    s = settings(data.get('settings', {}))
    rgb = decode(data.get('image'))
    h,w = rgb.shape[:2]
    ratio = min(1, s['resolution']/max(h,w))
    if ratio<1:
        rgb = cv2.resize(rgb,(max(1,round(w*ratio)),max(1,round(h*ratio))),interpolation=cv2.INTER_AREA)
    if s['channel']=='gray':
        gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    elif s['channel']=='lab':
        gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)[:,:,0]
    elif s['channel']=='value':
        gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)[:,:,2]
    else:
        gray = rgb[:,:,["red","green","blue"].index(s['channel'])].copy()
    values = np.arange(256,dtype=np.float32)/255
    lut = np.rint(np.clip(((np.power(values,100/s['gamma'])-.5)*s['contrast']/100+.5)*255+s['brightness'],0,255)).astype(np.uint8)
    gray = cv2.LUT(gray,lut)
    if s['equalize']=='histogram':
        gray=cv2.equalizeHist(gray)
    elif s['equalize']=='clahe':
        gray=cv2.createCLAHE(clipLimit=s['clip'],tileGridSize=(s['grid'],s['grid'])).apply(gray)
    k=s['kernel']
    if s['noise']=='gaussian': gray=cv2.GaussianBlur(gray,(k,k),s['sigma'])
    elif s['noise']=='bilateral': gray=cv2.bilateralFilter(gray,k,s['sigmaColor'],s['sigmaSpace'])
    elif s['noise']=='median': gray=cv2.medianBlur(gray,k)
    elif s['noise']=='nlm': gray=cv2.fastNlMeansDenoising(gray,None,s['nlm'],7,21)
    low,high=s['low'],s['high']
    if s['method']=='canny':
        if s['autoThreshold']:
            median=float(np.median(gray)); spread=s['autoSpread']/100
            low=int(max(0,(1-spread)*median)); high=int(min(255,max(low+1,(1+spread)*median)))
            low=min(low,high-1)
        edges=cv2.Canny(gray,low,high,apertureSize=s['aperture'],L2gradient=s['l2'])
    elif s['method']=='ed':
        if not hasattr(cv2,'ximgproc') or not hasattr(cv2.ximgproc,'createEdgeDrawing'):
            raise ValueError('هذه الطريقة تحتاج opencv-contrib-python.')
        detector=cv2.ximgproc.createEdgeDrawing();params=detector.Params()
        for name,key in [('GradientThresholdValue','gradientThreshold'),('AnchorThresholdValue','anchor'),('ScanInterval','scan'),('MinPathLength','minPath'),('Sigma','edSigma'),('EdgeDetectionOperator','edOperator'),('PFmode','pf'),('SumFlag','sumFlag')]:
            setattr(params,name,s[key])
        detector.setParams(params);detector.detectEdges(gray);edges=detector.getEdgeImage()
    else:
        if s['method']=='laplacian':
            magnitude=np.abs(cv2.Laplacian(gray,cv2.CV_32F,ksize=s['derivativeKernel']))
        elif s['method']=='morph':
            kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(s['morphKernel'],s['morphKernel']))
            magnitude=cv2.morphologyEx(gray,cv2.MORPH_GRADIENT,kernel).astype(np.float32)
        else:
            def derivative(dx,dy):
                if s['method']=='scharr':return cv2.Scharr(gray,cv2.CV_32F,dx,dy)
                return cv2.Sobel(gray,cv2.CV_32F,dx,dy,ksize=s['derivativeKernel'])
            if s['direction']=='x':magnitude=np.abs(derivative(1,0))
            elif s['direction']=='y':magnitude=np.abs(derivative(0,1))
            else:magnitude=cv2.magnitude(derivative(1,0),derivative(0,1))
        if s['normalizeGradient']:
            magnitude=cv2.normalize(magnitude,None,0,255,cv2.NORM_MINMAX)
        edges=np.where(magnitude>s['edgeThreshold'],255,0).astype(np.uint8)
    before=int(np.count_nonzero(edges))
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(s['morphKernel'],s['morphKernel']))
    if s['close']:edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,kernel,iterations=s['close'])
    if s['opening']:edges=cv2.morphologyEx(edges,cv2.MORPH_OPEN,kernel,iterations=s['opening'])
    removed=0
    if s['component']:
        _,labels,stats,_=cv2.connectedComponentsWithStats(edges,8)
        ids=np.where(stats[:,cv2.CC_STAT_AREA]<s['component'])[0];ids=ids[ids!=0]
        removed=len(ids);edges[np.isin(labels,ids)]=0
    if s['thin']:
        if not hasattr(cv2,'ximgproc'):raise ValueError('الترقيق يحتاج OpenCV contrib.')
        edges=cv2.ximgproc.thinning(edges)
    if s['thickness']>1:
        edges=cv2.dilate(edges,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(s['thickness'],s['thickness'])))
    h,w=edges.shape;mask=edges>0;color=np.array([int(s['ink'][i:i+2],16) for i in [1,3,5]],np.uint8)
    output=np.zeros((h,w,4),np.uint8)
    output[:,:,:3]=255 if s['background']=='white' else 0
    output[:,:,3]=0 if s['background']=='transparent' else 255
    output[mask,:3]=color;output[mask,3]=255
    overlay=rgb.copy();alpha=s['overlayOpacity']/100
    overlay[mask]=np.round(rgb[mask]*(1-alpha)+np.array([38,85,189])*alpha).astype(np.uint8)
    return dict(image=encode(output),prepared=encode(gray),overlay=encode(overlay),
                width=w,height=h,edgePixels=int(mask.sum()),coverage=round(float(mask.mean()*100),2),
                beforePixels=before,removedComponents=removed,low=low,high=high,
                milliseconds=round((time.perf_counter()-start)*1000,1),opencv=cv2.__version__)
