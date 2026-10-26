"""Local photographic line-art comparison; no image is uploaded."""
from pathlib import Path
import importlib.util
import importlib.metadata
import sys, types, time, json, hashlib
import numpy as np
import cv2
import torch
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'photo-lineart-comparison'
OUT.mkdir(exist_ok=True)
source = Path(r'C:\Users\mesue\Downloads\tumblr_ompd8y9dGn1s1u22do1_1280.png')
im = ImageOps.exif_transpose(Image.open(source)).convert('RGB')
im.thumbnail((1024, 1024))
rgb = np.array(im)
h, w = rgb.shape[:2]
im.save(OUT / 'original.png')
results = {}
images = {'original': rgb}
t = time.perf_counter()
gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
smooth = cv2.bilateralFilter(gray, 9, 45, 45)
edges = cv2.Canny(smooth, 45, 110, L2gradient=True)
images['opencv'] = cv2.cvtColor(255-edges, cv2.COLOR_GRAY2RGB)
results['opencv'] = {'seconds': time.perf_counter()-t, 'method':'bilateral 9/45/45 + Canny 45/110 L2'}

# Load only the installed lineart module, avoiding unrelated detector dependencies.
package_root = Path(importlib.util.find_spec('controlnet_aux').origin).parent
namespace = types.ModuleType('local_lineart_runtime')
namespace.__path__ = [str(package_root)]
sys.modules[namespace.__name__] = namespace
spec = importlib.util.spec_from_file_location('local_lineart_runtime.lineart', package_root/'lineart'/'__init__.py', submodule_search_locations=[str(package_root/'lineart')])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
device = 'cuda' if torch.cuda.is_available() else 'cpu'
detector = module.LineartDetector.from_pretrained('lllyasviel/Annotators', cache_dir=str(ROOT/'models'/'lineart')).to(device)
tensor_image = cv2.resize(rgb, (int(np.ceil(w/64)*64), int(np.ceil(h/64)*64)))
x = torch.from_numpy(tensor_image).permute(2,0,1).unsqueeze(0).float().to(device)/255
for name, model in [('realistic', detector.model), ('coarse', detector.model_coarse)]:
    if device == 'cuda': torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
    t = time.perf_counter()
    with torch.inference_mode():
        ink = model(x)[0,0].cpu().numpy()
    if device == 'cuda': torch.cuda.synchronize()
    # Generator output is black ink on white; the library's public detector
    # inverts it for ControlNet conditioning. Pen artwork needs original polarity.
    result = (ink*255).clip(0,255).astype(np.uint8)
    images[name] = cv2.cvtColor(cv2.resize(result,(w,h)),cv2.COLOR_GRAY2RGB)
    results[name] = {'seconds':time.perf_counter()-t, 'device':device, 'peak_allocated_mib':torch.cuda.max_memory_allocated()/1048576 if device=='cuda' else None}
    print(name, results[name], flush=True)

regions = {'eye':(.37,.29,.94,.45), 'nose':(0,.39,.59,.60), 'mouth':(.03,.58,.60,.77)}
for name, arr in images.items():
    Image.fromarray(arr).save(OUT/f'{name}.png')
    for region, (x1,y1,x2,y2) in regions.items():
        Image.fromarray(arr).crop((int(x1*w),int(y1*h),int(x2*w),int(y2*h))).save(OUT/f'{name}-{region}.png')
