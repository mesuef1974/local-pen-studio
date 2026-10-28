"""Independent fixed-pen SVG raster audit. Scores ink masks, never face identity."""
import base64
import hashlib
import io
import math
import cv2
import numpy as np
from PIL import Image, ImageOps


def decode_image(encoded):
    from generation import image_bytes
    raw=image_bytes(encoded)
    image=ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGBA')
    if max(image.size)>4096:raise ValueError('أكبر ضلع للتخطيط والتدقيق 4096 بكسل؛ صغّر النسخة دون تغيير الأصل.')
    canvas=Image.new('RGBA',image.size,'white');canvas.alpha_composite(image)
    rgb=np.asarray(canvas.convert('RGB'))
    return rgb,cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)


def ink_mask(gray,threshold=0):
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=245:
        raise ValueError('عتبة الحبر خارج النطاق.')
    level,mask=cv2.threshold(gray,threshold,255,cv2.THRESH_BINARY_INV+(cv2.THRESH_OTSU if threshold==0 else 0))
    return mask,float(level)


def validate_physics(data):
    scale=data.get('mmPerPixel');pen=data.get('penMm',.3)
    for value,low,high in [(scale,.005,5),(pen,.05,1.2)]:
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('يلزم قياس صحيح للصورة بالمليمتر وقطر القلم.')
    return float(scale),float(pen)


def validate_paths(paths,width,height):
    if not isinstance(paths,list) or len(paths)>6000:raise ValueError('عدد مسارات التدقيق أكبر من الحد.')
    count=0
    for path in paths:
        if not isinstance(path,list) or len(path)<2:raise ValueError('مسار غير صالح.')
        count+=len(path)
        if count>400_000:raise ValueError('نقاط كثيرة للتدقيق؛ اختصر المسار دون حذف ملامحه.')
        for point in path:
            if not isinstance(point,(list,tuple)) or len(point)!=2:raise ValueError('نقطة غير صالحة.')
            for value,limit in zip(point,(width,height)):
                if type(value) not in (int,float) or not math.isfinite(value) or not -.5<=value<=limit-.5:
                    raise ValueError('إحداثيات المسار خارج الصورة.')


def render_svg(paths,width,height,pen_pixels,upscale=4):
    import cairosvg
    pad=max(3,math.ceil(pen_pixels)+2)
    if max(width+2*pad,height+2*pad)>8192 or (width+2*pad)*(height+2*pad)>40_000_000:
        raise ValueError('أثر القلم بالنسبة إلى الصورة أكبر من مساحة التدقيق الآمنة؛ كبّر حجم الرسم أو قلّل سماكة القلم.')
    scale=min(upscale,max(1,int(min(8192/max(width+2*pad,height+2*pad),
        math.sqrt(40_000_000/((width+2*pad)*(height+2*pad)))))))
    pieces=[]
    for path in paths:
        pieces.append('<path d="'+' '.join(f'{"M" if i==0 else "L"}{x:.6f},{y:.6f}' for i,(x,y) in enumerate(path))+'"/>')
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad-.5} {-pad-.5} {width+2*pad} {height+2*pad}">'
         f'<g fill="none" stroke="black" stroke-width="{pen_pixels:.9f}" stroke-linecap="round" stroke-linejoin="round">'+''.join(pieces)+'</g></svg>')
    raw=cairosvg.svg2png(bytestring=svg.encode(),output_width=(width+2*pad)*scale,
        output_height=(height+2*pad)*scale,background_color='white')
    return np.asarray(Image.open(io.BytesIO(raw)).convert('L')),pad,scale


