"""Local cold-start CPU/CUDA comparison; never downloads models or uploads images."""
import base64,json,subprocess,time,sys
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parent
DRAW=ROOT.parent/'drawing-simulator'
OUT=ROOT/'background-gpu-review'

def main():
    OUT.mkdir(exist_ok=True)
    source=DRAW/'photo-lineart-comparison/original.png'
    payload=json.dumps({'image':'data:image/png;base64,'+base64.b64encode(source.read_bytes()).decode()})
    runs={}
    for device,environment in [('cpu','.venv-background'),('cuda','.venv-background-gpu')]:
        if device=='cpu' and '--reuse-cpu' in sys.argv:
            runs[device]=json.loads((OUT/'cpu-run.json').read_text())
            continue
        code="""import sys,json,base64,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from background_service import run
result=run(json.load(sys.stdin),transparent=True,device=sys.argv[2],profile_path=Path(sys.argv[3])/'ort' if sys.argv[2]=='cuda' else None)
Path(sys.argv[3],sys.argv[2]+'.png').write_bytes(base64.b64decode(result.pop('image').split(',',1)[1]))
print(json.dumps(result))
"""
        started=time.perf_counter()
        log=(OUT/(device+'-runtime.log')).open('w',encoding='utf-8')
        process=subprocess.Popen([str(DRAW/environment/'Scripts/python.exe'),'-c',code,str(DRAW),device,str(OUT)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process.stdin.write(payload);process.stdin.close();samples=[]
        while process.poll() is None:
            if time.perf_counter()-started>180:
                process.kill();process.wait();raise RuntimeError('Background benchmark timed out')
            if device=='cuda':
                result=subprocess.run(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:samples.append([int(v.strip()) for v in result.stdout.strip().split(',')])
                except ValueError:pass
            time.sleep(.3)
        stdout=process.stdout.read();log.close();stderr=(OUT/(device+'-runtime.log')).read_text(encoding='utf-8',errors='replace')
        if process.returncode:raise RuntimeError(f'{device} failed: '+stderr[-1600:]+' '+stdout[-400:])
        runs[device]=json.loads(stdout);runs[device]['wallSeconds']=round(time.perf_counter()-started,3)
        if samples:
            runs[device]['peakTotalGpuMiB']=max(v[0] for v in samples)
            runs[device]['peakGpuUtilizationPercent']=max(v[1] for v in samples)
        if device=='cuda':
            events=json.loads(Path(runs[device].pop('profile')).read_text())
            providers=Counter(e.get('args',{}).get('provider') for e in events if e.get('args',{}).get('provider'))
            runs[device]['profileNodeEvents']=dict(providers)
            if not providers['CUDAExecutionProvider']:raise RuntimeError('No actual CUDA node execution in profile')
        print(json.dumps({device:runs[device]}),flush=True)
        (OUT/(device+'-run.json')).write_text(json.dumps(runs[device],indent=2),encoding='utf-8')
    cpu=np.asarray(Image.open(OUT/'cpu.png').convert('RGBA'))
    gpu=np.asarray(Image.open(OUT/'cuda.png').convert('RGBA'))
    original=np.asarray(Image.open(source).convert('RGBA'))
    ca,ga=cpu[:,:,3].astype(float),gpu[:,:,3].astype(float)
    union=((ca>127)|(ga>127)).sum()
    metrics={'alphaMeanAbsoluteDifference':round(float(np.abs(ca-ga).mean()),4),
             'maskIoU':round(float(((ca>127)&(ga>127)).sum()/max(1,union)),6),
             'originalRgbPreserved':bool(np.array_equal(gpu[:,:,:3],original[:,:,:3])),
             'transparentPixels':int((ga==0).sum()),'softAlphaPixels':int(((ga>0)&(ga<255)).sum()),
             'speedupColdStart':round(runs['cpu']['wallSeconds']/runs['cuda']['wallSeconds'],2)}
    result={'runs':runs,'comparison':metrics,'scope':'One bundled portrait; total GPU memory sampled, not process-only; cold process per request.'}
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    rows=''.join(f'<tr><td>{label}</td><td>{runs[device][key]}</td></tr>' for label,device,key in [
        ('زمن الطلب الكامل CPU · ثانية','cpu','wallSeconds'),('زمن الطلب الكامل GPU · ثانية','cuda','wallSeconds'),
        ('استدلال GPU · ثانية','cuda','inferenceSeconds'),('ذروة ذاكرة الكرت الكلية المرصودة · MiB','cuda','peakTotalGpuMiB')])
    (OUT/'report-ar.html').write_text(f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>تحقق إزالة الخلفية على NVIDIA</title><style>body{{font:17px/1.8 "Segoe UI",sans-serif;background:#f3f6f8;color:#193640;margin:0}}main{{max-width:1050px;margin:auto;padding:32px}}section{{background:white;padding:24px;border:1px solid #dce5e8;border-radius:12px;margin:20px 0}}table{{border-collapse:collapse;width:100%}}td{{padding:12px;border-bottom:1px solid #ddd}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}img{{max-width:100%;max-height:560px;display:block;margin:auto;background:repeating-conic-gradient(#ddd 0% 25%,#fff 0% 50%) 50%/20px 20px}}@media(max-width:650px){{.images{{grid-template-columns:1fr}}main{{padding:14px}}}}@media print{{body{{background:white}}section{{break-inside:avoid}}}}</style><main><h1>إزالة الخلفية على كرت NVIDIA</h1><p>اختبار محلي · BiRefNet-General · RTX 4060 Laptop 8GB · 27 أكتوبر 2026</p><section><h2>القياس الفعلي</h2><table>{rows}</table><p>تسارع الطلب الكامل: {metrics['speedupColdStart']}×. تطابق القناع الثنائي بين CPU وGPU: {metrics['maskIoU']*100:.3f}٪. متوسط فرق الشفافية: {metrics['alphaMeanAbsoluteDifference']} من255.</p><p>حفظ ألوان الأصل: {metrics['originalRgbPreserved']}. أثبت سجل ONNX تنفيذ {runs['cuda']['profileNodeEvents'].get('CUDAExecutionProvider',0)} حدث عقدة عبر CUDA. قد تبقى عمليات شكلية صغيرة على CPU.</p></section><section class="images"><div><h2>CPU</h2><img src="cpu.png" alt="فصل الخلفية بالمعالج"></div><div><h2>GPU</h2><img src="cuda.png" alt="فصل الخلفية بكرت NVIDIA"></div></section><section><h2>حدود التحقق</h2><p>عينة بورتريه واحدة؛ لا تعمم السرعة أو جودة الشعر على كل الصور. القياس يشمل بدء عملية وتحميل النموذج لكل طلب. الذاكرة المرصودة هي إجمالي ذاكرة الكرت وليست تخصيص النموذج وحده. النموذج يعمل بدقة1024 ويحافظ على أبعاد الصورة الأصلية وRGB، ويعدّل قناع الشفافية فقط. لا تنزيل أوزان ولا إرسال صور إلى خدمة خارجية. تنتهي عملية الفصل لتحرير الذاكرة قبل استخدام FLUX.</p></section></main></html>''',encoding='utf-8')
    if metrics['maskIoU']<.99 or not metrics['originalRgbPreserved']:raise RuntimeError('Quality regression requires review')
    print(json.dumps(metrics),flush=True)

if __name__=='__main__':main()
