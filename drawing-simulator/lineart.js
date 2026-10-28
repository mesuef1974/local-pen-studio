import {createImageEditor} from './image-editor.js';
import {$,setupTools} from './lineart-tools.js';
import {setActivity,setSummary} from './lineart-layout.js';
let source='',raw='',result='',busy=false,revision=0,timer,pending=false,cacheKey='',sourceVersion=0,metrics=null,paths=[],deleted=new Set(),pathRevision=0;
let selectedPath=-1,pathHistory=[],pathTimer;
function pathLength(p){let n=0;for(let k=1;k<p.length;k++)n+=Math.hypot(p[k][0]-p[k-1][0],p[k][1]-p[k-1][1]);return n;}
function orderedPaths(){
 const items=paths.map((p,i)=>({p,i})).filter(v=>!deleted.has(v.i)),mode=$('pathOrder').value;
 if(mode==='longest')return items.sort((a,b)=>pathLength(b.p)-pathLength(a.p));
 if(mode!=='nearest'||items.length<2)return items;
 const remaining=items.slice(),ordered=[];let last=[0,0];
 while(remaining.length){let best=0,reverse=false,distance=Infinity;remaining.forEach((v,i)=>{for(const end of [0,v.p.length-1]){const q=v.p[end],d=(q[0]-last[0])**2+(q[1]-last[1])**2;if(d<distance){distance=d;best=i;reverse=end!==0;}}});const v=remaining.splice(best,1)[0];ordered.push({i:v.i,p:reverse?v.p.slice().reverse():v.p});last=ordered.at(-1).p.at(-1);}
 // Nearest-neighbor is a heuristic: keep original if it would travel farther.
 const travel=list=>{let n=0,last=[0,0];for(const v of list){n+=Math.hypot(v.p[0][0]-last[0],v.p[0][1]-last[1]);last=v.p.at(-1);}return n;};
 return travel(ordered)<=travel(items)?ordered:items;
}
function rememberPathEdit(){pathHistory.push(new Set(deleted));if(pathHistory.length>30)pathHistory.shift();}
function editorAvailability(){if($('editInput'))$('editInput').disabled=!source||busy;if($('editResult'))$('editResult').disabled=!result||busy||document.body.dataset.resultStale==='true';}
function modelProgress(completed){editorAvailability();const bar=$('modelProgress');bar.hidden=!source;bar.max=3;bar.value=completed;bar.setAttribute('aria-valuetext',`${completed} من 3 مراحل مكتملة؛ لا يمثل الزمن المتبقي`);}
const status=(text,phase='info')=>{$('status').textContent=text;setActivity(phase);};
const inputDefaults={exposure:0,brightness:0,gamma:100,shadows:0,highlights:0,blacks:0,whites:0,tonalContrast:100,contrast:0,saturation:100,warmth:0,sharpness:0,denoise:0,cropX:0,cropY:0,cropW:100,cropH:100};
const preIds=Object.keys(inputDefaults);
let inputPreviewTimer,preparedKey='',preparedInput=null,modelRetryTimer,modelRetries=0;
const inputKey=()=>JSON.stringify([sourceVersion,settings(preIds)]);
const modelKey=()=>JSON.stringify([sourceVersion,'realistic',$('resolution').value,settings(preIds)]);
async function prepareInput(){const key=inputKey();if(key===preparedKey&&preparedInput)return preparedInput;const prepared=await api('/api/lineart/process',{action:'pre',image:source,settings:settings(preIds)});if(key!==inputKey())return null;preparedKey=key;preparedInput=prepared;modelProgress(cacheKey===modelKey()&&raw?2:1);$('original').src=prepared.image;const clipped=prepared.newlyClippedHighlightsPercent||0;$('inputWarning').hidden=clipped<.5;$('inputWarning').textContent=`التعديلات دفعت ${clipped.toFixed(1)}٪ من الصورة إلى الأبيض شبه الكامل. خفّض التعريض أو السطوع أو الأبيض إذا اختفت تفاصيل الملامح.`;return prepared;}
function previewInput(){clearTimeout(inputPreviewTimer);const serial=revision;inputPreviewTimer=setTimeout(()=>{prepareInput(serial).catch(e=>{if(serial===revision)status(e.message,'error');});},120);}
function resetInputFields(){for(const [id,value]of Object.entries(inputDefaults)){$(id).value=value;if($(id+'Value'))$(id+'Value').textContent=value;}}
const postIds=['strength','threshold','binary','weak','specks','weight','localReduction'];
const brushes=setupTools(()=>invalidate(false));
for(const [id,values]of Object.entries({presetNeutral:[0,0,0,2],presetPortrait:[10,5,160,6],presetQuick:[20,10,120,8]}))$(id).onclick=()=>{const [weak,specks,threshold,minimum]=values;for(const [field,value]of Object.entries({weak,specks,strength:100,weight:0})){$(field).value=value;$(field+'Value').textContent=value;}$('binary').checked=false;$('threshold').disabled=true;$('pathThreshold').value=threshold;$('pathMinimum').value=minimum;$('spurLength').value=0;invalidate();};
const settings=ids=>Object.fromEntries(ids.map(id=>[id,$(id).type==='checkbox'?$(id).checked:Number($(id).value)]));
async function api(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok||data.error){const error=Error(data.error||'تعذرت المعالجة المحلية.');error.status=response.status;throw error;}return data;}
function disableResult(){editorAvailability();document.body.dataset.resultStale='true';$('resultNotice').hidden=$('result').hidden;$('resultNotice').textContent='رسم سابق لا يطابق الإعدادات الحالية؛ انتظر التحديث أو اضغط تحديث النموذج.';document.dispatchEvent(new CustomEvent('model-result-invalid'));result='';$('editResult').disabled=true;$('download').disabled=true;disablePaths();}
function disablePaths(){document.dispatchEvent(new CustomEvent('pen-paths-invalid'));pathRevision++;$('pathProgress').hidden=true;clearTimeout(pathTimer);paths=[];deleted.clear();selectedPath=-1;pathHistory=[];$('undoPathEdit').disabled=true;$('deleteSelectedPath').disabled=true;$('pathSelection').textContent='لم يُحدد خط.';setSummary();for(const id of ['downloadSvg','usePaths','restorePaths','previewPaths'])$(id).disabled=true;$('pathStats').textContent='المسارات تحتاج تحديثًا بعد تغيير الصورة أو الإعدادات.';const c=$('pathCanvas');c.getContext('2d').clearRect(0,0,c.width,c.height);}
function invalidate(pre=false){revision++;clearTimeout(modelRetryTimer);modelRetries=0;modelProgress(cacheKey===modelKey()&&raw?2:0);disableResult();if(pre){cacheKey='';preparedKey='';brushes.clear();if(source)previewInput();}if(source){status($('auto').checked?'الإعدادات تغيرت؛ جارٍ تحديث المعاينة…':'الإعدادات تغيرت؛ اضغط تحديث النموذج.','pending');clearTimeout(timer);if($('auto').checked)timer=setTimeout(run,450);}}
async function load(url,name="\u0635\u0648\u0631\u0629 \u062c\u062f\u064a\u062f\u0629",preserve=false){if(!preserve){const im=new Image();im.src=url;await im.decode();const c=document.createElement('canvas'),s=Math.min(1,2000/Math.max(im.width,im.height));c.width=Math.round(im.width*s);c.height=Math.round(im.height*s);const ctx=c.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(im,0,0,c.width,c.height);source=c.toDataURL('image/png');} $('fileName').textContent=name;sourceVersion++;raw='';$('original').src=source;$('original').hidden=false;$('result').hidden=true;$('run').disabled=false;editorAvailability();resetInputFields();invalidate(true);}
async function handleFile(file){if(!file)return;if(file.size>12000000){status('الحد الأقصى 12 MB.','error');return;}const url=URL.createObjectURL(file);try{await load(url,file.name);}catch{status('تعذر قراءة الصورة.','error');}finally{URL.revokeObjectURL(url);}}
$('file').onchange=()=>handleFile($('file').files[0]);
$('sample').onclick=()=>load('/photo-lineart-comparison/original.png','بورتريه تجريبي').catch(()=>status('تعذر تحميل الصورة التجريبية.','error'));
for(const type of ['dragenter','dragover'])$('dropZone').addEventListener(type,event=>{event.preventDefault();$('dropZone').classList.add('dragging');});
for(const type of ['dragleave','drop'])$('dropZone').addEventListener(type,event=>{event.preventDefault();$('dropZone').classList.remove('dragging');if(type==='drop')handleFile(event.dataTransfer.files[0]);});
for(const id of [...preIds,'resolution',...postIds])$(id).addEventListener('input',()=>{if($(id+'Value'))$(id+'Value').textContent=$(id).value+(id==='strength'?'%':'');$('threshold').disabled=!$('binary').checked;invalidate(preIds.includes(id));});
$('auto').onchange=()=>{clearTimeout(timer);if($('auto').checked)invalidate();};
async function run(){clearTimeout(timer);clearTimeout(modelRetryTimer);if(!source)return;if(busy){pending=true;return;}busy=true;pending=false;const serial=revision;$('run').disabled=true;try{
 const key=modelKey();const cached=key===cacheKey&&raw;modelProgress(cached?2:0);
 if(!cached){status('تجهيز الصورة وتشغيل النموذج على جهازك…','busy');const prepared=await prepareInput(serial);if(!prepared||serial!==revision)return;modelProgress(1);
 const data=await api('/api/lineart',{image:prepared.image,model:'realistic',resolution:Number($('resolution').value),strength:100,binary:false,threshold:180});if(key!==modelKey())return;
 modelProgress(2);modelRetries=0;raw=data.image;metrics=data;cacheKey=key;brushes.resize(data.width,data.height);$('original').src=prepared.image;}
 if(serial!==revision)return;
 status('تحديث الخطوط وتطبيق التعديلات الموضعية…','busy');const processed=await api('/api/lineart/process',{action:'post',image:raw,mask:brushes.url(),settings:settings(postIds)});if(serial!==revision)return;
 result=processed.image;modelProgress(3);document.body.dataset.resultStale='false';$('resultNotice').hidden=true;$('result').src=result;$('result').hidden=false;$('download').disabled=false;$('previewPaths').disabled=false;
 $('metrics').textContent=`النموذج الدقيق · ${metrics.width} × ${metrics.height} · استدلال ${metrics.seconds} ثانية · ${metrics.device} · ${metrics.edited?'رسم محرر يدويًا':cached?'إعادة استخدام خرج النموذج':'استدلال جديد'} · مكونات صغيرة قبل تطبيق الحماية ${processed.removedComponents} · بكسلات محمية ${processed.protectedPixels} · حبر ${processed.inkPixelsBefore} ← ${processed.inkPixelsAfter}`;
 editorAvailability();status('نتيجة النموذج جاهزة. اعتمد الصورة للانتقال إلى تحديد مسار القلم.','ready');document.dispatchEvent(new CustomEvent('model-result-ready'));
 }catch(e){if(serial===revision){if(e.status===429&&modelRetries<4){modelRetries++;status(`النموذج مشغول بطلب آخر. إعادة المحاولة تلقائيًا ${modelRetries}/4…`,'pending');modelRetryTimer=setTimeout(()=>{if(serial===revision)return run();},modelRetries*1000);}else status(e.message,'error');}}finally{busy=false;editorAvailability();$('run').disabled=false;if((pending||serial!==revision)&&$('auto').checked){clearTimeout(timer);timer=setTimeout(run,450);}}}
