import concurrent.futures, datetime, html, json, re, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Stars are a dated snapshot of individual model entries on the LM Studio family pages.
DATA = [
('Qwen3.5 2B','Qwen/Qwen3.5-2B','qwen/qwen3.5-2b',58,'نص وصور','مساعد خفيف، تصنيف وتلخيص، فهم صور بسيطة','مريح مبدئيًا','4096–8192','qwen3.5'),
('Qwen3.5 4B','Qwen/Qwen3.5-4B','qwen/qwen3.5-4b',70,'نص وصور','محادثة عربية، شرح لقطات الشاشة والمخططات','مريح مبدئيًا','4096–8192','qwen3.5'),
('Qwen3.5 9B','Qwen/Qwen3.5-9B','qwen/qwen3.5-9b',246,'نص وصور','تجربة نموذج أكبر للمحادثة وتحليل الصور','مشروط؛ قد يحتاج توزيعًا على RAM','4096','qwen3.5'),
('Qwen3-VL 2B Instruct','Qwen/Qwen3-VL-2B-Instruct','qwen/qwen3-vl-2b',22,'فهم بصري','قراءة عناصر واجهة ووصف صور ضمن مهام بسيطة','مريح مبدئيًا','4096–8192','qwen3-vl'),
('Qwen3-VL 4B Instruct','Qwen/Qwen3-VL-4B-Instruct','qwen/qwen3-vl-4b',37,'فهم بصري','تحليل مستندات مصورة ولقطات شاشة؛ إخراجه نص','مريح مبدئيًا','4096–8192','qwen3-vl'),
('Qwen3-VL 8B Instruct','Qwen/Qwen3-VL-8B-Instruct','qwen/qwen3-vl-8b',58,'فهم بصري','تحليل صور أكثر تعقيدًا مع سياق قصير','مشروط؛ الصور تزيد الذاكرة','4096','qwen3-vl'),
('Qwen3 4B','Qwen/Qwen3-4B','qwen/qwen3-4b',12,'نص واستدلال','تلخيص وترجمة ومحادثة مع وضع تفكير اختياري','مريح مبدئيًا','8192','qwen3-2504'),
('Qwen3 8B','Qwen/Qwen3-8B','qwen/qwen3-8b',22,'نص واستدلال','مساعدك الحالي: كتابة عربية، شرح كود وتحليل نص','مجرّب التحميل على جهازك','8192؛ و16384 تقديريًا','qwen3-2504'),
('Ministral 3 3B Instruct','mistralai/Ministral-3-3B-Instruct-2512','mistralai/ministral-3-3b',41,'مساعد بصري وأدوات','محادثة وصور وJSON؛ الأدوات تحتاج تطبيقًا ينفذها','مريح مبدئيًا','4096–8192','ministral'),
('Ministral 3 3B Reasoning','mistralai/Ministral-3-3B-Reasoning-2512','mistralai/ministral-3-3b-reasoning',32,'استدلال صغير','مسائل منطق ورياضيات، مع كلفة وقت إضافية للتفكير','مريح مبدئيًا','8192','ministral'),
('Ministral 3 8B Instruct','mistralai/Ministral-3-8B-Instruct-2512','mistralai/ministral-3-8b',12,'مساعد بصري وأدوات','محادثة متعددة اللغات وصور وإخراج منظم','مشروط؛ ابدأ بسياق قصير','4096','ministral'),
('Granite 4.1 3B','ibm-granite/granite-4.1-3b','ibm/granite-4.1-3b',16,'نص وأدوات','استخراج حقول، JSON، تلخيص ومهام RAG','مريح مبدئيًا','8192','granite-4.1'),
('Granite 4.1 8B','ibm-granite/granite-4.1-8b','ibm/granite-4.1-8b',28,'نص وأدوات','اتباع تعليمات ومساعدة برمجية وتلخيص مستندات','مناسب تقديريًا بسياق محدود','4096–8192','granite-4.1'),
('Phi-4 mini reasoning','microsoft/Phi-4-mini-reasoning','microsoft/phi-4-mini-reasoning',33,'استدلال رياضي','حل مسائل متعددة الخطوات؛ لا نفترض تفوقه في العربية','مريح مبدئيًا','8192','phi-4-reasoning'),
('Gemma 3 1B IT','google/gemma-3-1b-it','google/gemma-3-1b',27,'نص خفيف','صياغة وتصنيف وتجارب سريعة؛ هذه النسخة لا تفهم الصور','مريح مبدئيًا','4096–8192','gemma-3'),
('Gemma 3 4B IT','google/gemma-3-4b-it','google/gemma-3-4b',65,'نص وصور','تلخيص وفهم صور ومقارنة الإجابات مع Qwen','مريح مبدئيًا','4096–8192','gemma-3'),
('DeepSeek R1 0528 Qwen3 8B','deepseek-ai/DeepSeek-R1-0528-Qwen3-8B','deepseek/deepseek-r1-0528-qwen3-8b',181,'استدلال','مسائل رياضيات ومنطق وبرمجة؛ الردود قد تطول','مناسب تقديريًا بسياق محدود','8192','deepseek-r1'),
('Mistral 7B Instruct v0.3','mistralai/Mistral-7B-Instruct-v0.3','mistralai/mistral-7b-instruct-v0.3',55,'نص عام','بديل أقدم للمحادثة الإنجليزية وتوليد النص والكود','مناسب تقديريًا بسياق محدود','8192','mistral'),
('Qwen2.5 Coder 7B Instruct','Qwen/Qwen2.5-Coder-7B-Instruct','qwen/qwen2.5-coder-7b',None,'برمجة متخصصة','توليد دوال وشرح أخطاء ومراجعة مقاطع كود؛ لا يرى مستودعك تلقائيًا','مناسب تقديريًا بسياق محدود','8192','qwen/qwen2.5-coder-7b'),
('Granite Vision 3.2 2B','ibm-granite/granite-vision-3.2-2b','ibm/granite-vision-3.2-2b',None,'رؤية مستندات','قراءة الجداول والرسوم والمخططات وOCR؛ موجه أساسًا للإنجليزية، والعربية تحتاج اختبارًا','مريح مبدئيًا','4096','ibm/granite-vision-3.2-2b'),
('Qwen2.5-VL 3B Instruct','Qwen/Qwen2.5-VL-3B-Instruct','qwen/qwen2.5-vl-3b',7,'فهم بصري وتحديد مواقع','فهم صور وفواتير وواجهات، وإرجاع إحداثيات أو JSON عند الطلب؛ دقتها تحتاج تحققًا','مريح مبدئيًا؛ للاستخدام البحثي غير التجاري','4096','qwen2.5-vl'),
('Qwen2.5-VL 7B Instruct','Qwen/Qwen2.5-VL-7B-Instruct','qwen/qwen2.5-vl-7b',27,'فهم بصري وتحديد مواقع','تحليل جداول ورسوم وصور مستندات وتحديد عناصر في صورة؛ ليس كشفًا لحظيًا مضمونًا','مشروط؛ صورة واحدة وسياق قصير','4096','qwen2.5-vl'),
('olmOCR 2 7B 1025','allenai/olmOCR-2-7B-1025','allenai/olmocr-2-7b',23,'OCR للمستندات','استخراج صفحات إلى نص منظم؛ يتطلب صورة صفحة وتعليمات خاصة، وتدريبه على الإنجليزية','مشروط؛ قد يحتاج توزيعًا على RAM','4096','olmocr2'),
]

