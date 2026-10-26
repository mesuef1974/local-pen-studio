"""Isolated, offline lineart inference entry point. JSON stdin/stdout only."""
import base64, io, json, sys, time, types, importlib.util, threading
from pathlib import Path
import cv2
import numpy as np
import torch
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parent
def run(data):
    model_name=data.get('model','realistic')
    if model_name != 'realistic': raise ValueError('التطبيق يدعم النموذج الدقيق فقط.')
    resolution=data.get('resolution',768)
    if resolution not in (512,768,1024):raise ValueError('دقة غير مسموحة.')
    strength=data.get('strength',100)
    threshold=data.get('threshold',180)
    binary=data.get('binary',False)
    if isinstance(strength,bool) or not isinstance(strength,(float,int)) or not 25<=strength<=200:raise ValueError('قوة الخط غير مناسبة.')
    if isinstance(threshold,bool) or not isinstance(threshold,(float,int)) or not 30<=threshold<=245 or not isinstance(binary,bool):raise ValueError('عتبة غير مناسبة.')
    encoded=data.get('image','')
    if not isinstance(encoded,str) or not encoded.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):raise ValueError('صيغة غير مسموحة.')
    raw=base64.b64decode(encoded.split(',',1)[1],validate=True)
    if len(raw)>5_000_000:raise ValueError('الصورة أكبر من 5 MB.')
    im=ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    if im.width*im.height>4_000_000:raise ValueError('الصورة تتجاوز 4 ملايين بكسل.')
    im=im.convert('RGBA'); background=Image.new('RGBA',im.size,'white');background.alpha_composite(im);im=background.convert('RGB')
    im.thumbnail((resolution,resolution));rgb=np.array(im);h,w=rgb.shape[:2]
    package=Path(importlib.util.find_spec('controlnet_aux').origin).parent
    ns=types.ModuleType('local_lineart_runtime');ns.__path__=[str(package)];sys.modules[ns.__name__]=ns
    spec=importlib.util.spec_from_file_location('local_lineart_runtime.lineart',package/'lineart/__init__.py',submodule_search_locations=[str(package/'lineart')])
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    filename='sk_model.pth'
    from huggingface_hub import hf_hub_download
    weights=hf_hub_download('lllyasviel/Annotators',filename,cache_dir=str(ROOT/'models/lineart'),local_files_only=True)
    model=module.Generator(3,1,3);model.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True));model.eval()
    device='cuda' if torch.cuda.is_available() else 'cpu';model.to(device)
    padded=cv2.copyMakeBorder(rgb,0,(-h)%64,0,(-w)%64,cv2.BORDER_REPLICATE)
    x=torch.from_numpy(padded).permute(2,0,1).unsqueeze(0).float().to(device)/255
    if device=='cuda':torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
    start=time.perf_counter()
    with torch.inference_mode():out=model(x)[0,0].cpu().numpy()[:h,:w]
    if device=='cuda':torch.cuda.synchronize()
    seconds=time.perf_counter()-start
    out=np.clip(255-(1-out)*255*strength/100,0,255).astype(np.uint8)
    if binary:out=cv2.threshold(out,threshold,255,cv2.THRESH_BINARY)[1]
    buffer=io.BytesIO();Image.fromarray(out).save(buffer,format='PNG')
    return {'image':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),'width':w,'height':h,'seconds':round(seconds,3),'device':device,'model':model_name,'peakMiB':round(torch.cuda.max_memory_allocated()/1048576) if device=='cuda' else None}
if __name__=='__main__':
    try:print(json.dumps(run(json.load(sys.stdin))))
    except ValueError as e:print(json.dumps({'error':str(e)}));sys.exit(2)
    except Exception:print(json.dumps({'error':'تعذر تشغيل النموذج المحلي. تحقق من الأوزان وذاكرة كرت الشاشة.'}));sys.exit(1)