$('run').onclick=()=>document.body.dataset.stage==='paths'?previewPaths():run();
$('resetTools').onclick=()=>{for(const [id,value]of Object.entries({strength:100,threshold:180,weak:0,specks:0,weight:0,localReduction:65})){$(id).value=value;$(id+'Value').textContent=value;}$('binary').checked=false;$('threshold').disabled=true;brushes.clear();invalidate();};
function download(url,name){const a=document.createElement('a');a.href=url;a.download=name;a.click();}
$('download').onclick=()=>{if(result)download(result,'lineart-'+'realistic'+'.png');};
function send(image,geometry=null){try{sessionStorage.setItem('lineart-approved',image);sessionStorage.removeItem('lineart-paths-approved');if(geometry)sessionStorage.setItem('lineart-paths-approved',JSON.stringify(geometry));try{sessionStorage.setItem('lineart-model-draft',JSON.stringify({source,raw,result,metrics,pre:settings(preIds),post:settings(postIds),resolution:Number($('resolution').value),mask:brushes.url()}));}catch{sessionStorage.removeItem('lineart-model-draft');}location.href='/simulator.html';}catch{status('تعذر نقل الصورة؛ نزّلها ثم ارفعها في المرسم.','error');}}

function penMm(){return Math.max(.2,Math.min(1.2,Number($('pathPenWidth').value)||.3));}
function scaleMm(){return Math.min(180/Math.max(1,metrics.width-1),267/Math.max(1,metrics.height-1));}
async function previewPaths(){if(!result)return;$('pathThresholdValue').textContent=Number($('pathThreshold').value)?$('pathThreshold').value:'تلقائي · Otsu';clearTimeout(pathTimer);const job=++pathRevision;$('pathProgress').hidden=false;$('pathProgress').removeAttribute('value');for(const id of ['downloadSvg','usePaths','restorePaths'])$(id).disabled=true;$('pathStats').textContent='جارٍ تحديد مسارات القلم…';status('جارٍ تحديد مسارات القلم من الصورة المعتمدة…','busy');try{const tolerance=Number($('pathTolerance').value);if(!Number.isFinite(tolerance)||tolerance<0||tolerance>.3)throw Error('السماحية بين صفر و0.3 مم.');const data=await api('/api/paths',{image:result,lineMode:$('pathRepresentation').value,lineDenoise:0,minLength:Number($('pathMinimum').value),tolerance:Math.min(2.5,tolerance/scaleMm()),inkThreshold:Number($('pathThreshold').value),spurLength:Number($('spurLength').value),componentMin:Number($('pathComponentMin').value),junctionRouting:$('pathRouting').checked});if(job!==pathRevision)return;paths=data.paths;deleted.clear();selectedPath=-1;pathHistory=[];status('المسارات جاهزة. راجعها ثم صدّرها أو افتح المحاكاة.','ready');$('pathCanvas').width=data.width;$('pathCanvas').height=data.height;drawPaths();}catch(e){if(job===pathRevision){$('pathStats').textContent=e.message;$('pathLiveStats').textContent=e.message;status(e.message,'error');}}finally{if(job===pathRevision)$('pathProgress').hidden=true;}}
function drawPaths(){
 const c=$('pathCanvas'),ctx=c.getContext('2d'),scale=scaleMm(),ordered=orderedPaths();ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);
 let length=0,points=0,travel=0,last=[0,0];
 for(const {p} of ordered){length+=pathLength(p);points+=p.length;travel+=Math.hypot(p[0][0]-last[0],p[0][1]-last[1]);if($('pathShowTravel').checked){ctx.beginPath();ctx.moveTo(...last);ctx.lineTo(...p[0]);ctx.strokeStyle='#2563eb';ctx.lineWidth=.6/scale;ctx.setLineDash([3/scale,2/scale]);ctx.stroke();}last=p.at(-1);}
 paths.forEach((p,i)=>{if(deleted.has(i)&&!$('pathShowDeleted').checked)return;ctx.setLineDash(deleted.has(i)?[3,3]:[]);ctx.beginPath();p.forEach(([x,y],j)=>j?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.strokeStyle=i===selectedPath?'#2563eb':deleted.has(i)?'#dd9c9c':'#183c3b';ctx.lineWidth=(i===selectedPath?penMm()+.25:penMm())/scale;ctx.lineCap=ctx.lineJoin='round';ctx.stroke();});
 ctx.setLineDash([]);if($('pathShowStarts').checked)for(const {p} of ordered){ctx.beginPath();ctx.arc(...p[0],1/scale,0,Math.PI*2);ctx.fillStyle='#b45309';ctx.fill();}
 const count=ordered.length,speed=Math.min(200,Math.max(1,Number($('pathSpeed').value)||30)),travelSpeed=Math.min(300,Math.max(1,Number($('pathTravelSpeed').value)||80)),lift=Math.min(5,Math.max(0,Number($('pathLift').value)||0)),seconds=length*scale/speed+travel*scale/travelSpeed+count*lift;
 $('pathStats').textContent=`${count} ضربة · ${points} نقطة · حبر ${(length*scale/1000).toFixed(2)} م · انتقال ${(travel*scale/1000).toFixed(2)} م · مستبعد ${deleted.size} · نحو ${Math.round(seconds)} ثانية دون التسارع`;
 $('pathLiveStats').textContent=$('pathStats').textContent;
 $('pathSelection').textContent=selectedPath<0?'لم يُحدد خط.':`الخط ${selectedPath+1} · ${paths[selectedPath].length} نقطة · ${(pathLength(paths[selectedPath])*scale).toFixed(1)} مم`;
 $('deleteSelectedPath').disabled=selectedPath<0||deleted.has(selectedPath);$('undoPathEdit').disabled=!pathHistory.length;
 setSummary(count,length*scale/1000,seconds,paths.length>0);for(const id of ['downloadSvg','usePaths'])$(id).disabled=!count;$('restorePaths').disabled=!deleted.size;
}
$('previewPaths').onclick=previewPaths;
for(const id of ['pathRepresentation','pathThreshold','pathTolerance','spurLength','pathMinimum','pathComponentMin','pathRouting'])$(id).oninput=()=>{syncPathOptions();$('pathThresholdValue').textContent=Number($('pathThreshold').value)?$('pathThreshold').value:'تلقائي · Otsu';disablePaths();$('previewPaths').disabled=!result;clearTimeout(pathTimer);if(result&&$('auto').checked)pathTimer=setTimeout(previewPaths,450);else if(result)status('إعدادات المسارات تغيرت؛ اضغط تحديث المسارات.','pending');};
$('restorePaths').onclick=()=>{rememberPathEdit();deleted.clear();drawPaths();};
$('undoPathEdit').onclick=()=>{if(pathHistory.length){deleted=pathHistory.pop();drawPaths();}};
$('deleteSelectedPath').onclick=()=>{if(selectedPath>=0){rememberPathEdit();deleted.add(selectedPath);drawPaths();}};
for(const id of ['pathOrder','pathSpeed','pathTravelSpeed','pathLift','pathShowDeleted','pathShowTravel','pathShowStarts'])$(id).oninput=()=>{if(paths.length)drawPaths();};
$('pathCanvas').onclick=e=>{if(!paths.length)return;const c=$('pathCanvas'),r=c.getBoundingClientRect(),x=(e.clientX-r.left)*c.width/r.width,y=(e.clientY-r.top)*c.height/r.height;let best=-1,distance=8*c.width/r.width;paths.forEach((path,index)=>{if(deleted.has(index)&&!$('pathShowDeleted').checked)return;for(let k=1;k<path.length;k++){const a=path[k-1],b=path[k],dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1))),d=Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);if(d<distance){distance=d;best=index;}}});if(best>=0){selectedPath=best;if($('pathClickMode').value==='select'){drawPaths();return;}rememberPathEdit();if(deleted.has(best))deleted.delete(best);else deleted.add(best);drawPaths();}};
$('downloadSvg').onclick=()=>{const s=scaleMm(),ox=(210-(metrics.width-1)*s)/2,oy=(297-(metrics.height-1)*s)/2;const body=orderedPaths().map(v=>v.p).map(p=>`<path d="${p.map(([x,y],i)=>`${i?'L':'M'}${(x*s+ox).toFixed(3)},${(y*s+oy).toFixed(3)}`).join(' ')}"/>`).join('');const blob=new Blob([`<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297"><g fill="none" stroke="black" stroke-width="${penMm()}" stroke-linecap="round" stroke-linejoin="round">${body}</g></svg>`],{type:'image/svg+xml'}),url=URL.createObjectURL(blob);download(url,'selected-pen-paths.svg');setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('usePaths').onclick=()=>{const c=document.createElement('canvas');c.width=metrics.width;c.height=metrics.height;const ctx=c.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);ctx.strokeStyle='black';ctx.lineWidth=penMm()/scaleMm();ctx.lineJoin=ctx.lineCap='round';paths.forEach((p,i)=>{if(deleted.has(i))return;ctx.beginPath();p.forEach(([x,y],j)=>j?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();});send(c.toDataURL('image/png'),{width:c.width,height:c.height,lineMode:$('pathRepresentation').value,penWidthMm:penMm(),paths:orderedPaths().map(v=>v.p)});};

$('pathPenWidth').oninput=()=>{if(paths.length)drawPaths();};

document.addEventListener('model-image-approved',()=>previewPaths());
function syncPathOptions(){const copying=$('pathRepresentation').value==='ink';for(const id of ['pathTolerance','spurLength','pathMinimum'])$(id).disabled=copying;$('pathRouting').disabled=copying;$('pathTolerance').closest('.field').hidden=copying;$('spurLength').closest('details').hidden=copying;}
syncPathOptions();

// Restore the in-tab draft when returning from simulation; never rerun the model silently.
async function restoreDraft(){
 if(new URLSearchParams(location.search).get('resume')!=='1')return;
 try{const draft=JSON.parse(sessionStorage.getItem('lineart-model-draft')||'null');if(!draft||!draft.metrics||!draft.source?.startsWith('data:image/png;base64,')||!draft.raw?.startsWith('data:image/png;base64,')||!draft.result?.startsWith('data:image/png;base64,'))return;
 source=draft.source;raw=draft.raw;result=draft.result;metrics=draft.metrics;sourceVersion++;
 for(const [ids,values]of [[preIds,draft.pre],[postIds,draft.post]])for(const id of ids){if(typeof values?.[id]!==($(id).type==='checkbox'?'boolean':'number'))continue;if($(id).type==='checkbox')$(id).checked=values[id];else $(id).value=values[id];if($(id+'Value'))$(id+'Value').textContent=$(id).value+(id==='strength'?'%':'');}
 $('resolution').value=[512,768,1024].includes(draft.resolution)?draft.resolution:768;$('threshold').disabled=!$('binary').checked;
 const prepared=await api('/api/lineart/process',{action:'pre',image:source,settings:settings(preIds)});
 $('original').src=prepared.image;$('original').hidden=false;document.body.dataset.resultStale='false';$('resultNotice').hidden=true;$('result').src=result;$('result').hidden=false;$('fileName').textContent='الرسم المحفوظ من هذه الجلسة';brushes.resize(metrics.width,metrics.height);
 if(draft.mask?.startsWith('data:image/png;base64,')){const mask=new Image();mask.src=draft.mask;await mask.decode();brushes.mask.getContext('2d').drawImage(mask,0,0);}
 cacheKey=JSON.stringify([sourceVersion,'realistic',$('resolution').value,settings(preIds)]);$('download').disabled=false;$('run').disabled=false;$('previewPaths').disabled=false;modelProgress(3);editorAvailability();status('استُعيدت نتيجة النموذج وتعديلاتك. اعتمد الصورة لتحديد المسارات.','ready');document.dispatchEvent(new CustomEvent('model-result-ready'));
 }catch{status('تعذرت استعادة الجلسة؛ اختر صورتك مجددًا.','error');}
}
restoreDraft();

$('resetInput').onclick=()=>{resetInputFields();invalidate(true);};

const professionalEditor=createImageEditor(api,async edited=>{
 clearTimeout(timer);clearTimeout(modelRetryTimer);clearTimeout(inputPreviewTimer);
 if(edited.target==='input'){await load(edited.image,'\u0635\u0648\u0631\u0629 \u0645\u062d\u0631\u0631\u0629 \u0645\u062d\u0644\u064a\u064b\u0627',true);return;}
 revision++;source=edited.reference;sourceVersion++;resetInputFields();preparedKey='';preparedInput=null;
 raw=edited.image;metrics={...metrics,width:edited.width,height:edited.height,edited:true};cacheKey=modelKey();
 brushes.resize(edited.width,edited.height);brushes.clear();
 for(const [id,value]of Object.entries({strength:100,threshold:180,weak:0,specks:0,weight:0,localReduction:65})){$(id).value=value;if($(id+'Value'))$(id+'Value').textContent=value;}
 $('binary').checked=false;$('threshold').disabled=true;$('original').src=edited.reference;
 disableResult();await run();
},()=>{if(source&&$('auto').checked&&document.body.dataset.resultStale==='true'){clearTimeout(timer);timer=setTimeout(run,450);}});
$('editInput').onclick=async()=>{if(!source||busy)return;clearTimeout(timer);try{const prepared=await prepareInput();if(prepared)await professionalEditor.open(prepared.image,prepared.image,'input');}catch(e){status(e.message,'error');}};
$('editResult').onclick=async()=>{if(!result||busy||document.body.dataset.resultStale==='true')return;clearTimeout(timer);await professionalEditor.open(result,$('original').src,'result');};