def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'LocalModelGuide/1.0'})
    with urllib.request.urlopen(req,timeout=35) as r:return json.load(r)

def collect(row):
    name,origin,lmid,stars,kind,use,fit,ctx,family=row
    out=dict(name=name,origin=origin,lmid=lmid,stars=stars,kind=kind,use=use,fit=fit,context=ctx,family=family)
    try:
        meta=get('https://huggingface.co/api/models/'+origin)
        card=meta.get('cardData',{})
        out.update(likes=meta.get('likes'),license=card.get('license') or card.get('license_name','غير موثق'),license_url=card.get('license_link'),downloads=meta.get('downloads'))
    except Exception as e:out.update(likes=None,license='تعذر التحقق',metadata_error=str(e))
    query=origin.split('/')[-1]+'-GGUF'
    try:
        results=get('https://huggingface.co/api/models?search='+urllib.parse.quote(query)+'&limit=15&sort=downloads&direction=-1')
        results=[x for x in results if x['id'].split('/')[-1].lower()==query.lower()]
        direct='lmstudio-community/'+query
        if not any(x['id'].lower()==direct.lower() for x in results):results.insert(0,{'id':direct})
        results.sort(key=lambda x:(not x['id'].startswith('lmstudio-community/'),not x['id'].startswith(origin.split('/')[0]+'/')))
        for item in results[:5]:
            rid=item['id']
            if any(w in rid.lower() for w in ('abliterated','uncensored','heretic','distill')) and 'Distill' not in origin:continue
            meta=get('https://huggingface.co/api/models/'+rid+'?blobs=true')
            files=[f for f in meta.get('siblings',[]) if re.search(r'(?i)Q4_K_M.*\.gguf$',f['rfilename']) and 'mmproj' not in f['rfilename'].lower()]
            if files:
                sizes=[f.get('size',f.get('lfs',{}).get('size',0)) for f in files]
                if not all(sizes):continue
                out.update(gguf_repo=rid,gguf_files=[f['rfilename'] for f in files],file_gb=round(sum(sizes)/1e9,2),quant='Q4_K_M')
                proj=[f for f in meta.get('siblings',[]) if 'mmproj' in f['rfilename'].lower() and f['rfilename'].lower().endswith('.gguf')]
                out['projector_files']=[{'name':f['rfilename'],'gb':round(f.get('size',f.get('lfs',{}).get('size',0))/1e9,2)} for f in proj]
                break
        if 'gguf_repo' not in out:out['gguf_note']='لم أوثق ملف Q4_K_M محددًا؛ اختر GGUF من رابط LM Studio وافحص حجمه.'
    except Exception as e:out['gguf_error']=str(e)
    return out

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:models=list(pool.map(collect,DATA))
stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
(ROOT/'models-evidence.json').write_text(json.dumps(dict(retrieved_at_utc=stamp,stars_source='LM Studio individual entries on linked family pages; captured in browser',models=models),ensure_ascii=False,indent=2),encoding='utf-8')
for m in models:print(json.dumps({k:m.get(k) for k in ('name','license','likes','gguf_repo','file_gb','metadata_error','gguf_error')},ensure_ascii=False))

