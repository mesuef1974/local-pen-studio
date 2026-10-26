"""Use the installed local BiRefNet weights; keep real alpha, never compose on white."""
import base64,io,json,os,sys
from pathlib import Path
from PIL import Image

models=Path(__file__).resolve().parent.parent/'drawing-simulator/models/background'
os.environ['REMBG_HOME']=str(models)
os.environ['OMP_NUM_THREADS']='6'
sys.modules['cupy']=None

def main():
    if not (models/'models/birefnet-general/birefnet-general.onnx').is_file():raise ValueError('أوزان BiRefNet المحلية غير موجودة.')
    data=json.load(sys.stdin);raw=base64.b64decode(data['image'].split(',',1)[1],validate=True)
    if len(raw)>6_000_000:raise ValueError('الصورة كبيرة جدًا.')
    image=Image.open(io.BytesIO(raw))
    if image.width*image.height>4_000_000:raise ValueError('الصورة تتجاوز الحد.')
    from rembg import remove,new_session
    session=new_session('birefnet-general',providers=['CPUExecutionProvider'])
    result=remove(image.convert('RGB'),session=session).convert('RGBA')
    # Respect any alpha already present in the uploaded source.
    from PIL import ImageChops
    result.putalpha(ImageChops.multiply(result.getchannel('A'),image.convert('RGBA').getchannel('A')))
    b=io.BytesIO();result.save(b,format='PNG')
    print(json.dumps({'image':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()}))

if __name__=='__main__':
    try:main()
    except ValueError as error:print(json.dumps({'error':str(error)},ensure_ascii=False));sys.exit(2)
    except Exception:print(json.dumps({'error':'تعذرت إزالة الخلفية المحلية.'},ensure_ascii=False));sys.exit(1)
