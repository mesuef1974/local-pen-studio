import {composePrompt} from './flux-prompts.js';
const $=id=>document.getElementById(id);
const element=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};

export async function createFluxControls({api,onChange,onUseHistory,download}){
 const response=await fetch('/flux-catalog.json');
 if(!response.ok)throw Error('تعذر تحميل مكتبة البرومبتات. حدّث الصفحة بعد تشغيل السيرفر الجديد.');
 const catalog=await response.json(),references=[],history=[];
 let locked=false,uploading=false;
 const savedKey='flux-professional-prompts-v1';
 let saved=[];try{const data=JSON.parse(localStorage.getItem(savedKey)||'[]');if(Array.isArray(data))saved=data.filter(v=>typeof v.title==='string'&&typeof v.prompt==='string').slice(0,20);}catch{}
 const note=text=>{$('fluxNote').textContent=text;};
 const changed=()=>{refreshPrompt();onChange();};
 for(const category of [...new Set(catalog.presets.map(p=>p.category))]){
  const group=element('optgroup');group.label=category;
  for(const preset of catalog.presets.filter(p=>p.category===category)){const option=element('option',preset.title);option.value=preset.id;group.append(option);}
  $('genStyle').append(group);
  const option=element('option',category);option.value=category;$('libraryCategory').append(option);
 }
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
 function refreshPrompt(){const s=settings();$('effectivePrompt').value=composePrompt(catalog,s);$('promptCount').textContent=`${$('effectivePrompt').value.length} حرف · يُتحقق من حد 512 رمزًا قبل التوليد`;$('referencePanel').hidden=s.mode!=='multi';$('fluxPreserveSection').hidden=s.mode==='generate';$('textModeHint').hidden=s.mode!=='generate';}
 function applyPreset(id){if(locked)return;const preset=catalog.presets.find(p=>p.id===id);if(!preset)return;
  $('genStyle').value=id;$('genPrompt').value=preset.prompt;$('genMode').value=preset.mode;
  for(const key of Object.keys(catalog.controls))$('fluxControl_'+key).value='auto';
  for(const key of Object.keys(catalog.preserve))$('fluxPreserve_'+key).checked=true;
  if(preset.mode==='multi')$('genResolution').value='512';
  note(preset.description);changed();
 }
 function renderLibrary(){
  const query=$('librarySearch').value.trim().toLocaleLowerCase(),category=$('libraryCategory').value;
  $('libraryCards').replaceChildren();let count=0;
  for(const preset of catalog.presets){if(category&&category!==preset.category)continue;if(query&&!`${preset.title} ${preset.description} ${preset.prompt}`.toLocaleLowerCase().includes(query))continue;
   const card=element('button',undefined,'prompt-card');card.type='button';card.append(element('small',preset.category),element('strong',preset.title),element('span',preset.description));card.onclick=()=>{applyPreset(preset.id);$('promptLibrary').close();};$('libraryCards').append(card);count++;
  }
  $('libraryCount').textContent=count?`${count} برومبت جاهز قابل للتعديل`:'لا توجد نتائج مطابقة.';
 }
 function renderSaved(){
  $('savedPrompts').replaceChildren();
  saved.forEach((item,index)=>{const row=element('div',undefined,'saved-prompt'),button=element('button',item.title,'button secondary'),remove=element('button','حذف','button text');button.type=remove.type='button';
   button.onclick=()=>{if(locked)return;$('genStyle').value='custom';$('genPrompt').value=item.prompt.slice(0,1200);note('تم تحميل قالبك المحفوظ.');changed();};
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
 for(const id of ['genMode','genAspect','genResolution','genSeed','genPrompt'])$(id).addEventListener('input',changed);
 $('openPromptLibrary').onclick=()=>{renderLibrary();renderSaved();$('promptLibrary').showModal();$('librarySearch').focus();};
 $('closePromptLibrary').onclick=()=>$('promptLibrary').close();$('librarySearch').oninput=renderLibrary;$('libraryCategory').onchange=renderLibrary;
 $('savePrompt').onclick=()=>{if(locked)return;const title=$('savedTitle').value.trim(),prompt=$('genPrompt').value.trim();if(!title||!prompt){note('اكتب اسم القالب ووصفًا قبل الحفظ.');return;}saved=[{title:title.slice(0,60),prompt},...saved.filter(v=>v.title!==title)].slice(0,20);persistSaved();note('حُفظ نص القالب محليًا في هذا المتصفح؛ لم تُحفظ الصور.');};
 $('copyPrompt').onclick=async()=>{try{await navigator.clipboard.writeText($('effectivePrompt').value);note('نُسخ الوصف النهائي.');}catch{note('تعذر النسخ التلقائي؛ حدد النص داخل الوصف النهائي أو نزّله.');}};
 $('downloadPrompt').onclick=()=>{const url=URL.createObjectURL(new Blob([$('effectivePrompt').value],{type:'text/plain;charset=utf-8'}));download(url,'flux-prompt.txt');setTimeout(()=>URL.revokeObjectURL(url),1000);};
 $('randomSeed').onclick=()=>{if(locked)return;const seed=new Uint32Array(1);crypto.getRandomValues(seed);$('genSeed').value=seed[0]%2147483648;changed();};
 $('referenceFiles').onchange=async()=>{
  if(locked||uploading)return;const files=[...$('referenceFiles').files];if(files.length+references.length>2){note('الحد الأقصى مرجعان إضافيان؛ أزل مرجعًا أو اختر صورًا أقل.');$('referenceFiles').value='';return;}
  uploading=true;onChange();try{for(const file of files){if(file.size>15_000_000)throw Error('الصورة المرجعية أكبر من 15 ميغابايت.');const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('تعذر فتح المرجع.'));reader.readAsDataURL(file);});const result=await api('/api/import',{image:encoded});references.push({image:result.image,role:'style',name:file.name});}note('أُضيفت المراجع محليًا. راجع دور كل صورة قبل التوليد.');}catch(error){note(error.message);}finally{uploading=false;$('referenceFiles').value='';renderReferences();changed();}
 };
 function addHistory(result,request){history.unshift({result,request});if(history.length>8)history.pop();renderHistory();}
 function renderHistory(){
  $('generationHistory').hidden=!history.length;$('historyCards').replaceChildren();
  history.forEach(({result,request},index)=>{const card=element('article',undefined,'history-card'),image=element('img'),title=element('strong',catalog.presets.find(p=>p.id===request.style)?.title||'نتيجة'),meta=element('small',`${result.width}×${result.height} · بذرة ${result.seed}`),buttons=element('div',undefined,'button-row'),save=element('button','PNG','button secondary'),use=element('button','مراجعة هذه النسخة','button secondary');
   image.src=result.image;image.alt=`نتيجة محفوظة في الجلسة: ${title.textContent}`;save.type=use.type='button';save.onclick=()=>download(result.image,`flux-${index+1}.png`);use.disabled=locked;use.onclick=()=>{if(!locked)onUseHistory(result);};use.classList.add('history-use');buttons.append(save,use);card.append(image,title,meta,buttons);$('historyCards').append(card);
  });
 }
 function render({busy,source,stage=0,processing=false}){locked=busy||uploading;refreshPrompt();$('generationHistory').hidden=stage!==0||!history.length;$('generationFields').disabled=locked;$('referenceFiles').disabled=locked||references.length>=2;for(const el of document.querySelectorAll('.history-use'))el.disabled=locked||processing;
  const s=settings();return !locked&&(s.mode==='generate'||!!source)&&(s.mode!=='multi'||references.length>0)&&(s.style!=='custom'||!!s.prompt);
 }
 renderReferences();renderSaved();$('genStyle').value='ink';$('genPrompt').value=catalog.presets.find(p=>p.id==='ink').prompt;refreshPrompt();
 return {settings,render,addHistory,catalog};
}