def esc(s):return html.escape(str(s))
body=[]
for i,m in enumerate(models,1):
    assert m.get('gguf_repo') and m.get('file_gb'),m
    lp='https://lmstudio.ai/models/'+m['lmid']
    hp='https://huggingface.co/'+m['origin']
    gp='https://huggingface.co/'+m['gguf_repo']+'/tree/main'
    p=m.get('projector_files',[])
    extra=''
    if p:
        vals=[x['gb'] for x in p if x['gb']]
        if vals:extra='<small>ملف رؤية إضافي: '+str(min(vals))+('–'+str(max(vals)) if min(vals)!=max(vals) else '')+' GB حسب النسخة</small>'
    lic=m['license']
    rights='نعم؛ أوزان بترخيص مرن، والتعديل والاستخدام التجاري مع الالتزام بالترخيص.'
    if lic=='gemma':rights='أوزان متاحة؛ التعديل والاستخدام وفق شروط Gemma، وليس ترخيص Apache/MIT.'
    if lic=='qwen-research':rights='أوزان متاحة؛ التعديل للبحث والتقييم غير التجاري فقط. الاستخدام التجاري يتطلب ترخيصًا من Alibaba؛ راجع ملف LICENSE في المستودع الأصلي.'
    cls='tested' if 'مجرّب' in m['fit'] else ('conditional' if 'مشروط' in m['fit'] else 'suitable')
    stars_text='★ '+str(m['stars']) if m['stars'] is not None else 'غير موثق؛ لا يعني صفرًا'
    body.append(f'''<tr data-stars="{m['stars'] if m['stars'] is not None else -1}" data-likes="{m['likes'] or 0}" data-size="{m['file_gb']}" data-kind="{esc(m['kind'])}"><td>{i}</td><td><a class="model" href="{lp}" target="_blank" rel="noopener">{esc(m['name'])}</a><small><a href="{hp}" target="_blank" rel="noopener">بطاقة النموذج على Hugging Face ↗</a></small></td><td>{esc(m['kind'])}<small>{esc(m['use'])}</small></td><td><a href="{gp}" target="_blank" rel="noopener">Q4_K_M · <bdi>{m['file_gb']:.2f} GB</bdi></a>{extra}</td><td><span class="badge {cls}">{esc(m['fit'])}</span><small>سياق بداية: <bdi>{esc(m['context'])}</bdi> رمز</small></td><td><a href="https://lmstudio.ai/models/{m['family']}" target="_blank" rel="noopener">{stars_text}</a></td><td><a href="{hp}" target="_blank" rel="noopener">♥ {m['likes']:,}</a><small>للمستودع الأصلي، لا لنسخة GGUF</small></td><td><bdi>{esc(lic)}</bdi><small>{rights}</small></td></tr>''')

