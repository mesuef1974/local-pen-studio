import {composePrompt} from './flux-prompts.js';
const $=id=>document.getElementById(id);
const element=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};

export async function createFluxControls({api,onChange,onUseHistory,download}){
 const response=await fetch('/flux-catalog.json');
 if(!response.ok)throw Error('تعذر تحميل مكتبة البرومبتات. حدّث الصفحة بعد تشغيل السيرفر الجديد.');
 const catalog=await response.json(),references=[],history=[];
 let locked=false,uploading=false,sourceForCompare=null,compareStatus='';
 const savedKey='flux-professional-prompts-v1';
 let saved=[];try{const data=JSON.parse(localStorage.getItem(savedKey)||'[]');if(Array.isArray(data))saved=data.filter(v=>typeof v.title==='string'&&typeof v.prompt==='string').slice(0,20);}catch{}
 const note=text=>{$('fluxNote').textContent=text;};
 const descriptions={
  'رسم خطي للمراجعة قبل المسارات':{purpose:'تحويل فني إلى خطوط قليلة أو واضحة.',change:'قد يبسط الوجه والشعر والتفاصيل الداخلية.',preserve:'يحاول إبقاء التكوين والسمات الظاهرة.',fit:'للمراجعة الفنية فقط؛ لا يضمن تطابق المسارات.'},
  'الرسم الفني':{purpose:'إنتاج معالجة فنية بأسلوب محدد.',change:'قد يغير الملامح أو النسب أو الظلال بحسب الأسلوب.',preserve:'يحاول إبقاء موضوع الصورة وسماتها العامة.',fit:'غير موصى به للتتبّع المطابق.'},
  'قوالب متخصصة':{purpose:'رسم موضوع متخصص كغرض أو حيوان أو مبنى.',change:'يبسط أو يعيد تفسير التفاصيل وفق نوع الموضوع.',preserve:'يحاول إبقاء الشكل والسمات الواضحة.',fit:'استخدمه للموضوع المناسب؛ راجع النتيجة.'},
  'تعديل الصور':{purpose:'تنفيذ تعديل بصري محدد على الصورة.',change:'يغير الإضاءة أو الخلفية أو عناصر المشهد.',preserve:'يحاول إبقاء الموضوع الرئيسي.',fit:'ليس قالب استخراج حواف.'},
  'مراجع متعددة':{purpose:'استخدام صورة إضافية بدور مرجعي محدد.',change:'قد يدمج خصائص المرجع بحسب دوره.',preserve:'يحاول اتباع أدوار الصور المسندة.',fit:'راجع الهوية والمحتوى قبل الاعتماد.'},
  'التوليد من النص':{purpose:'إنشاء صورة جديدة انطلاقًا من وصف نصي.',change:'ينشئ المحتوى والتكوين من الوصف.',preserve:'لا يستخدم صورة المستخدم كمصدر محتوى.',fit:'ليس تحويلًا لصورة أصلية.'},
  'تعليمات حرة':{purpose:'صياغة توجيه مخصص للمهمة.',change:'بحسب النص الذي يكتبه المستخدم.',preserve:'بحسب التوجيهات الإضافية المحددة.',fit:'النتيجة توليدية وتحتاج إلى مراجعة.'}
 };
 const guidance=category=>descriptions[category]||descriptions['تعليمات حرة'];
 const lineCategory='رسم خطي للمراجعة قبل المسارات';
 function promptWarnings(s){const warnings=[],preset=catalog.presets.find(item=>item.id===s.style);
  if(preset?.category===lineCategory&&s.controls.shading==='full')warnings.push('قالب الرسم الخطي مع «تظليل غني»: قد ينتج مساحات كثيفة لا تلائم المسارات.');
  if(preset?.category===lineCategory&&s.controls.detail==='high')warnings.push('التفاصيل الغنية قد تضيف خطوطًا كثيرة أو تغيّر تفاصيل الصورة.');
  if(preset?.id==='coloring'&&['light','full'].includes(s.controls.shading))warnings.push('قالب صفحة التلوين يطلب مساحات بيضاء، وإعداد الظلال يطلب تظليلًا.');
  if(preset?.id==='caricature'&&s.preserve.identity)warnings.push('الكاريكاتير يبالغ فنيًا؛ خيار محاولة حفظ الهوية لا يضمن ثبات الملامح.');
  const selected=[s.style,$('compareStyleB').value,$('compareStyleC').value].filter(Boolean);
  return {warnings,compare:new Set(selected).size!==selected.length?['يوجد قالب مكرر في المقارنة؛ اختر قوالب مختلفة لتكون المقارنة مفيدة.']:[]};
 }
 const changed=()=>{compareStatus='';refreshPrompt();onChange();};
 const categoryOrder=['رسم خطي للمراجعة قبل المسارات','الرسم الفني','قوالب متخصصة','تعديل الصور','مراجع متعددة','التوليد من النص','تعليمات حرة'];
 for(const category of categoryOrder.filter(name=>catalog.presets.some(p=>p.category===name))){
  const group=element('optgroup');group.label=category;
  for(const preset of catalog.presets.filter(p=>p.category===category)){const option=element('option',preset.title);option.value=preset.id;group.append(option);}
  $('genStyle').append(group);
  const option=element('option',category);option.value=category;$('libraryCategory').append(option);
 }
 for(const id of ['compareStyleB','compareStyleC'])for(const preset of catalog.presets.filter(item=>item.mode==='edit'&&item.id!=='custom')){
  const option=element('option',`${preset.title} · ${preset.category}`);option.value=preset.id;$(id).append(option);
 }
 const defaultAlternative=catalog.presets.find(item=>item.id==='minimal'&&item.mode==='edit');
 if(defaultAlternative){$('compareStyleB').value=defaultAlternative.id;$('comparePromptB').value=defaultAlternative.prompt;}
 for(const [key,group]of Object.entries(catalog.controls)){
  const field=element('div',undefined,'field'),label=element('label',group.label),select=element('select');
  select.id='fluxControl_'+key;label.htmlFor=select.id;
  for(const [value,rule]of Object.entries(group.options)){const option=element('option',rule[0]);option.value=value;select.append(option);}
  select.onchange=changed;field.append(label,select);$('fluxGuidance').append(field);
 }
 for(const [key,rule]of Object.entries(catalog.preserve)){
  const label=element('label',undefined,'check'),input=element('input');input.type='checkbox';input.id='fluxPreserve_'+key;input.checked=true;input.onchange=changed;label.append(input,document.createTextNode(rule[0]));$('fluxPreserve').append(label);
 }
 function settings(){return {
  style:$('genStyle').value,prompt:$('genPrompt').value.trim(),mode:$('genMode').value,
  seed:Number($('genSeed').value),resolution:Number($('genResolution').value),aspect:$('genAspect').value,
  controls:Object.fromEntries(Object.keys(catalog.controls).map(key=>[key,$('fluxControl_'+key).value])),
  preserve:Object.fromEntries(Object.keys(catalog.preserve).map(key=>[key,$('fluxPreserve_'+key).checked])),
  references:$('genMode').value==='multi'?references.map(({image,role})=>({image,role})):[],
 };}
 function refreshPrompt(){const s=settings(),preset=catalog.presets.find(item=>item.id===s.style),{warnings,compare:compareWarnings}=promptWarnings(s);$('effectivePrompt').value=composePrompt(catalog,s);$('promptCount').textContent=`${$('effectivePrompt').value.length} حرف · يُتحقق من حد 512 رمزًا قبل التوليد`;$('referencePanel').hidden=s.mode!=='multi';$('fluxPreserveSection').hidden=s.mode==='generate';$('textModeHint').hidden=s.mode!=='generate';
  const summary=guidance(preset?.category);$('fluxNote').textContent=`${summary.purpose} ${summary.fit}`;$('promptConflict').textContent=warnings.join(' ');
  const a=$('comparePromptA');if(a)a.textContent=`A · ${preset?.title||'القالب الحالي'} · البذرة ${s.seed} · ${s.resolution}px`;
  const b=$('compareStyleB').value,c=$('compareStyleC').value,busyConflict=new Set([s.style,b,c].filter(Boolean)).size<[s.style,b,c].filter(Boolean).length;
  const bReady=!!b&&!!$('comparePromptB').value.trim(),cReady=!c||!!$('comparePromptC').value.trim();
  const canCompare=s.mode==='edit'&&!!sourceForCompare&&!!s.prompt&&bReady&&cReady&&!busyConflict;
  $('comparePromptB').disabled=!b;$('comparePromptC').disabled=!c;$('generateCompare').disabled=locked||!canCompare;
  $('compareWarning').textContent=compareStatus||(s.mode!=='edit'?'المقارنة المتوازية متاحة في وضع تعديل الصورة فقط.':!sourceForCompare?'افتح صورة أولًا لتتم مقارنة النسخ على المصدر نفسه.':!s.prompt?'أدخل تعليمات النسخة A قبل المقارنة.':!b?'اختر قالبًا للنسخة B.':!bReady?'أكمل تعليمات النسخة B أو ألغِ اختيارها.':!cReady?'أكمل تعليمات النسخة C أو ألغِ اختيارها.':busyConflict?'اختر قالبًا مختلفًا لكل نسخة.':compareWarnings.join(' ')||'كل نسخة تُرسل بطلب مستقل مع ثبات المصدر والبذرة وبقية الإعدادات.');
  $('generateCompare').textContent=c?'توليد مقارنة A/B/C':'توليد مقارنة A/B';
 }
 function applyPreset(id){if(locked)return;const preset=catalog.presets.find(p=>p.id===id);if(!preset)return;
  $('genStyle').value=id;$('genPrompt').value=preset.prompt;$('genMode').value=preset.mode;
  for(const key of Object.keys(catalog.controls))$('fluxControl_'+key).value='auto';
  for(const key of Object.keys(catalog.preserve))$('fluxPreserve_'+key).checked=true;
  if(preset.mode==='multi')$('genResolution').value='512';
  note(preset.description);changed();
 }
 function setCompareTemplate(letter){const preset=catalog.presets.find(item=>item.id===$(`compareStyle${letter}`).value);$(`comparePrompt${letter}`).value=preset?.prompt||'';changed();}
 function compareVariants(){return ['B','C'].map(letter=>{const preset=catalog.presets.find(item=>item.id===$(`compareStyle${letter}`).value);return preset?{letter,style:preset.id,title:preset.title,prompt:$(`comparePrompt${letter}`).value.trim()}:null;}).filter(item=>item&&item.prompt);}
 function setCompareStatus(message){compareStatus=message;refreshPrompt();}
 function renderLibrary(){
  const query=$('librarySearch').value.trim().toLocaleLowerCase(),category=$('libraryCategory').value;
  $('libraryCards').replaceChildren();let count=0;
  const ordered=[...catalog.presets].sort((a,b)=>categoryOrder.indexOf(a.category)-categoryOrder.indexOf(b.category));
  for(const preset of ordered){if(category&&category!==preset.category)continue;if(query&&!`${preset.title} ${preset.description} ${preset.prompt}`.toLocaleLowerCase().includes(query))continue;
   const card=element('button',undefined,'prompt-card');card.type='button';const summary=guidance(preset.category);card.append(element('small',preset.category),element('strong',preset.title),element('span',preset.description),element('span',`الغرض: ${summary.purpose}`),element('span',`قد يغيّر: ${summary.change}`),element('span',`يحاول الحفاظ على: ${summary.preserve}`),element('span',`الملاءمة: ${summary.fit}`));card.onclick=()=>{applyPreset(preset.id);$('promptLibrary').close();};$('libraryCards').append(card);count++;
  }
  $('libraryCount').textContent=count?`${count} برومبت جاهز قابل للتعديل`:'لا توجد نتائج مطابقة.';
 }
 function renderSaved(){
  $('savedPrompts').replaceChildren();
  saved.forEach((item,index)=>{const row=element('div',undefined,'saved-prompt'),button=element('button',item.title,'button secondary'),remove=element('button','حذف','button text');button.type=remove.type='button';
   button.onclick=()=>{if(locked)return;$('genStyle').value='custom';$('genPrompt').value=item.prompt.slice(0,4096);if(item.finalPrompt){$('genMode').value='edit';for(const key of Object.keys(catalog.controls))$('fluxControl_'+key).value='auto';for(const key of Object.keys(catalog.preserve))$('fluxPreserve_'+key).checked=false;references.splice(0,references.length);renderReferences();}note('تم تحميل البرومبت المحفوظ؛ راجع الصورة المصدر والإعدادات قبل التوليد.');changed();};
   remove.setAttribute('aria-label','حذف القالب '+item.title);remove.onclick=()=>{saved.splice(index,1);persistSaved();renderSaved();};row.append(button,remove);$('savedPrompts').append(row);
  });$('noSaved').hidden=!!saved.length;
 }
 function persistSaved(){try{localStorage.setItem(savedKey,JSON.stringify(saved));}catch{note('تعذر حفظ القالب في هذا المتصفح؛ يمكنك تنزيل الوصف.');}}
 function renderReferences(){
  $('referenceCards').replaceChildren();references.forEach((reference,index)=>{
   const card=element('div',undefined,'reference-card'),image=element('img'),body=element('div'),label=element('label',`المرجع ${index+2} · ${reference.name}`),select=element('select'),remove=element('button','إزالة','button text');
   image.src=reference.image;image.alt=`الصورة المرجعية ${index+2}`;select.id='referenceRole_'+index;label.htmlFor=select.id;
   for(const [value,rule]of Object.entries(catalog.roles)){const option=element('option',rule[0]);option.value=value;select.append(option);}select.value=reference.role;select.onchange=()=>{reference.role=select.value;changed();};
   remove.type='button';remove.setAttribute('aria-label',`إزالة المرجع ${index+2}`);remove.onclick=()=>{if(locked)return;references.splice(index,1);renderReferences();changed();};body.append(label,select);card.append(image,body,remove);$('referenceCards').append(card);
  });$('referenceEmpty').hidden=!!references.length;$('referenceCounter').textContent=`${references.length} / 2 إضافية`;
 }
 $('genStyle').onchange=()=>applyPreset($('genStyle').value);
 $('compareStyleB').onchange=()=>setCompareTemplate('B');$('compareStyleC').onchange=()=>setCompareTemplate('C');
 for(const id of ['comparePromptB','comparePromptC'])$(id).addEventListener('input',changed);
 for(const id of ['genMode','genAspect','genResolution','genSeed','genPrompt'])$(id).addEventListener('input',changed);
 $('openPromptLibrary').onclick=()=>{renderLibrary();renderSaved();$('promptLibrary').showModal();$('librarySearch').focus();};
 $('closePromptLibrary').onclick=()=>$('promptLibrary').close();$('librarySearch').oninput=renderLibrary;$('libraryCategory').onchange=renderLibrary;
  $('savePrompt').onclick=()=>{if(locked)return;const title=$('savedTitle').value.trim(),prompt=$('effectivePrompt').value.trim();if(!title||!prompt){note('اكتب اسمًا للبرومبت النهائي وتأكد من وجود نص قبل الحفظ.');return;}if(settings().mode!=='edit'||references.length){note('لحفظ البرومبت النهائي أوقف وضع المراجع المتعددة؛ تُحفظ التعليمات دون الصور.');return;}saved=[{title:title.slice(0,60),prompt,finalPrompt:true},...saved.filter(v=>v.title!==title)].slice(0,20);persistSaved();renderSaved();note('حُفظ البرومبت النهائي محليًا في هذا المتصفح؛ الصور المصدرية لا تُحفظ.');};
 $('copyPrompt').onclick=async()=>{try{await navigator.clipboard.writeText($('effectivePrompt').value);note('نُسخ الوصف النهائي.');}catch{note('تعذر النسخ التلقائي؛ حدد النص داخل الوصف النهائي أو نزّله.');}};
 $('downloadPrompt').onclick=()=>{const url=URL.createObjectURL(new Blob([$('effectivePrompt').value],{type:'text/plain;charset=utf-8'}));download(url,'flux-prompt.txt');setTimeout(()=>URL.revokeObjectURL(url),1000);};
 $('randomSeed').onclick=()=>{if(locked)return;const seed=new Uint32Array(1);crypto.getRandomValues(seed);$('genSeed').value=seed[0]%2147483648;changed();};
 $('referenceFiles').onchange=async()=>{
  if(locked||uploading)return;const files=[...$('referenceFiles').files];if(files.length+references.length>2){note('الحد الأقصى مرجعان إضافيان؛ أزل مرجعًا أو اختر صورًا أقل.');$('referenceFiles').value='';return;}
  uploading=true;onChange();try{for(const file of files){if(file.size>15_000_000)throw Error('الصورة المرجعية أكبر من 15 ميغابايت.');const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('تعذر فتح المرجع.'));reader.readAsDataURL(file);});const result=await api('/api/import',{image:encoded});references.push({image:result.image,role:'style',name:file.name});}note('أُضيفت المراجع محليًا. راجع دور كل صورة قبل التوليد.');}catch(error){note(error.message);}finally{uploading=false;$('referenceFiles').value='';renderReferences();changed();}
 };
 function addHistory(result,request){if(!request.reviewStatus)request.reviewStatus='pending';history.unshift({result,request});if(history.length>8)history.pop();renderHistory();}
 function renderHistory(){
  $('generationHistory').hidden=!history.length;$('historyCards').replaceChildren();
  history.forEach(({result,request},index)=>{const card=element('article',undefined,'history-card'),image=element('img'),base=catalog.presets.find(p=>p.id===request.style)?.title||'نتيجة',title=element('strong',request.variantLabel||base),meta=element('small',`${result.width}×${result.height} · بذرة ${result.seed}`),buttons=element('div',undefined,'button-row'),save=element('button','PNG','button secondary'),use=element('button','مراجعة هذه النسخة','button secondary'),details=element('details',undefined,'history-details'),summary=element('summary','التفاصيل'),prompt=element('pre',result.effectivePrompt||request.prompt||'تعليمات غير متاحة'),source=element('img'),settings=element('small',`${request.mode||'edit'} · ${request.resolution||''}px · ${request.aspect||''} · البذرة ${request.seed||result.seed}${request.comparisonId?` · مقارنة ${request.comparisonId}`:''}`),statusLabel=element('label','حالة المراجعة لهذه النسخة'),status=element('select'),statusHelp=element('small','للمقارنة فقط؛ لا يعتمد الصورة للمسارات.');
   prompt.dir='auto';status.id=`historyReviewStatus${index}`;statusLabel.htmlFor=status.id;for(const [value,label]of [['pending','قيد المراجعة'],['accepted','مقبولة بصريًا'],['rejected','مرفوضة'],['revise','تحتاج تعديلًا']]){const option=element('option',label);option.value=value;status.append(option);}status.value=request.reviewStatus||'pending';status.onchange=()=>{request.reviewStatus=status.value;};
   image.src=result.image;image.alt=`نتيجة محفوظة في الجلسة: ${title.textContent}`;source.src=request.sourceImage||'';source.alt='الصورة المصدر المستخدمة لهذه النتيجة';source.hidden=!request.sourceImage;save.type=use.type='button';save.onclick=()=>download(result.image,`flux-${index+1}.png`);use.disabled=locked;use.onclick=()=>{if(!locked)onUseHistory(result);};use.classList.add('history-use');buttons.append(use);details.append(summary,meta,statusLabel,status,statusHelp,source,settings,prompt,save);card.append(image,title,details,buttons);$('historyCards').append(card);
  });
 }
 function render({busy,source,stage=0,processing=false}){locked=busy||uploading;sourceForCompare=source;refreshPrompt();$('generationHistory').hidden=stage!==0||!history.length;$('generationFields').disabled=$('advancedFields').disabled=locked;$('referenceFiles').disabled=locked||references.length>=2;for(const el of document.querySelectorAll('.history-use'))el.disabled=locked||processing;
  const s=settings();return !locked&&(s.mode==='generate'||!!source)&&(s.mode!=='multi'||references.length>0)&&(s.style!=='custom'||!!s.prompt);
 }
 const drawer=$('advancedDrawer'),shut=()=>{drawer.open=false;drawer.querySelector('summary').focus();};
 $('closeDrawer').onclick=shut;drawer.onkeydown=event=>{if(event.key==='Escape'&&drawer.open){event.stopPropagation();shut();}};
 renderReferences();renderSaved();$('genStyle').value='ink';$('genPrompt').value=catalog.presets.find(p=>p.id==='ink').prompt;refreshPrompt();
 return {settings,render,addHistory,catalog,compareVariants,setCompareStatus};
}
