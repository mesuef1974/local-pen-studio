const $=id=>document.getElementById(id);
const shell=document.querySelector('.shell');
const methods={canny:['Canny','حواف رفيعة بعتبتين: حساسية التفاصيل واستمرار الخط. نقطة بداية مناسبة لمعظم الصور.'],ed:['EdgeDrawing','يبني مقاطع حواف متصلة. مناسب لاستكشاف حدود أوضح مع تقليل التشظّي.'],sobel:['Sobel','تدرجات الإضاءة الأفقية والرأسية. قد تكون الحواف أعرض من Canny.'],scharr:['Scharr','مشتقات محسّنة بمرشح ثابت 3×3، مع اختيار اتجاه التدرج.'],laplacian:['Laplacian','يرصد تغيّر التدرج في كل الاتجاهات. حساس للضوضاء؛ ابدأ بتنعيم الصورة.'],morph:['Morph. gradient','فرق التمدد والتآكل. يبرز حدود المناطق بحسب حجم العنصر البنيوي.']};
// Each field maps to a real setting in processing.py. Irrelevant controls are hidden.
const groups=[
 ['إعدادات الخوارزمية',true,[
  ['autoThreshold','عتبات تلقائية من وسيط الإضاءة','check',false,'canny'],
  ['low','العتبة الدنيا','range',60,0,255,1,'manualCanny'],
  ['high','العتبة العليا','range',150,1,255,1,'manualCanny'],
  ['autoSpread','هامش العتبات التلقائية ٪','range',33,1,90,1,'autoCanny'],
  ['aperture','حجم مشتقة Canny','select',3,[[3,'3 × 3'],[5,'5 × 5'],[7,'7 × 7']],'canny'],
  ['l2','حساب التدرج بمعيار L2','check',true,'canny'],
  ['pf','اكتشاف حر المعلمات · PF','check',false,'ed'],
  ['gradientThreshold','عتبة قوة التدرج','range',24,1,120,1,'edManual'],
  ['anchor','حساسية نقاط الارتكاز','range',4,0,50,1,'edManual'],
  ['scan','فاصل المسح · بكسل','range',1,1,8,1,'edManual'],
  ['minPath','أقل طول مقطع · بكسل','range',12,2,100,1,'ed'],
  ['edSigma','تنعيم EdgeDrawing الداخلي','range',1,.1,4,.1,'ed'],
  ['edOperator','مؤثر التدرج','select',0,[[0,'Prewitt'],[1,'Sobel'],[2,'Scharr'],[3,'LSD']],'ed'],
  ['sumFlag','جمع مركبتي التدرج','check',true,'ed'],
  ['direction','اتجاه الحواف','select','xy',[['xy','الاتجاهان'],['x','تغيّر أفقي · حدود رأسية'],['y','تغيّر رأسي · حدود أفقية']],'direction'],
  ['derivativeKernel','حجم مرشح المشتقة','select',3,[[1,'1'],[3,'3 × 3'],[5,'5 × 5'],[7,'7 × 7']],'derivative'],
  ['edgeThreshold','عتبة قبول التدرج','range',45,0,255,1,'gradient'],
  ['normalizeGradient','تطبيع قوة التدرج إلى 0–255','check',true,'gradient'],
 ]],
 ['تهيئة الصورة والتباين',false,[
  ['resolution','أقصى ضلع للمعالجة','select',1600,[[512,'512 بكسل'],[1024,'1024 بكسل'],[1600,'1600 بكسل'],[2000,'2000 بكسل']]],
  ['channel','قناة استخراج الحواف','select','gray',[['gray','رمادي قياسي'],['lab','إضاءة Lab · L'],['value','قيمة HSV · V'],['red','الأحمر'],['green','الأخضر'],['blue','الأزرق']]],
  ['brightness','السطوع','range',0,-100,100,1],
  ['contrast','التباين ٪','range',100,20,250,1],
  ['gamma','غاما · محايد 100','range',100,25,250,1],
  ['equalize','توزيع الإضاءة','select','none',[['none','دون تعديل'],['histogram','موازنة المدرج التكراري'],['clahe','تباين محلي · CLAHE']]],
  ['clip','حد تعزيز CLAHE','range',2,.5,8,.1,'clahe'],
  ['grid','عدد بلاطات CLAHE لكل ضلع','range',8,2,32,1,'clahe'],
 ]],
 ['تخفيف الضوضاء والملمس',false,[
  ['noise','مرشح التجهيز','select','gaussian',[['none','دون تنعيم'],['gaussian','Gaussian · تنعيم عام'],['bilateral','Bilateral · الحفاظ على الحدود'],['median','Median · الضوضاء النقطية'],['nlm','Non-local means · تنقية أبطأ']]],
  ['kernel','حجم نافذة التنعيم','select',3,[[3,'3 × 3'],[5,'5 × 5'],[7,'7 × 7'],[9,'9 × 9'],[11,'11 × 11']],'noiseKernel'],
  ['sigma','قوة التنعيم · سيغما','range',1.2,.1,5,.1,'gaussian'],
  ['sigmaColor','تسامح فرق اللون','range',45,1,150,1,'bilateral'],
  ['sigmaSpace','مدى التأثير المكاني','range',9,1,30,1,'bilateral'],
  ['nlm','قوة تنقية NLM','range',8,1,20,1,'nlm'],
 ]],
 ['تنقية الحواف وتشكيل الخط',false,[
  ['morphKernel','حجم عنصر التشكيل','select',3,[[3,'3 × 3'],[5,'5 × 5'],[7,'7 × 7'],[9,'9 × 9'],[11,'11 × 11']]],
  ['close','إغلاق الفجوات · تكرار','range',0,0,3,1],
  ['opening','إزالة النتوءات · تكرار','range',0,0,3,1],
  ['component','حذف مكونات أصغر من · بكسل','range',0,0,500,1],
  ['thin','ترقيق الخط إلى بكسل واحد','check',false],
  ['thickness','سماكة الخط النهائي · بكسل','range',1,1,5,1],
 ]],
 ['لون النتيجة والخلفية',false,[
  ['ink','لون الحواف','color','#142b42'],
  ['background','خلفية PNG','select','white',[['white','بيضاء'],['black','سوداء'],['transparent','شفافة']]],
  ['overlayOpacity','وضوح الحواف في التراكب ٪','range',70,0,100,1],
 ]],
];
const fields=groups.flatMap(g=>g[2]);
const defaults=Object.fromEntries(fields.map(f=>[f[0],f[3]]));
const preparationFields=new Set(groups.slice(1,3).flatMap(g=>g[2].map(f=>f[0])));
$('sourceView').value='prepared';
function sourcePreview(){const prepared=$('sourceView').value==='prepared';$('sourceImage').src=prepared&&output?output.prepared:source;$('sourceCaption').textContent=prepared?'مدخل الحواف بعد التجهيز':'الصورة الأصلية دون تعديل';$('sourceImage').alt=prepared?'مدخل كشف الحواف بعد تجهيز الصورة':'الصورة الأصلية دون تعديل';}
let method='canny',source='',output=null,sourceVersion=0,view='split',revision=0,busy=false,pending=false,timer,loadRevision=0;
function control(f){const [id,title,type,value]=f;let when=type==='check'?f[4]:type==='range'?f[7]:type==='select'?f[5]:null;const condition=when?` data-when="${when}"`:'';
 if(type==='check')return `<label class="check"${condition}><input id="${id}" type="checkbox" ${value?'checked':''}>${title}</label>`;
 const input=type==='select'?`<select id="${id}">${f[4].map(([v,t])=>`<option value="${v}"${v===value?' selected':''}>${t}</option>`).join('')}</select>`:type==='range'?`<input id="${id}" type="range" min="${f[4]}" max="${f[5]}" step="${f[6]}" value="${value}">`:`<input id="${id}" type="color" value="${value}">`;
 return `<div class="field"${condition}><label for="${id}">${title}${type==='range'?`<output id="${id}Value" for="${id}">${value}</output>`:''}</label>${input}</div>`;
}
$('controls').innerHTML=groups.map(([title,open,items])=>`<details class="tool-group"${open?' open':''}><summary>${title}</summary><div class="group-content">${items.map(control).join('')}${title==='تنقية الحواف وتشكيل الخط'?'<p class="help">ابدأ بصفر للتنقية. قد يحذف الفتح والترقيق تفاصيل رفيعة، وقد يضيف الإغلاق وصلات غير مطلوبة.</p>':''}</div></details>`).join('');
$('methods').innerHTML=Object.entries(methods).map(([id,[name]])=>`<button data-method="${id}" aria-pressed="${id===method}"><i aria-hidden="true"></i>${name}</button>`).join('');
function values(){return {method,...Object.fromEntries(fields.map(([id,,type])=>[id,type==='check'?$(id).checked:type==='range'||(type==='select'&&typeof defaults[id]==='number')?Number($(id).value):$(id).value]))};}
function sync(){
 const conditions={canny:method==='canny',manualCanny:method==='canny'&&!$('autoThreshold').checked,autoCanny:method==='canny'&&$('autoThreshold').checked,ed:method==='ed',edManual:method==='ed'&&!$('pf').checked,direction:['sobel','scharr'].includes(method),derivative:['sobel','laplacian'].includes(method),gradient:['sobel','scharr','laplacian','morph'].includes(method),clahe:$('equalize').value==='clahe',noiseKernel:['gaussian','bilateral','median'].includes($('noise').value),gaussian:$('noise').value==='gaussian',bilateral:$('noise').value==='bilateral',nlm:$('noise').value==='nlm'};
 document.querySelectorAll('[data-when]').forEach(el=>{el.hidden=!conditions[el.dataset.when];el.querySelectorAll('input,select').forEach(input=>input.disabled=el.hidden);});
 for(const [id,,type] of fields)if(type==='range')$(id+'Value').textContent=$(id).value;
 document.querySelectorAll('[data-method]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.method===method));$('methodHelp').textContent=methods[method][1];$('algorithmLabel').textContent=methods[method][0];
}
function clearPreset(){activePreset=null;renderPresets();}
function showError(message){$('error').textContent=message;$('error').hidden=!message;}
function invalidate(){revision++;shell.dataset.stale='true';$('save').disabled=true;showError('');for(const id of ['timing','coverage','removed','size'])$(id).textContent='—';}
function schedule(){sync();invalidate();clearTimeout(timer);if(source&&$('auto').checked)timer=setTimeout(work,300);}
for(const [id] of fields)$(id).addEventListener('input',()=>{if(preparationFields.has(id)){$('sourceView').value='prepared';sourcePreview();}if(id==='background'){
 if($('background').value==='black'&&['#142b42','#000000'].includes($('ink').value))$('ink').value='#ffffff';
 else if($('background').value==='white'&&$('ink').value==='#ffffff')$('ink').value='#142b42';
 }if(!presetKeptFields.includes(id))clearPreset();schedule();});
document.querySelectorAll('[data-method]').forEach(b=>b.onclick=()=>{method=b.dataset.method;applyPreset('balanced');});
function assign(s){method=s.method||'canny';for(const [id,,type] of fields){const v=s[id]??defaults[id];if(type==='check')$(id).checked=v;else $(id).value=v;}$('sourceView').value='prepared';sourcePreview();sync();}
// Recipes are specific to the chosen detector; none silently switches algorithms.
// Format: stable key, Arabic label, practical effect, processing settings.
const methodPresets = {
 canny:[
  ['balanced','متوازن','حواف رفيعة مع تنعيم خفيف وعتبتين متوسطتين.',{}],
  ['portrait','ملامح هادئة','يخفف الملمس قبل الكشف ويستبعد الشظايا الصغيرة؛ لا يتعرف على الوجوه.',{noise:'bilateral',kernel:7,sigmaColor:65,sigmaSpace:12,low:45,high:110,component:8}],
  ['clean','تقليل الملمس','تنعيم أقوى وعتبات أعلى لتقليل التفاصيل الصغيرة.',{kernel:5,sigma:1.6,low:75,high:175,component:20}],
  ['detail','تفاصيل دقيقة','عتبات منخفضة وتنعيم خفيف مع إبقاء المكونات الصغيرة.',{kernel:3,sigma:.6,low:22,high:65,thin:true}],
  ['structure','حدود واضحة','يركز على الحواف القوية ويغلق فجوات صغيرة؛ قد يصل خطوطًا متقاربة.',{kernel:5,sigma:1.3,low:85,high:185,close:1,thin:true,component:12}],
  ['lowlight','إضاءة ضعيفة','يعزز التباين المحلي ويخفف الضوضاء ثم يلتقط الحواف الأضعف.',{equalize:'clahe',clip:2.5,gamma:115,noise:'bilateral',kernel:7,sigmaColor:55,sigmaSpace:10,low:30,high:85}],
  ['thin','خطوط رفيعة','يرقّق الناتج إلى بكسل واحد دون حذف المكونات الصغيرة.',{low:45,high:120,thin:true}],
  ['auto','حساسية تلقائية','يحسب العتبتين من وسيط إضاءة الصورة مع تنعيم يحفظ الحدود.',{autoThreshold:true,autoSpread:25,noise:'bilateral',kernel:5,sigmaColor:40,sigmaSpace:8}],
 ],
 ed:[
  ['balanced','متوازن','مقاطع متصلة بقوة تدرج متوسطة وأقل طول 12 بكسل.',{gradientThreshold:24,minPath:12}],
  ['portrait','ملامح هادئة','تخفيف الملمس مع مقاطع قصيرة للحفاظ على تفاصيل الملامح.',{noise:'bilateral',kernel:7,sigmaColor:60,sigmaSpace:12,gradientThreshold:20,anchor:3,minPath:7,component:5}],
  ['clean','تقليل الملمس','يرفع عتبة التدرج وطول المقاطع لتقليل التشظي.',{kernel:5,sigma:1.5,gradientThreshold:45,anchor:6,minPath:25,component:16}],
  ['detail','تفاصيل دقيقة','يلتقط تدرجات أضعف ومقاطع أقصر مع تنعيم داخلي أخف.',{sigma:.6,gradientThreshold:12,anchor:1,minPath:4,edSigma:.6}],
  ['structure','حدود ممتدة','مقاطع أطول باستخدام Sobel لاستكشاف حدود الأجسام.',{gradientThreshold:30,minPath:30,edOperator:1,kernel:5,sigma:1.2,component:12}],
  ['lowlight','إضاءة ضعيفة','تباين محلي وعتبة تدرج منخفضة للصور الداكنة.',{equalize:'clahe',clip:2,gamma:115,noise:'bilateral',kernel:7,gradientThreshold:14,anchor:2,minPath:6}],
  ['thin','خطوط رفيعة','يرقّق الحواف المتصلة مع إبقاء المقاطع القصيرة.',{gradientThreshold:20,minPath:6,thin:true}],
  ['auto','اكتشاف تلقائي PF','يفعّل وضع EdgeDrawing الحر من معلمات العتبات.',{pf:true,minPath:8,edSigma:.8,sigma:.8}],
 ],
 sobel:[
  ['balanced','متوازن','يجمع تدرجي الاتجاهين بمرشح 3×3 وعتبة متوسطة.',{edgeThreshold:50}],
  ['portrait','ملامح هادئة','يخفف نسيج البشرة ثم يرقّق خطوط التدرج الناتجة.',{noise:'bilateral',kernel:7,sigmaColor:65,sigmaSpace:12,edgeThreshold:55,thin:true,component:6}],
  ['clean','تقليل الملمس','تنعيم وعتبة أعلى لاستبعاد فروق الإضاءة الضعيفة.',{kernel:5,sigma:1.6,edgeThreshold:85,component:18}],
  ['detail','تفاصيل دقيقة','عتبة منخفضة لحفظ التدرجات الدقيقة وقد تظهر معها ضوضاء.',{sigma:.6,edgeThreshold:18,thin:true}],
  ['structure','حدود واضحة','عتبة قوية وإغلاق محدود ثم ترقيق؛ قد يصل حواف متقاربة.',{edgeThreshold:80,kernel:5,sigma:1.2,close:1,thin:true,component:12}],
  ['lowlight','إضاءة ضعيفة','تعزيز محلي قبل حساب التدرج لتظهر التفاصيل الداكنة.',{equalize:'clahe',clip:2.5,gamma:115,noise:'bilateral',kernel:7,edgeThreshold:32}],
  ['thin','خطوط رفيعة','يحوّل حدود التدرج العريضة إلى خطوط بكسل واحد.',{edgeThreshold:45,thin:true}],
  ['bold','خطوط بارزة','حواف قوية بسماكة نهائية بكسلين.',{edgeThreshold:70,thickness:2,component:8}],
  ['vertical','حدود رأسية','يعزل التغير الأفقي لإظهار الحدود الرأسية غالبًا.',{direction:'x',edgeThreshold:50}],
  ['horizontal','حدود أفقية','يعزل التغير الرأسي لإظهار الحدود الأفقية غالبًا.',{direction:'y',edgeThreshold:50}],
 ],
 scharr:[
  ['balanced','متوازن','مشتقات Scharr بالاتجاهين مع تطبيع وعتبة متوسطة.',{edgeThreshold:45}],
  ['portrait','ملامح هادئة','Bilateral لتخفيف الملمس ثم ترقيق المشتقات.',{noise:'bilateral',kernel:7,sigmaColor:65,sigmaSpace:12,edgeThreshold:55,thin:true,component:6}],
  ['clean','تقليل الملمس','تنعيم أقوى وعتبة أعلى لتقليل الخطوط الثانوية.',{kernel:5,sigma:1.5,edgeThreshold:80,component:18}],
  ['detail','تفاصيل دقيقة','يُبقي التدرجات الضعيفة مع تنعيم خفيف.',{sigma:.6,edgeThreshold:16,thin:true}],
  ['structure','حدود واضحة','يركز على التدرجات القوية ويستبعد المكونات الصغيرة.',{kernel:5,sigma:1.2,edgeThreshold:85,component:14,thin:true}],
  ['lowlight','إضاءة ضعيفة','CLAHE مع تهدئة الضوضاء قبل مشتقات Scharr.',{equalize:'clahe',clip:2.5,gamma:115,noise:'bilateral',kernel:7,edgeThreshold:30}],
  ['thin','خطوط رفيعة','ترقيق بكسل واحد بعد قبول التدرجات المتوسطة.',{edgeThreshold:42,thin:true}],
  ['bold','خطوط بارزة','عتبة قوية وسماكة بكسلين لاستكشاف الكتل.',{edgeThreshold:70,thickness:2,component:8}],
  ['vertical','حدود رأسية','مشتقة Scharr الأفقية لإبراز الحدود الرأسية.',{direction:'x',edgeThreshold:45}],
  ['horizontal','حدود أفقية','مشتقة Scharr الرأسية لإبراز الحدود الأفقية.',{direction:'y',edgeThreshold:45}],
 ],
 laplacian:[
  ['balanced','متوازن','تنعيم 5×5 قبل المشتقة الثانية لتخفيف حساسيتها للضوضاء.',{kernel:5,sigma:1.2,edgeThreshold:35}],
  ['portrait','ملامح هادئة','تخفيف الملمس ورفع عتبة المشتقة ثم ترقيق الخط.',{noise:'bilateral',kernel:7,sigmaColor:70,sigmaSpace:12,edgeThreshold:55,thin:true,component:8}],
  ['clean','تقليل الضوضاء','مرشح Median مع عتبة قوية وحذف المكونات الصغيرة.',{noise:'median',kernel:5,edgeThreshold:75,component:20}],
  ['detail','تفاصيل دقيقة','مشتقة حساسة بعتبة منخفضة؛ قد تُظهر نسيج الصورة.',{sigma:.7,edgeThreshold:18,thin:true}],
  ['structure','حدود واضحة','تنعيم أقوى ومشتقة 5×5 لاستخراج حدود أوسع.',{kernel:7,sigma:1.6,derivativeKernel:5,edgeThreshold:65,component:15,thin:true}],
  ['lowlight','إضاءة ضعيفة','تعزيز التباين المحلي مع تنقية قبل المشتقة الثانية.',{equalize:'clahe',clip:2,gamma:115,noise:'bilateral',kernel:7,edgeThreshold:28}],
  ['thin','خطوط رفيعة','ترقيق الخطوط المقبولة مع إبقاء المكونات الصغيرة.',{kernel:5,sigma:1.1,edgeThreshold:40,thin:true}],
  ['bold','خطوط بارزة','يُبقي الحدود الأقوى بسماكة بكسلين.',{kernel:5,sigma:1.2,edgeThreshold:65,thickness:2,component:8}],
 ],
 morph:[
  ['balanced','متوازن','فرق التمدد والتآكل بعنصر 3×3 وعتبة متوسطة.',{edgeThreshold:40,morphKernel:3}],
  ['portrait','ملامح هادئة','تخفيف الملمس قبل تشكيل حدود بعنصر صغير وترقيقها.',{noise:'bilateral',kernel:7,sigmaColor:70,sigmaSpace:12,edgeThreshold:55,morphKernel:3,thin:true,component:6}],
  ['clean','تقليل الملمس','تنعيم أقوى وعتبة أعلى للحدود المورفولوجية.',{noise:'bilateral',kernel:7,sigmaColor:85,sigmaSpace:14,edgeThreshold:85,morphKernel:3,component:18}],
  ['detail','تفاصيل دقيقة','عنصر صغير وعتبة منخفضة مع إبقاء المكونات الدقيقة.',{sigma:.7,edgeThreshold:18,morphKernel:3,thin:true}],
  ['structure','حدود واسعة','عنصر 7×7 يلتقط نطاقًا أوسع حول حدود المناطق.',{kernel:5,sigma:1.3,morphKernel:7,edgeThreshold:75,component:15}],
  ['lowlight','إضاءة ضعيفة','تباين محلي قبل التشكيل بعنصر 3×3.',{equalize:'clahe',clip:2.5,gamma:115,noise:'bilateral',kernel:7,edgeThreshold:30,morphKernel:3}],
  ['thin','خطوط رفيعة','عنصر 3×3 ثم ترقيق الناتج إلى بكسل واحد.',{edgeThreshold:45,morphKernel:3,thin:true}],
  ['bold','خطوط بارزة','حدود بعنصر 5×5 وسماكة نهائية إضافية.',{kernel:5,sigma:1.2,morphKernel:5,edgeThreshold:65,thickness:2,component:8}],
 ],
};
const presetKeptFields=['resolution','ink','background','overlayOpacity'];
let activePreset='balanced';
function renderPresets(){
 const focused=document.activeElement?.dataset?.preset;
 const choices=methodPresets[method];$('presetHeading').textContent='تفضيلات '+methods[method][0];
 $('presets').innerHTML=choices.map(([key,label])=>`<button data-preset="${key}" aria-pressed="${key===activePreset}">${label}</button>`).join('');
 const selected=choices.find(p=>p[0]===activePreset);$('presetState').textContent=selected?selected[1]:'مخصص';
 $('presetDescription').textContent=selected?selected[2]:'إعداداتك اليدوية الحالية؛ اختر تفضيلًا لإعادة ضبط مجموعة الأدوات.';
 document.querySelectorAll('[data-preset]').forEach(button=>button.onclick=()=>applyPreset(button.dataset.preset));
 if(focused)[...document.querySelectorAll('[data-preset]')].find(button=>button.dataset.preset===focused)?.focus();
}
function applyPreset(key){
 const recipe=methodPresets[method].find(p=>p[0]===key);if(!recipe)return;
 const current=values(),kept=Object.fromEntries(presetKeptFields.map(id=>[id,current[id]]));
 assign({...defaults,...recipe[3],...kept,method});activePreset=key;renderPresets();schedule();
}
$('reset').onclick=()=>applyPreset('balanced');
renderPresets();
async function work(){
 clearTimeout(timer);if(!source)return;if(busy){pending=true;return;}busy=true;pending=false;const job=revision;const version=sourceVersion;$('progress').hidden=false;$('workspace').setAttribute('aria-busy','true');$('run').disabled=true;
 try{const response=await fetch('/api/edges',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:source,settings:values()})});const data=await response.json();if(job!==revision||version!==sourceVersion)return;if(!response.ok)throw Error(data.error||'تعذرت معالجة الصورة.');
  output=data;$('resultImage').src=view==='overlay'?data.overlay:data.image;$('resultImage').hidden=false;$('resultPlaceholder').hidden=true;
  sourcePreview();
  $('timing').textContent=data.milliseconds<1000?`${Math.round(data.milliseconds)} مللي ثانية`:`${(data.milliseconds/1000).toFixed(2)} ثانية`;
  $('coverage').textContent=data.coverage+'%';$('removed').textContent=data.removedComponents.toLocaleString('ar-u-nu-latn');$('size').textContent=`${data.width} × ${data.height}`;$('engine').textContent=`OpenCV ${data.opencv} / CPU`;
  $('dimensions').textContent=`${data.width} × ${data.height} px`+(method==='canny'?` / ${data.low}–${data.high}`:'');shell.dataset.stale='false';$('save').disabled=false;showError('');
 }catch(error){if(job===revision)showError(error.message||'تعذر الاتصال بالسيرفر المحلي.');}
 finally{busy=false;$('progress').hidden=true;$('workspace').setAttribute('aria-busy','false');$('run').disabled=!source;requestAnimationFrame(fit);if(pending){pending=false;work();}}
}
$('run').onclick=()=>{pending=true;work();};
$('auto').onchange=()=>{if($('auto').checked&&source&&shell.dataset.stale==='true')work();else clearTimeout(timer);};
async function loadFile(file){
 if(!file)return;const load=++loadRevision;if(!['image/png','image/jpeg','image/webp'].includes(file.type)){showError('اختر PNG أو JPG أو WebP.');return;}if(file.size>20_000_000){showError('اختر صورة أصغر من 20 ميغابايت.');return;}
 const url=URL.createObjectURL(file);
 try{const image=new Image();image.src=url;await image.decode();if(load!==loadRevision)return;if(image.naturalWidth*image.naturalHeight>60_000_000)throw Error('الصورة كبيرة جدًا؛ صغّرها إلى أقل من 60 مليون بكسل أولًا.');
  const scale=Math.min(1,2000/Math.max(image.naturalWidth,image.naturalHeight));const c=document.createElement('canvas');c.width=Math.max(1,Math.round(image.naturalWidth*scale));c.height=Math.max(1,Math.round(image.naturalHeight*scale));const ctx=c.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(image,0,0,c.width,c.height);
  source=c.toDataURL('image/png');if(source.length>8_000_000)source=c.toDataURL('image/jpeg',.95);sourceVersion++;output=null;invalidate();$('sourceImage').src=source;$('sourceImage').alt='الصورة المرجعية: '+file.name;$('resultImage').hidden=true;$('resultPlaceholder').hidden=false;$('empty').hidden=true;$('imageGrid').hidden=false;$('filename').textContent=file.name;$('run').disabled=false;$('dimensions').textContent=`${c.width} × ${c.height} px`;$('zoom').value=100;fit();if(busy)pending=true;else work();
 }catch(error){if(load===loadRevision)showError(error.message||'تعذر فتح الصورة.');}finally{URL.revokeObjectURL(url);$('file').value='';}
}
$('file').onchange=()=>loadFile($('file').files[0]);$('emptyUpload').onclick=()=>$('file').click();
$('sample').onclick=async()=>{try{const response=await fetch('/sample.png');if(!response.ok)throw Error('الصورة التجريبية غير متاحة.');await loadFile(new File([await response.blob()],'صورة تجريبية.png',{type:'image/png'}));}catch(error){showError(error.message);}};
for(const event of ['dragenter','dragover'])shell.addEventListener(event,e=>{e.preventDefault();shell.classList.add('dragging');});
shell.addEventListener('dragleave',e=>{if(!shell.contains(e.relatedTarget))shell.classList.remove('dragging');});shell.addEventListener('drop',e=>{e.preventDefault();shell.classList.remove('dragging');loadFile(e.dataTransfer.files[0]);});
function fit(){
 const zoom=Number($('zoom').value)/100;$('zoomValue').textContent=$('zoom').value+'%';
 for(const id of ['sourceImage','resultImage']){const image=$(id),paper=image.parentElement,viewport=paper.parentElement;if(!image.naturalWidth||image.hidden)continue;const css=getComputedStyle(viewport),availableW=viewport.clientWidth-parseFloat(css.paddingLeft)-parseFloat(css.paddingRight),availableH=viewport.clientHeight-parseFloat(css.paddingTop)-parseFloat(css.paddingBottom)-20;const width=Math.min(availableW,availableH*image.naturalWidth/image.naturalHeight);paper.style.width=Math.max(1,width*zoom)+'px';}
}
for(const id of ['sourceImage','resultImage'])$(id).onload=fit;
new ResizeObserver(()=>requestAnimationFrame(fit)).observe($('workspace'));
$('zoom').oninput=fit;$('fit').onclick=()=>{$('zoom').value=100;fit();};
document.querySelectorAll('button[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;shell.dataset.view=view;document.querySelectorAll('button[data-view]').forEach(other=>other.setAttribute('aria-pressed',b===other));$('resultCaption').textContent=view==='overlay'?'الحواف فوق الصورة':'صورة الحواف';if(output)$('resultImage').src=view==='overlay'?output.overlay:output.image;requestAnimationFrame(fit);});
$('sourceView').onchange=sourcePreview;
function download(url,name){const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();}
$('save').onclick=()=>{if(output&&shell.dataset.stale==='false')download(output.image,'edges-'+method+'.png');};
$('saveSettings').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,settings:values()},null,2)],{type:'application/json'}));download(url,'edge-studio-settings.json');setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('settingsFile').onchange=async()=>{try{const file=$('settingsFile').files[0];if(!file)return;if(file.size>50000)throw Error('ملف الإعدادات أكبر من المتوقع.');const data=JSON.parse(await file.text());if(data.version!==1||!data.settings||typeof data.settings!=='object'||!Object.hasOwn(methods,data.settings.method))throw Error('ملف إعدادات غير متوافق.');const candidate={...defaults,...data.settings};for(const [id,,type] of fields){const v=candidate[id];if(type==='check'&&typeof v!=='boolean')throw Error('خيار غير صحيح: '+id);if(type==='range'&&(typeof v!=='number'||!Number.isFinite(v)||v<Number($(id).min)||v>Number($(id).max)))throw Error('قيمة غير صحيحة: '+id);if(type==='select'&&![...$(id).options].some(o=>o.value===String(v)))throw Error('خيار غير صحيح: '+id);if(type==='color'&&!/^#[0-9a-f]{6}$/i.test(v))throw Error('لون غير صحيح.');}assign(candidate);clearPreset();schedule();}catch(error){showError(error.message||'تعذر قراءة الإعدادات.');}finally{$('settingsFile').value='';}};
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&source){event.preventDefault();work();}});
sync();shell.dataset.view=view;