page='''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>18 نموذجًا محليًا لـ LM Studio — دليل جهازك</title><style>
:root{font-family:"Segoe UI",Tahoma,Arial,sans-serif;color:#183248;background:#eff4f7;line-height:1.7}*{box-sizing:border-box}body{margin:0}main{max-width:1660px;margin:28px auto;padding:34px;background:white;border-radius:20px}header{background:linear-gradient(120deg,#16354e,#075c64);color:white;padding:30px;border-radius:15px}h1{margin:5px 0 12px;font-size:30px}.eyebrow{font-size:13px;color:#b4e9dc}header p{max-width:950px;margin:0}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.card{background:#f0f6f8;border:1px solid #dce8ec;padding:13px;border-radius:10px}.card strong{display:block;font-size:20px}.card span{font-size:13px;color:#587080}.note{padding:14px 18px;background:#fff8e9;border-right:4px solid #dcad4e;border-radius:6px;margin:16px 0}.method{background:#edf8f5;border-color:#168d79}.controls{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0}input,select,button{font:inherit;border:1px solid #b8cbd4;border-radius:8px;padding:9px 13px;background:white;color:#17354b}input{flex:1;min-width:220px}button{cursor:pointer;background:#123e54;color:white}.count{align-self:center;color:#536c7b;font-size:13px}.scroll{overflow:auto;border:1px solid #d9e4ea;border-radius:10px}table{border-collapse:collapse;width:100%;min-width:1200px;font-size:13px}th{background:#183e55;color:white;text-align:right;padding:14px 10px;white-space:nowrap}td{padding:14px 10px;border-bottom:1px solid #e0e9ee;vertical-align:top}tr:nth-child(even){background:#f6f9fb}tr:hover{background:#ecf6f8}a{color:#07648b;text-decoration:none}a:hover{text-decoration:underline}.model{font-weight:700;display:block;direction:ltr;text-align:right;min-width:170px}small{display:block;color:#536d7b;font-size:11px;line-height:1.65;margin-top:5px;max-width:240px}.badge{display:inline-block;padding:3px 7px;border-radius:5px;font-size:11px}.tested{background:#d8f1e5;color:#14643c}.suitable{background:#e4f1fa;color:#165e87}.conditional{background:#fff0cd;color:#88571a}h2{font-size:21px;margin-top:30px}.bottom{display:grid;grid-template-columns:1fr 1fr;gap:18px}.panel{background:#f5f8fa;border:1px solid #dde6ed;padding:19px;border-radius:12px}.panel h2{margin-top:0}li{margin:8px 0}footer{font-size:12px;color:#607580;margin-top:25px;border-top:1px solid #dce6eb;padding-top:15px}bdi{direction:ltr;unicode-bidi:isolate}@media(max-width:750px){main{padding:16px;margin:0;border-radius:0}header{padding:22px}h1{font-size:25px}.cards{grid-template-columns:1fr 1fr}.bottom{grid-template-columns:1fr}}@media print{@page{size:A3 landscape;margin:12mm}body{background:white}main{max-width:none;margin:0;padding:0}.controls{display:none}.scroll{overflow:visible;border:0}table{min-width:0;font-size:10px}td,th{padding:8px}small{font-size:9px}.badge{font-size:9px}header{padding:15px}h1{font-size:24px}.cards{margin:10px 0}.card{padding:8px}.card strong{font-size:16px}tr{break-inside:avoid}thead{display:table-header-group}*{print-color-adjust:exact;-webkit-print-color-adjust:exact}a{color:inherit;text-decoration:none}.bottom{break-inside:avoid}}
</style></head><body><main><header><div class="eyebrow">نسخة موسعة • مصادر LM Studio وHugging Face • تحقق في 25 أكتوبر 2026</div><h1>18 نموذجًا محليًا يعمل في LM Studio</h1><p>اختيارات لجهاز Intel i7‑13650HX وRAM ‏32 GB وبطاقة RTX 4060 Laptop ذات 8 GB. لكل نموذج رابط داخل فهرس LM Studio، ورابط للأوزان الأصلية، وملف GGUF محدد.</p></header><section class="cards"><div class="card"><strong>18 نموذجًا</strong><span>نسخ محددة؛ ليست أحجامًا مجهولة</span></div><div class="card"><strong>GGUF · Q4_K_M</strong><span>صيغة مناسبة لمحرك llama.cpp على Windows</span></div><div class="card"><strong>★ + ♥</strong><span>نجوم LM Studio وإعجابات Hugging Face</span></div><div class="card"><strong>نموذج واحد مجرّب</strong><span>Qwen3‑8B؛ بقية الملاءمات تقديرية</span></div></section>
<div class="note method"><strong>ما الذي ثبت؟</strong> جميع النماذج أدناه مدرجة محليًا في كتالوج LM Studio، ولكل منها ملف Q4_K_M موثق في Hugging Face. هذا يثبت مسار تشغيلها في التطبيق، ولا يعني أن كل نسخة اختُبرت على جهازك أو على إصدار محركك الحالي. حدّث محرك llama.cpp إذا رفض تحميل بنية حديثة. اختُبر Qwen3‑8B وحده بسياق 8192، وبلغ إجمالي استخدام البطاقة نحو 5871 MiB وقت القياس.</div>
<div class="note"><strong>قراءة الأرقام بدقة:</strong> الحجم هو مجموع بايتات ملفات أوزان Q4_K_M بالـGB العشري؛ لا يشمل ملفات الرؤية ولا KV cache ولا ذاكرة التشغيل. أحجام الذاكرة المبسطة المعروضة في كتالوج LM Studio ليست أحجام هذه الملفات بالضرورة. لا تجمع ذاكرة Intel المدمجة مع VRAM بطاقة NVIDIA. رموز السياق ليست عدد كلمات.</div>
<div class="controls"><input id="search" type="search" placeholder="ابحث باسم النموذج أو الاستخدام أو الترخيص…" aria-label="البحث في النماذج"><select id="sort" aria-label="ترتيب الجدول"><option value="default">ترتيب الدليل</option><option value="stars">نجوم LM Studio: الأعلى أولًا</option><option value="likes">إعجابات Hugging Face: الأعلى أولًا</option><option value="size">حجم الأوزان: الأصغر أولًا</option></select><button onclick="window.print()">طباعة / حفظ PDF</button><span id="count" class="count">18 من 18 نموذجًا</span></div>
<div class="scroll"><table><thead><tr><th>#</th><th>النموذج المحدد ومصادره</th><th>النوع والاستخدام</th><th>أوزان GGUF الموثقة</th><th>الملاءمة لجهازك</th><th>نجوم LM Studio</th><th>إعجابات Hugging Face</th><th>الترخيص والتعديل</th></tr></thead><tbody id="rows">'''+''.join(body)+'''</tbody></table></div>
<div class="bottom"><section class="panel"><h2>كيف تستعمل التقييم؟</h2><p>★ و♥ أعداد تفضيل وإعجاب، وليسا تقييمًا من خمس نجوم ولا اختبار جودة. لا يُقارنان بين الموقعين، وقد تستفيد النماذج الأقدم من مدة وجودها. الأرقام لقطة وقت البحث وقد تتغير.</p><p>توجد اختبارات جودة في بطاقات النماذج، لكن لا أضع ترتيبًا موحدًا مبنيًا على اختبارات مختلفة. مثلًا تعرض صفحة <a href="https://lmstudio.ai/models/ministral">Ministral</a> نتائج WildBench وMM MTBench لعدة نسخ؛ هذه نتائج منشورة، لا قياسات لملف Q4 على جهازك. لا تُنقل نتيجة عائلة كبيرة إلى نموذج صغير لمجرد اشتراكهما في الاسم.</p></section><section class="panel"><h2>الترخيص والتخصيص</h2><p>Apache‑2.0 وMIT يسمحان عمومًا بالاستخدام والتعديل والتوزيع مع التزامات الترخيص والإشعارات. Gemma له <a href="https://ai.google.dev/gemma/terms">شروط خاصة</a>. وصف «مفتوح الأوزان» أدق؛ توفر الأوزان لا يعني توفر كامل بيانات التدريب وخطواته.</p><p>يمكن تخصيص التعليمات وإضافة ملفات عبر RAG دون تعديل الأوزان. تدريب LoRA يحتاج أدوات خارج LM Studio وأصولًا مناسبة للتدريب؛ ليس من المضمون تدريب نموذج 8B على بطاقة 8 GB. النماذج التي تقبل الصور هنا تُخرج نصًا ولا تولد صورًا.</p></section></div>
<section class="panel" style="margin-top:18px"><h2>ترتيب البداية المقترح</h2><ol><li><strong>محادثة يومية:</strong> احتفظ بـQwen3‑8B الموجود بسياق 8192؛ وجود نماذج أحدث لا يثبت تفوقها في مهامك قبل المقارنة.</li><li><strong>صور ومساعد أخف:</strong> جرّب Qwen3.5‑4B أو Qwen3‑VL‑4B مع ملفات الرؤية المطلوبة.</li><li><strong>JSON واستخراج بيانات:</strong> قارن Granite 4.1 3B وMinistral 3 3B على أمثلة عربية من عملك.</li><li><strong>رياضيات واستدلال:</strong> قارن Phi‑4 mini reasoning أو DeepSeek R1 0528 8B، وقيّم صحة الإجابة وزمنها.</li></ol><p>ابدأ بسياق قصير، وراقب تقدير الذاكرة داخل LM Studio قبل التحميل. قدرة النموذج النظرية على 128K أو 256K لا تجعل ذلك عمليًا على VRAM ‏8 GB. الصفوف المشروطة قد تحتاج خفض السياق أو تحميل بعض الطبقات إلى RAM مع انخفاض السرعة.</p></section>
<footer>مصادر كل صف: صفحة النموذج وكتالوج العائلة في lmstudio.ai، وبطاقة المستودع وبيانات الملفات عبر API في huggingface.co. الإعجابات تخص المستودع الأصلي، والنجوم تخص مدخل LM Studio المحدد، وليست مجموع العائلة. نسخة الأدلة: <a href="models-evidence.json">models-evidence.json</a>. لم تُنزّل الأوزان أثناء إعداد الجدول. الصفحة محلية ومتجاوبة وقابلة للطباعة على A3 أفقيًا؛ يمكن تغيير مقاس الورق مع التحجيم.</footer></main><script>
const tableBody=document.querySelector('#rows');const original=Array.from(tableBody.rows);function update(){const term=document.querySelector('#search').value.trim().toLowerCase();const sort=document.querySelector('#sort').value;const rows=[...original];if(sort!=='default')rows.sort((a,b)=>sort==='size'?+a.dataset.size-+b.dataset.size:+b.dataset[sort]-+a.dataset[sort]);let count=0;for(const row of rows){row.hidden=!row.textContent.toLowerCase().includes(term);if(!row.hidden)count++;tableBody.appendChild(row)}document.querySelector('#count').textContent=count+' من '+original.length+' نموذجًا'}document.querySelector('#search').addEventListener('input',update);document.querySelector('#sort').addEventListener('change',update);
</script></body></html>'''
total=len(models)
page=page.replace('18 نموذجًا',f'{total} نموذجًا').replace('18 من 18',f'{total} من {total}')
vision_ids={m['lmid'] for m in models if m.get('projector_files')}
for kind in {m['kind'] for m in models if m['lmid'] in vision_ids}:
    marker=f'data-kind="{esc(kind)}"'
    page=page.replace(marker,marker+' data-vision="1"')
