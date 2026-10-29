const $=id=>document.getElementById(id);
let activeStep='source',activeView='compare';
let modelApproved=false;
const steps=['source','paths'];
export function fitImages(){
 const zoom=Number($('zoom').value)/100;
 for(const id of ['original','result']){
  const image=$(id);if(image.hidden||!image.naturalWidth)continue;
  const viewport=image.closest('.image-viewport');if(!viewport?.clientHeight)continue;
  const css=getComputedStyle(viewport),spaceX=parseFloat(css.paddingLeft)+parseFloat(css.paddingRight),spaceY=parseFloat(css.paddingTop)+parseFloat(css.paddingBottom);
  const width=Math.max(1,Math.min(viewport.clientWidth-spaceX,(viewport.clientHeight-spaceY-16)*image.naturalWidth/image.naturalHeight));
  const target=id==='result'?image.parentElement:image;target.style.width=(width*zoom)+'px';if(id==='result'){image.style.width='100%';$('modelProgress').style.width=(width*zoom)+'px';}
 }
 const canvas=$('pathCanvas'),viewport=canvas.parentElement;
 if(viewport.clientHeight){const css=getComputedStyle(viewport),paddingX=parseFloat(css.paddingLeft)+parseFloat(css.paddingRight),paddingY=parseFloat(css.paddingTop)+parseFloat(css.paddingBottom);canvas.style.width=Math.max(1,Math.min(viewport.clientWidth-paddingX,(viewport.clientHeight-paddingY)*canvas.width/canvas.height))*zoom+'px';}
 if($('pathProgress'))$('pathProgress').style.width=canvas.style.width;
 $('zoomValue').textContent=$('zoom').value+'%';
}
export function setActivity(phase='info'){
 document.body.dataset.activity=phase;
 const labels={empty:'بانتظار صورة',busy:'جارٍ المعالجة',ready:'المعاينة محدثة',error:'راجع الإعدادات',pending:'تحديث مطلوب',info:'محلي'};
 $('activityBadge').querySelector('span').textContent=labels[phase]||'محلي';
 $('editorPreview').setAttribute('aria-busy',String(phase==='busy'));if(phase==='busy')$('nextStep').disabled=true;
}
export function setSummary(count=null,ink=0,seconds=0,available=false){
 $('summaryStrokes').textContent=count===null?'—':count.toLocaleString('ar-u-nu-latn');
 $('summaryInk').textContent=count===null?'—':ink.toFixed(2)+' م';
 const total=Math.round(seconds);$('summaryTime').textContent=count===null?'—':Math.floor(total/60)+':'+String(total%60).padStart(2,'0');
 $('pathEmpty').hidden=available;$('pathCanvas').hidden=!available;
 if(!available&&$('pathLiveStats'))$('pathLiveStats').textContent='حدّد المسارات لمراجعة عدد الضربات وزمن الحركة.';
 $('pathEmpty').textContent=count===0?'لا توجد خطوط بهذه الإعدادات. خفّف التنظيف أو غيّر العتبة.':'ستظهر مسارات الصورة هنا بعد المعالجة';
 requestAnimationFrame(fitImages);
}
function updateAvailability(){
 const hasSource=!$('original').hidden&&Boolean($('original').getAttribute('src'));
 const hasResult=!$('result').hidden&&Boolean($('result').getAttribute('src'))&&document.body.dataset.resultStale!=='true';
 $('emptyState').hidden=hasSource;
 $('imageViews').hidden=!hasSource||activeView==='paths';
 $('pathView').hidden=activeView!=='paths';
 $('nextStep').disabled=!hasResult||document.body.dataset.activity!=='ready';
 requestAnimationFrame(fitImages);
}
function setView(view){
 activeView=view;$('imageViews').setAttribute('aria-labelledby','view-'+(view==='result'?'result':'compare'));document.querySelector('.preview-stage').dataset.view=view;
 document.querySelectorAll('[data-view][role=tab]').forEach(button=>{const selected=button.dataset.view===view;button.setAttribute('aria-selected',selected);button.tabIndex=selected?0:-1;});
 $('canvasHint').textContent={compare:'مدخل النموذج والرسم الخطي جنبًا إلى جنب',result:'كبّر الرسم لمراجعة الملامح والتعديل بالفرشاة',paths:'مسارات القلم على A4 · انقر خطًا لاستبعاده أو استعادته'}[view];
 $('usePaths').hidden=activeStep!=='paths';$('nextStep').hidden=activeStep==='paths';
 updateAvailability();
}
function setStep(step){
 if(step==='paths'&&!modelApproved)return;
 if(step==='paths'&&$('brushMode').value!=='none'){$('brushMode').value='none';$('brushMode').dispatchEvent(new Event('change'));}
 activeStep=step;document.body.dataset.stage=step;$('run').textContent=step==='paths'?'تحديث المسارات':'تحديث النموذج';$('auto').parentElement.lastChild.textContent=step==='paths'?' تحديث المسارات تلقائيًا':' تشغيل النموذج تلقائيًا';
 document.querySelectorAll('[data-step]').forEach(button=>{const selected=button.dataset.step===step;button.setAttribute('aria-selected',selected);button.tabIndex=selected?0:-1;$('panel-'+button.dataset.step).hidden=!selected;});
 document.querySelector('.panel-scroll').scrollTop=0;
 $('nextStep').textContent='اعتماد الصورة وتحديد مسار القلم ←';
 setView(step==='paths'?'paths':'compare');
}
function rovingTabs(container,selector,onSelect){
 container.addEventListener('keydown',event=>{
  const buttons=[...container.querySelectorAll(selector)].filter(button=>!button.disabled),index=buttons.indexOf(document.activeElement);if(index<0)return;
  let next=index;if(event.key==='ArrowLeft')next=(index+1)%buttons.length;else if(event.key==='ArrowRight')next=(index-1+buttons.length)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;
  event.preventDefault();onSelect(buttons[next]);buttons[next].focus();
 });
}
export function initLayout(){
 $('mobileToolsToggle').onclick=()=>{const open=!document.body.classList.contains('tools-open');document.body.classList.toggle('tools-open',open);$('mobileToolsToggle').setAttribute('aria-expanded',open);$('mobileToolsToggle').textContent=open?'إغلاق':'الأدوات';if(open)document.querySelector('.step-tabs [aria-selected=true]').focus();};
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('tools-open')){$('mobileToolsToggle').click();$('mobileToolsToggle').focus();}});
 document.querySelectorAll('[data-step]').forEach(button=>button.onclick=()=>setStep(button.dataset.step));
 document.querySelectorAll('[data-view][role=tab]').forEach(button=>button.onclick=()=>button.dataset.view==='paths'?setStep('paths'):setView(button.dataset.view));
 rovingTabs(document.querySelector('.step-tabs'),'[data-step]',button=>setStep(button.dataset.step));
 rovingTabs(document.querySelector('.view-tabs'),'[data-view]',button=>button.dataset.view==='paths'?setStep('paths'):setView(button.dataset.view));
 $('nextStep').onclick=()=>{if($('nextStep').disabled)return;modelApproved=true;$('step-paths').disabled=false;$('view-paths').disabled=false;setStep('paths');document.dispatchEvent(new CustomEvent('model-image-approved'));};
 document.addEventListener('model-result-invalid',()=>{modelApproved=false;$('step-paths').disabled=true;$('view-paths').disabled=true;$('nextStep').disabled=true;if(activeStep==='paths')setStep('source');});
 document.addEventListener('model-result-ready',updateAvailability);
 $('view-paths').disabled=true;
 $('brushDetails').addEventListener('toggle',()=>{if($('brushDetails').open&&activeStep==='source')setView('result');else if($('brushMode').value!=='none'){$('brushMode').value='none';$('brushMode').dispatchEvent(new Event('change'));}});
 $('emptySample').onclick=()=>$('sample').click();
 $('fitView').onclick=()=>{$('zoom').value=100;fitImages();};
 $('showDiagnostics').onclick=()=>{const expanded=$('diagnostics').hidden;$('diagnostics').hidden=!expanded;$('showDiagnostics').setAttribute('aria-expanded',expanded);requestAnimationFrame(fitImages);};
 for(const id of ['original','result'])$(id).addEventListener('load',updateAvailability);
 new MutationObserver(updateAvailability).observe($('original'),{attributes:true,attributeFilter:['hidden','src']});
 new MutationObserver(updateAvailability).observe($('result'),{attributes:true,attributeFilter:['hidden','src']});
 const observer=new ResizeObserver(()=>requestAnimationFrame(fitImages));document.querySelectorAll('.image-viewport,.pen-preview').forEach(el=>observer.observe(el));
 for(const button of document.querySelectorAll('.brush-choice'))button.onclick=()=>{$('brushMode').value=button.dataset.mode;$('brushMode').dispatchEvent(new Event('change'));};
 $('brushMode').addEventListener('change',()=>{const mode=$('brushMode').value;document.querySelectorAll('.brush-choice').forEach(button=>button.setAttribute('aria-pressed',button.dataset.mode===mode));$('brushIndicator').textContent={none:'الفرشاة متوقفة',protect:'فرشاة الحماية · أحمر',lighten:'فرشاة التخفيف · أخضر',erase:'فرشاة المحو · أزرق',unmask:'إزالة القناع'}[mode];$('localReduction').disabled=mode!=='lighten';});
 const presets=['presetNeutral','presetPortrait','presetQuick'];for(const id of presets){$(id).title=$(id).querySelector('small').textContent;$(id).addEventListener('click',()=>{presets.forEach(other=>$(other).setAttribute('aria-pressed',other===id));$('presetDescription').textContent=$(id).querySelector('small').textContent;});}
 for(const id of ['strength','weak','specks','weight','binary','threshold'])$(id).addEventListener('input',()=>{presets.forEach(other=>$(other).setAttribute('aria-pressed','false'));$('presetDescription').textContent='إعدادات مخصصة — راقب الملامح أثناء التعديل.';});
 $('resetTools').addEventListener('click',()=>{presets.forEach(id=>$(id).setAttribute('aria-pressed',id==='presetNeutral'));$('presetDescription').textContent=$('presetNeutral').querySelector('small').textContent;});
 document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&!$('run').disabled){event.preventDefault();$('run').click();}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'&&activeStep==='source'&&$('brushDetails').open&&!/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)&&!$('undoMask').disabled){event.preventDefault();$('undoMask').click();}});
 // Keep zoomed comparisons at matching relative scroll positions.
 const viewports=[...document.querySelectorAll('.image-viewport')];let synchronizing=false;
 for(const viewport of viewports)viewport.addEventListener('scroll',()=>{if(synchronizing||activeView!=='compare')return;synchronizing=true;const other=viewports.find(el=>el!==viewport);other.scrollTop=viewport.scrollTop/Math.max(1,viewport.scrollHeight-viewport.clientHeight)*Math.max(0,other.scrollHeight-other.clientHeight);other.scrollLeft=viewport.scrollLeft/Math.max(1,viewport.scrollWidth-viewport.clientWidth)*Math.max(0,other.scrollWidth-other.clientWidth);requestAnimationFrame(()=>synchronizing=false);});
 setStep('source');setSummary();$('brushMode').dispatchEvent(new Event('change'));
}
