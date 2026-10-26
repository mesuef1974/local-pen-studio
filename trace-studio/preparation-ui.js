export function createPreparation(api,hooks){
 const $=id=>document.getElementById(id);
 const defaults={background:'auto',style:'tones',levels:12,denoise:45,contrast:110,brightness:0,tolerance:25};
 const sliders=[['levels','عدد الدرجات الرمادية',4,32],['denoise','تخفيف الملمس والضوضاء',0,100],['contrast','التباين ٪',50,180],['brightness','السطوع',-60,60],['tolerance','تسامح الخلفية البسيطة',0,100]];
 $('prepAdjustments').innerHTML=sliders.map(([id,label,min,max])=>`<div class="field"><label for="prep-${id}">${label}<output id="prep-${id}-value">${defaults[id]}</output></label><input id="prep-${id}" type="range" min="${min}" max="${max}" step="1" value="${defaults[id]}"></div>`).join('');
 const recipes=[['balanced','رمادي مبسط',{}],['detail','تفاصيل أكثر',{levels:24,denoise:20,contrast:105}],['soft','ملمس أقل',{levels:8,denoise:75,contrast:105}],['ink','حبر أبيض وأسود',{style:'ink',denoise:55,contrast:110}],['gray','رمادي كامل',{style:'gray',denoise:20,contrast:100}]];
 $('prepPresets').innerHTML=recipes.map(([id,label])=>`<button data-prep-preset="${id}" aria-pressed="${id==='balanced'}">${label}</button>`).join('');
 let source='',prepared='',preparedMeta=null,filename='',revision=0,fresh=false,busy=false,pending=false,once=false,timer;
 function settings(){return {background:$('prepBackground').value,style:$('prepStyle').value,...Object.fromEntries(sliders.map(([id])=>[id,Number($('prep-'+id).value)]))};}
 function sync(){for(const [id]of sliders)$('prep-'+id+'-value').textContent=$('prep-'+id).value;$('prep-levels').disabled=$('prepStyle').value!=='tones';$('prep-tolerance').disabled=$('prepBackground').value!=='border';}
 function stage(value){document.body.dataset.stage=value;$('stagePrepare').setAttribute('aria-pressed',value==='prepare');$('stageTrace').setAttribute('aria-pressed',value==='trace');requestAnimationFrame(fit);}
 function availability(){$('prepRun').disabled=!source||busy;$('approvePreparation').disabled=!fresh||!preparedMeta?.ready||busy;$('savePrepared').disabled=!fresh||busy;}
 function error(text){hooks.error(text);}
 function dirty(){revision++;fresh=false;$('prepareWorkspace').dataset.stale='true';$('stageTrace').disabled=true;clearTimeout(timer);hooks.invalidate();availability();$('prepNote').textContent='راجع معاينة التجهيز قبل اعتمادها. التعديلات تبدأ دائمًا من الأصل المستورد.';document.querySelectorAll('[data-prep-preset]').forEach(b=>b.setAttribute('aria-pressed','false'));sync();if(source&&once&&$('prepAuto').checked)timer=setTimeout(run,450);}
 function activity(value){busy=value;$('prepProgress').hidden=!value||!source;$('prepareWorkspace').setAttribute('aria-busy',String(value));hooks.busy(value);availability();}
 async function load(file){
  if(!file)return;
  if(file.size>15_000_000){error('الحد الأقصى للاستيراد 15 ميغابايت.');return;}
  clearTimeout(timer);revision++;fresh=false;once=false;pending=false;source='';prepared='';preparedMeta=null;$('stageTrace').disabled=true;hooks.invalidate();stage('prepare');activity(true);
  try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('تعذر فتح الصورة.'));reader.readAsDataURL(file);});
   const result=await api('/api/import',{image:data});source=result.image;filename=file.name;$('filename').textContent=file.name;$('sourceInfo').textContent=`استيراد ${result.meta.width} × ${result.meta.height} بكسل`+(result.resized?' بعد تصغير مناسب للمعالجة':'')+(result.firstFrame?' · الإطار الأول فقط':'');
   $('prepSource').src=source;$('prepEmpty').hidden=true;$('prepGrid').hidden=false;$('prepResult').hidden=true;$('prepPlaceholder').hidden=false;
   $('prepResultPaper').style.aspectRatio=result.meta.width+'/'+result.meta.height;
   if(result.meta.ready){prepared=source;preparedMeta=result.meta;fresh=true;$('prepareWorkspace').dataset.stale='false';$('prepResult').src=source;$('prepResult').hidden=false;$('prepPlaceholder').hidden=true;$('prepNote').textContent='المدخل رسم شفاف أحادي اللون بالفعل. يمكنك اعتماده كما هو أو تجهيز نسخة أخرى.';}
   else $('prepNote').textContent='اختر طريقة الخلفية وأسلوب الرسم، ثم اضغط «تجهيز الصورة». الأصل المستورد محفوظ للمقارنة.';
   error('');
  }catch(e){error(e.message);}finally{activity(false);$('file').value='';requestAnimationFrame(fit);}
 }
 async function run(){
  clearTimeout(timer);if(!source)return;if(busy){pending=true;return;}
  once=true;pending=false;fresh=false;$('stageTrace').disabled=true;hooks.invalidate();activity(true);const job=revision;
  try{const result=await api('/api/prepare',{image:source,settings:settings()});if(job!==revision)return;prepared=result.image;preparedMeta=result.meta;fresh=true;$('prepareWorkspace').dataset.stale='false';$('prepResult').src=prepared;$('prepResult').hidden=false;$('prepPlaceholder').hidden=true;$('prepNote').textContent=`المعاينة مجهزة · ${result.meta.width} × ${result.meta.height} بكسل · ${result.seconds} ثانية`+(result.backgroundCached?' · أُعيد استخدام فصل الخلفية المحفوظ':'')+' · راجع الملامح والشفافية ثم اعتمد الصورة.';error('');}
  catch(e){if(job===revision)error(e.message);}
  finally{activity(false);requestAnimationFrame(fit);if(pending){pending=false;if($('prepAuto').checked)run();}}
 }
 $('prepRun').onclick=run;
 for(const id of ['prepBackground','prepStyle',...sliders.map(([id])=>'prep-'+id)])$(id).oninput=dirty;
 document.querySelectorAll('[data-prep-preset]').forEach(b=>b.onclick=()=>{const recipe=recipes.find(p=>p[0]===b.dataset.prepPreset);const s={...defaults,...recipe[2],background:$('prepBackground').value,tolerance:Number($('prep-tolerance').value)};$('prepStyle').value=s.style;for(const [id]of sliders)$('prep-'+id).value=s[id];dirty();clearTimeout(timer);document.querySelectorAll('[data-prep-preset]').forEach(other=>other.setAttribute('aria-pressed',other===b));if(source)run();});
 $('prepAuto').onchange=()=>{if(!$('prepAuto').checked)clearTimeout(timer);else if(source&&once&&!fresh)run();};
 $('approvePreparation').onclick=()=>{if(!fresh||!preparedMeta?.ready||busy)return;$('stageTrace').disabled=false;stage('trace');hooks.accept(prepared,source,preparedMeta,filename);};
 $('stagePrepare').onclick=()=>stage('prepare');$('stageTrace').onclick=()=>{if(!$('stageTrace').disabled)stage('trace');};
 $('savePrepared').onclick=()=>{if(fresh)hooks.download(prepared,'trace-prepared.png');};
 $('prepEmptyUpload').onclick=()=>$('file').click();
 function fit(){for(const id of ['prepSource','prepResult']){const image=$(id),paper=image.parentElement,viewport=paper.parentElement;const width=image.naturalWidth||$('prepSource').naturalWidth,height=image.naturalHeight||$('prepSource').naturalHeight;if(!width||!viewport.clientHeight)continue;const css=getComputedStyle(viewport);paper.style.width=Math.max(1,Math.min(viewport.clientWidth-parseFloat(css.paddingLeft)-parseFloat(css.paddingRight),(viewport.clientHeight-parseFloat(css.paddingTop)-parseFloat(css.paddingBottom)-20)*width/height))+'px';}}
 for(const id of ['prepSource','prepResult'])$(id).onload=fit;new ResizeObserver(()=>requestAnimationFrame(fit)).observe($('prepareWorkspace'));
 document.addEventListener('keydown',e=>{if(document.body.dataset.stage==='prepare'&&(e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!$('prepRun').disabled){e.preventDefault();run();}});
 sync();availability();stage('prepare');
 return {load};
}