page=page.replace('<button onclick="window.print()">','<label style="align-self:center"><input id="visionOnly" type="checkbox" style="min-width:0;vertical-align:middle"> نماذج الرؤية فقط</label><button onclick="window.print()">')
page=page.replace("row.hidden=!row.textContent.toLowerCase().includes(term);","row.hidden=!row.textContent.toLowerCase().includes(term)||(document.querySelector('#visionOnly').checked&&row.dataset.vision!=='1');")
page=page.replace("document.querySelector('#search').addEventListener('input',update);","document.querySelector('#visionOnly').addEventListener('change',update);document.querySelector('#search').addEventListener('input',update);")
vision_section='''<section class="panel" style="margin-top:18px"><h2>الرؤية الحاسوبية داخل LM Studio: ماذا تختار؟</h2><ul><li><strong>فهم الصور ولقطات الشاشة:</strong> ابدأ بـQwen3.5‑4B أو Qwen3‑VL‑4B الموجودين في الجدول.</li><li><strong>جداول ورسوم ومستندات:</strong> أضيف Granite Vision 3.2 2B، وهو أخف؛ اختبر العربية لأن توجهه الأساسي إنجليزي.</li><li><strong>مواقع العناصر وإحداثياتها:</strong> أضيف Qwen2.5‑VL بنسختي 3B و7B؛ الإحداثيات نص يولده النموذج وقد تكون خاطئة. نسخة 3B بترخيص بحثي غير تجاري، بخلاف نسخة 7B ذات Apache‑2.0.</li><li><strong>OCR متخصص:</strong> أضيف olmOCR 2 7B. صفحة LM Studio توصي بصورة صفحة أطول أبعادها 1288 بكسل وتعليمات تحتوي بيانات المستند؛ إرسال صورة عشوائية لا يكرر خط المعالجة الكامل. العربية غير مضمونة.</li></ul><p><strong>الفرق عن أنظمة الكشف والتقسيم:</strong> النماذج هنا من نوع VLM: تدخل صورة وسؤالًا وتخرج نصًا أو إحداثيات. لم أدرج YOLO أو SAM لأنها ليست نماذج تحميل في محرك LM Studio؛ تحتاج بيئة تشغيل أخرى للتتبع اللحظي أو أقنعة التقسيم. دعم النموذج للفيديو في بيئته الأصلية لا يثبت أن واجهة LM Studio تقبل ملف فيديو كاملًا؛ استخدم صورًا أو إطارات مستخرجة عند الحاجة.</p><p><strong>ذاكرة الرؤية:</strong> نزّل ملف الأوزان وملف mmproj المطابق معًا. ابدأ بصورة واحدة وسياق 4096، وراقب تقدير الذاكرة؛ لا تعتبر مجموع حجم الملفين هو استهلاك VRAM النهائي.</p><p><strong>تقييم متخصص منشور:</strong> تسجل منظومة olmOCR v0.4.0 مع نموذج olmOCR‑2‑7B‑1025 نتيجة <bdi>82.3 ± 1.1</bdi> على olmOCR‑Bench بحسب <a href="https://lmstudio.ai/models/olmocr2">الصفحة الرسمية في LM Studio</a>. النتيجة تخص خط معالجة يتضمن تجهيز الصفحات وإعادة المحاولة، وليست تقييمًا لاستخدام GGUF Q4 داخل المحادثة على جهازك.</p></section>'''
page=page.replace('<footer>',vision_section+'<footer>')
(ROOT/'models-guide-ar.html').write_text(page,encoding='utf-8')
assert len(body)==len(DATA)==23
assert all('metadata_error' not in m and 'gguf_error' not in m for m in models)
print(f'HTML generated: {total} models, {len(vision_ids)} vision models; GGUF files, licenses and HF likes verified.')
