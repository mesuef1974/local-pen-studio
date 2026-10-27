"""Isolated rembg runtime. A downloaded model is required; requests never download."""
import base64, io, json, os, sys, time
from pathlib import Path
from types import SimpleNamespace
from PIL import Image, ImageOps, ImageChops
ROOT=Path(__file__).resolve().parent
os.environ['REMBG_HOME']=str(ROOT/'models/background')
os.environ['OMP_NUM_THREADS']='6'

def local_session(model_path, *, device='cpu', profile_path=None):
    if device not in ('cpu','cuda'):raise ValueError('جهاز إزالة الخلفية غير صحيح.')
    if device=='cuda':
        # Load the existing PyTorch CUDA/cuDNN DLLs before ONNX Runtime on Windows.
        import torch
        if not torch.cuda.is_available():raise ValueError('كرت NVIDIA غير متاح لإزالة الخلفية؛ لم يُستخدم المعالج بديلًا.')
    import onnxruntime as ort
    if device=='cuda' and 'CUDAExecutionProvider' not in ort.get_available_providers():
        raise ValueError('مشغّل CUDA لإزالة الخلفية غير جاهز؛ لم يُستخدم المعالج بديلًا.')
    options=ort.SessionOptions();options.intra_op_num_threads=6;options.inter_op_num_threads=6
    if profile_path:
        options.enable_profiling=True;options.profile_file_prefix=str(profile_path)
    providers=['CPUExecutionProvider']
    if device=='cuda':
        providers=[('CUDAExecutionProvider',{'device_id':0,'gpu_mem_limit':6*1024**3,
                    'arena_extend_strategy':'kSameAsRequested','cudnn_conv_algo_search':'HEURISTIC',
                    'cudnn_conv_use_max_workspace':'0'})]
    if not model_path.is_file():raise ValueError('أوزان إزالة الخلفية غير جاهزة.')
    if device=='cuda':
        # Avoid rembg's unrelated matting/Numba/CuPy imports for this direct model.
        session=SimpleNamespace(inner_session=ort.InferenceSession(str(model_path),sess_options=options,providers=providers))
        if 'CUDAExecutionProvider' not in session.inner_session.get_providers():
            raise ValueError('تعذر تفعيل CUDA لإزالة الخلفية؛ لم يُستخدم المعالج بديلًا.')
        session.inner_session.disable_fallback()
        return session
    from rembg.sessions.birefnet_general import BiRefNetSessionGeneral
    class OfflineBiRefNet(BiRefNetSessionGeneral):
        @classmethod
        def download_models(cls,*args,**kwargs):
            return str(model_path)
    return OfflineBiRefNet('birefnet-general',options,providers=providers)

def cuda_mask(image,session):
    """Same 1024 normalization and sigmoid/min-max mask as rembg BiRefNet General."""
    import numpy as np
    values=np.asarray(image.resize((1024,1024),Image.Resampling.LANCZOS))
    values=values/max(1,np.max(values))
    normalized=np.zeros(values.shape)
    for i,(mean,std) in enumerate(zip((.485,.456,.406),(.229,.224,.225))):normalized[:,:,i]=(values[:,:,i]-mean)/std
    tensor=np.expand_dims(normalized.transpose(2,0,1),0).astype(np.float32)
    logits=session.inner_session.run(None,{session.inner_session.get_inputs()[0].name:tensor})[0][:,0,:,:]
    prediction=1/(1+np.exp(-np.clip(logits,-80,80)))
    span=float(prediction.max()-prediction.min())
    if not np.isfinite(prediction).all() or span<=0:raise ValueError('لم ينتج نموذج CUDA قناعًا صالحًا للصورة.')
    prediction=np.squeeze((prediction-prediction.min())/span)
    return Image.fromarray((prediction*255).astype('uint8')).resize(image.size,Image.Resampling.LANCZOS)

def run(data,*,transparent=False,device='cpu',profile_path=None):
    started=time.perf_counter()
    model_path=ROOT/'models/background/models/birefnet-general/birefnet-general.onnx'
    if device=='cuda':model_path=model_path.with_name('birefnet-general-fp16.onnx')
    if not model_path.is_file():raise ValueError('أوزان إزالة الخلفية غير جاهزة.')
    value=data.get('image','')
    if not isinstance(value,str) or not value.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):raise ValueError('صيغة غير مناسبة.')
    raw=base64.b64decode(value.split(',',1)[1],validate=True)
    if len(raw)>6_000_000:raise ValueError('الصورة أكبر من الحد.')
    image=Image.open(io.BytesIO(raw))
    if image.width*image.height>4_000_000:raise ValueError('الصورة أكبر من الحد.')
    image=ImageOps.exif_transpose(image).convert('RGBA')
    if image.getchannel('A').getextrema()[1]==0:raise ValueError('الصورة شفافة بالكامل؛ لا يوجد موضوع لإزالة خلفيته.')
    if device=='cpu':sys.modules['cupy']=None
    session=local_session(model_path,device=device,profile_path=profile_path)
    loaded=time.perf_counter()
    # Hidden RGB in transparent pixels must not influence semantic segmentation.
    model_input=Image.new('RGBA',image.size,'white');model_input.alpha_composite(image)
    if device=='cuda':
        predicted=model_input.copy();predicted.putalpha(cuda_mask(model_input.convert('RGB'),session))
    else:
        # CPU compatibility only: matting's optional CuPy is unrelated to ONNX.
        sys.modules['cupy']=None
        from rembg import remove
        predicted=remove(model_input.convert('RGB'),session=session).convert('RGBA')
    inferred=time.perf_counter()
    if predicted.size!=image.size:raise ValueError('أبعاد قناع الخلفية غير صحيحة.')
    # Keep source RGB; only combine masks. Never revive previously erased pixels.
    cutout=image.copy();cutout.putalpha(ImageChops.multiply(predicted.getchannel('A'),image.getchannel('A')))
    if transparent:result=cutout
    else:
        background=Image.new('RGBA',cutout.size,'white');background.alpha_composite(cutout)
        result=background.convert('RGB')
    output=io.BytesIO();result.save(output,format='PNG')
    result={'image':'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode(),'width':image.width,'height':image.height,'model':'BiRefNet-General','device':'CUDA' if device=='cuda' else 'CPU','precision':'mixed-fp16' if device=='cuda' else 'fp32',
            'seconds':round(time.perf_counter()-started,3),'loadSeconds':round(loaded-started,3),'inferenceSeconds':round(inferred-loaded,3)}
    if profile_path:result['profile']=session.inner_session.end_profiling()
    return result

if __name__=='__main__':
    try:print(json.dumps(run(json.load(sys.stdin))))
    except ValueError as e:print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(2)
    except Exception:print(json.dumps({'error':'تعذرت إزالة الخلفية المحلية.'},ensure_ascii=False));sys.exit(1)
