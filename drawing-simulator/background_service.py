"""Isolated rembg runtime. A downloaded model is required; requests never download."""
import base64, io, json, os, sys
from pathlib import Path
from PIL import Image, ImageOps
ROOT=Path(__file__).resolve().parent
os.environ['REMBG_HOME']=str(ROOT/'models/background')
os.environ['OMP_NUM_THREADS']='6'

def run(data):
    model_path=ROOT/'models/background/models/birefnet-general/birefnet-general.onnx'
    if not model_path.is_file():raise ValueError('أوزان إزالة الخلفية غير جاهزة.')
    value=data.get('image','')
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,'):raise ValueError('صيغة غير مناسبة.')
    raw=base64.b64decode(value.split(',',1)[1],validate=True)
    if len(raw)>5_000_000:raise ValueError('الصورة أكبر من الحد.')
    image=Image.open(io.BytesIO(raw))
    if image.width*image.height>4_000_000:raise ValueError('الصورة أكبر من الحد.')
    image=ImageOps.exif_transpose(image)
    # CPU backend: do not import the host's optional CuPy CUDA runtime.
    sys.modules['cupy']=None
    from rembg import remove,new_session
    session=new_session('birefnet-general',providers=['CPUExecutionProvider'])
    cutout=remove(image.convert('RGB'),session=session)
    background=Image.new('RGBA',cutout.size,'white');background.alpha_composite(cutout.convert('RGBA'))
    output=io.BytesIO();background.convert('RGB').save(output,format='PNG')
    return {'image':'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode(),'width':image.width,'height':image.height,'model':'BiRefNet-General','device':'CPU'}

if __name__=='__main__':
    try:print(json.dumps(run(json.load(sys.stdin))))
    except ValueError as e:print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(2)
    except Exception:print(json.dumps({'error':'تعذرت إزالة الخلفية المحلية.'},ensure_ascii=False));sys.exit(1)