metadata = {'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'dimensions':[w,h], 'results':results,'regions_normalized':regions,'torch':torch.__version__, 'opencv':cv2.__version__,'controlnet_aux':importlib.metadata.version('controlnet-aux'),'model':'lllyasviel/Annotators','weights':['sk_model.pth','sk_model2.pth'], 'gpu':torch.cuda.get_device_name() if device=='cuda' else None}
(OUT/'results.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
labels = {'original':'الصورة الأصلية','opencv':'OpenCV · حواف تقليدية','realistic':'Lineart · دقيق','coarse':'Lineart · مبسط'}
def grid(suffix=''):
    return '<div class="grid">'+''.join(f'<figure><figcaption>{label}</figcaption><img src="{name}{suffix}.png" loading="lazy"></figure>' for name,label in labels.items())+'</div>'
html = '''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مقارنة خطوط الوجه محليًا</title><style>body{margin:0;background:#f1f4ef;color:#183c3b;font:17px/1.8 system-ui}main{max-width:1450px;margin:auto;padding:35px}section{background:white;padding:25px;border-radius:18px;margin:24px 0}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}figure{margin:0;background:#f8f9f5;border:1px solid #dae2d9;border-radius:10px;overflow:hidden}figcaption{padding:12px;font-weight:650}img{display:block;width:100%;height:auto}small{color:#5d716b}a{color:#17685f}h1{font-size:32px}h2{font-size:23px}.note{border-right:4px solid #c59147;padding:14px;background:#fff9ef}@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}main{padding:15px}}@media print{body{background:white}main{padding:0}section{break-inside:avoid;border:1px solid #ddd}.grid{grid-template-columns:repeat(4,1fr)}}</style><main><small>تجربة محلية • مرحلة الصورة قبل مسارات القلم</small><h1>هل نستخرج الملامح أم نكرر تفاصيل الصورة؟</h1><p>مقارنة الصورة نفسها، بالمقياس نفسه، بين حواف OpenCV ونموذج استخراج خطوط مدرّب بنسختيه. لم تُرسل الصورة إلى خدمة خارجية. النتائج أدناه فعلية، وليست رسومات توضيحية.</p><p class="note">هذا النموذج يستخرج رسمًا خطيًا؛ لا يعمل داخل LM Studio ولا يتحكم بالذراع. جودة الخطوط لا تعني أن مسارات القلم صارت سليمة. لا توجد هنا درجة مقاسة لحفظ الهوية.</p><section><h2>الوجه كاملًا</h2>'''+grid()+'''</section>'''
for key,label in [('eye','العين والحاجب'),('nose','الأنف وحدود الوجه'),('mouth','الفم والشفاه')]:
    html += f'<section><h2>{label}</h2>'+grid('-'+key)+'</section>'
html += '<section><h2>تفاصيل التشغيل القابلة للمراجعة</h2><p>الحواف التقليدية: تنعيم ثنائي ثم Canny، وليست مقارنة شاملة لكل خوارزميات OpenCV. النموذج: LineartDetector من controlnet-aux، بالأوزان الدقيقة والمبسطة. لم نطبق عتبة ثنائية أو تنظيفًا إضافيًا على خرج النموذج، حتى نرى أثره مباشرة.</p><ul>'
for name, result in results.items():
    html += f'<li>{labels[name]}: {result["seconds"]:.3f} ثانية'+(f'؛ {result["device"]}؛ ذروة ذاكرة العملية {result["peak_allocated_mib"]:.0f} MiB' if result.get('peak_allocated_mib') else '')+'</li>'
html += f'</ul><p>الدقة الموحدة {w} × {h}. الزمن يشمل الاستدلال/المعالجة فقط، ولا يشمل تنزيل الأوزان وتحميلها. استهلاك الذاكرة هو تخصيص PyTorch لهذه العملية، وليس استهلاك الجهاز كاملًا.</p><p><a href="results.json">الإعدادات والنتائج وبصمة المصدر</a> · <a href="https://github.com/huggingface/controlnet_aux">المكتبة الأصلية</a> · <a href="https://huggingface.co/lllyasviel/Annotators">مصدر الأوزان</a></p><p>صلاحية الأوزان للاستخدام التجاري تحتاج مراجعة شروطها؛ لا نفترض ترخيصًا موحدًا للمكتبة وجميع الأوزان.</p></section></main></html>'
assessment = '<section><h2>التقييم البصري لهذه الصورة</h2><p>OpenCV ينتج حواف حادة ومتقطعة حول العين والشفاه. النسخة الدقيقة من النموذج تحفظ تفاصيل العين بصورة أوضح بصريًا، لكنها تحتفظ بملمس الشفاه وكثير من الشعر. النسخة المبسطة ترسم حدودًا أقوى، مع خطوط متراكبة قد تشوه قراءة العين والفم. تسمية «مبسط» لا تضمن قلة ضربات القلم.</p><p><strong>القرار: النسخة الدقيقة مرشح للمرحلة التالية، وليست حلًا نهائيًا.</strong> يلزم تقليل تفاصيل الشعر والشفاه مع حماية حدود الملامح، ثم اختبار التحويل إلى خطوط مركزية. المقارنة بصرية على صورة واحدة؛ لم نثبت تفوقًا عامًا أو دقة هوية، ولم نربط هذا النموذج بمسارات القلم بعد.</p></section>'
html = html.replace('</main></html>', assessment+'</main></html>')
(OUT/'report-ar.html').write_text(html,encoding='utf-8')
print('REPORT',OUT/'report-ar.html',flush=True)