def png_data(array):
    buffer=io.BytesIO();Image.fromarray(array).save(buffer,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()


def measure(rgb,gray,mask,paths,mm_per_pixel,pen_mm,include_images=True):
    height,width=gray.shape
    reconstruction,pad,upscale=render_svg(paths,width,height,pen_mm/mm_per_pixel,
        upscale=8 if pen_mm/mm_per_pixel<1 else 4)
    target=cv2.copyMakeBorder(cv2.resize(mask,(width*upscale,height*upscale),interpolation=cv2.INTER_NEAREST),
        pad*upscale,pad*upscale,pad*upscale,pad*upscale,cv2.BORDER_CONSTANT,value=0)>0
    actual=reconstruction<128
    both=int(np.count_nonzero(target&actual));missing=int(np.count_nonzero(target&~actual));extra=int(np.count_nonzero(~target&actual))
    expected=int(target.sum());drawn=int(actual.sum());union=both+missing+extra
    # Compare tones at the source pixel resolution. Interpolating a black/white
    # reference upwards would invent gray edge bands and inflate the tone error.
    crop=reconstruction[pad*upscale:(pad+height)*upscale,pad*upscale:(pad+width)*upscale]
    native=cv2.resize(crop,(width,height),interpolation=cv2.INTER_AREA)
    roi=(mask>0)|(native<250)
    difference=np.abs(gray.astype(np.int16)-native.astype(np.int16))
    colored=np.max(rgb,axis=2).astype(np.int16)-np.min(rgb,axis=2).astype(np.int16)>16
    result={'inkIoU':round(100*both/union,2) if union else 100,
        'inkRecall':round(100*both/expected,2) if expected else 100,
        'inkPrecision':round(100*both/drawn,2) if drawn else (100 if not expected else 0),
        'grayErrorInkRegion':round(float(difference[roi].mean())/255*100,2) if roi.any() else 0,
        'missingInkPercent':round(100*missing/expected,2) if expected else 0,
        'extraInkPercent':round(100*extra/drawn,2) if drawn else 0,
        'coloredPixelsPercent':round(float(colored.mean())*100,2),
        'penMm':pen_mm,'mmPerPixel':mm_per_pixel,'auditUpscale':upscale,
        'auditIncludesOutsideImage':True,'scope':'thresholded ink mask; not identity or full-color equivalence',
        'grayMeasurement':'native source resolution; union of target ink and reconstructed pixels below 250',
        'renderer':'CairoSVG round-cap round-join physical pen footprint'}
    if include_images:
        result['reconstruction']=png_data(native)
        heat=np.full((*target.shape,3),255,np.uint8);heat[target&actual]=[35,49,61];heat[target&~actual]=[214,58,64];heat[~target&actual]=[50,107,213]
        heat=cv2.resize(heat,(width+2*pad,height+2*pad),interpolation=cv2.INTER_AREA)
        result['difference']=png_data(heat)
        result['target']=png_data(255-mask)
    return result


def audit(data):
    rgb,gray=decode_image(data.get('image'));scale,pen=validate_physics(data)
    paths=data.get('paths');validate_paths(paths,gray.shape[1],gray.shape[0])
    mask,threshold=ink_mask(gray,data.get('inkThreshold',0))
    return measure(rgb,gray,mask,paths,scale,pen)|{'threshold':threshold,
        'inputHash':hashlib.sha256(data['image'].encode()).hexdigest()}


def webgpu_target(data):
    """Prepare only the packed reference mask for the browser WebGPU audit."""
    rgb,gray=decode_image(data.get('image'));scale,pen=validate_physics(data)
    height,width=gray.shape
    mask,threshold=ink_mask(gray,data.get('inkThreshold',0))
    pen_pixels=pen/scale;pad=max(3,math.ceil(pen_pixels)+2)
    if max(width+2*pad,height+2*pad)>8192 or (width+2*pad)*(height+2*pad)>40_000_000:
        raise ValueError('أثر القلم بالنسبة إلى الصورة أكبر من مساحة التدقيق الآمنة؛ كبّر حجم الرسم أو قلّل سماكة القلم.')
    upscale=min(8 if pen_pixels<1 else 4,max(1,int(min(8192/max(width+2*pad,height+2*pad),
        math.sqrt(40_000_000/((width+2*pad)*(height+2*pad)))))))
    scaled=cv2.resize(mask,(width*upscale,height*upscale),interpolation=cv2.INTER_NEAREST)
    target=cv2.copyMakeBorder(scaled,pad*upscale,pad*upscale,pad*upscale,pad*upscale,
        cv2.BORDER_CONSTANT,value=0)>0
    packed=np.packbits(target.reshape(-1),bitorder='little')
    packed=np.pad(packed,(0,(-packed.size)%4))
    colored=np.max(rgb,axis=2).astype(np.int16)-np.min(rgb,axis=2).astype(np.int16)>16
    edge_density=float(np.mean(cv2.Canny(gray,60,140)>0))
    return {'width':int(target.shape[1]),'height':int(target.shape[0]),
        'sourceWidth':width,'sourceHeight':height,'pad':pad*upscale,
        'bitsBase64':base64.b64encode(packed.tobytes()).decode(),
        'expected':int(np.count_nonzero(target)),'threshold':threshold,
        'coloredPixelsPercent':round(float(colored.mean())*100,2),
        'edgeDensity':round(edge_density,6),
        'penMm':pen,'mmPerPixel':scale,'auditUpscale':upscale,
        'auditIncludesOutsideImage':True,
        'inputHash':hashlib.sha256(data['image'].encode()).hexdigest()}
