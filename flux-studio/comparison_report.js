const $=id=>document.getElementById(id);
const names={front:'وجه أمامي',side:'وجه جانبي',full:'شخصية مرسومة',animal:'قطة',object:'فنجان'};
const styles={ink:'خطوط قلم نظيفة',minimal:'رسم مختصر','pencil-light':'رصاص خفيف'};
const casesOrder=Object.keys(names),styleOrder=Object.keys(styles);
let data={rows:[],cases:[],state:'running'},reviews={rows:{},recommendations:[]};
const escape=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const number=(n,d=0)=>Number.isFinite(n)?new Intl.NumberFormat('en-US',{maximumFractionDigits:d}).format(n):'—';
const duration=s=>{if(!Number.isFinite(s))return '—';const v=Math.round(s);return `${Math.floor(v/60)}:${String(v%60).padStart(2,'0')}`;};
const good=value=>Boolean(value&&!value.error&&Number.isFinite(value.seconds));
const saving=row=>good(row.direct)&&good(row.precise)&&row.precise.seconds>0?(row.precise.seconds-row.direct.seconds)/row.precise.seconds*100:null;
const source=id=>`${id}-source.png`;

function image(id,path,available,title){const img=$(id),button=img.parentElement,placeholder=button.querySelector('.placeholder');img.hidden=!available;if(placeholder)placeholder.hidden=available;button.disabled=!available;button.setAttribute('aria-label',available?'تكبير '+title:title+' غير متاح بعد');if(available&&img.getAttribute('src')!==path)img.src=path;button.onclick=()=>{if(!available)return;$('zoomImage').src=path;$('zoomImage').alt=title;$('zoomTitle').textContent=title;$('zoomDialog').showModal();};}

function metricHTML(metrics){
 if(metrics?.error)return `<p class="error">${escape(metrics.error)}</p>`;
 if(!good(metrics))return '<p>لم يكتمل الحساب بعد.</p>';
 return `<div><span>ضربات القلم</span><strong><bdi>${number(metrics.count)}</bdi></strong></div><div><span>زمن الحركة · د:ث</span><strong><bdi>${duration(metrics.seconds)}</bdi></strong></div><div><span>طول الحبر · متر</span><strong><bdi>${number(metrics.inkMm/1000,2)}</bdi></strong></div><div><span>خطوط أقصر من 2 مم</span><strong><bdi>${number(metrics.shortUnder2mm)}</bdi></strong></div><p class="path-precision">بكسل المصدر على الورق: ${number(metrics.mapping.scale,3)} مم؛ ${metrics.mapping.scale>metrics.penMm?'أكبر من سماكة القلم المختارة، وقد تظهر درجات السلم في المنحنيات.':'هذا قياس لشبكة الصورة، وليس لدقة الذراع.'}</p>`;
}

function renderDetail(){
 const id=$('caseSelect').value,style=$('styleSelect').value,key=id+'-'+style;
 const selectedCase=data.cases.find(c=>c.id===id),row=data.rows.find(r=>r.id===key);
 $('sourceNote').textContent=selectedCase?.note||'لم يصل تشغيل هذه العينة بعد. تستمر المقارنة محليًا وتُحدَّث النتائج عند اكتمال كل تجربة.';
 image('sourceImage',source(id),!!selectedCase,'الصورة المرجعية');
 image('fluxImage',key+'-flux.png',!!row?.generation,'خرج FLUX');
 image('preciseImage',key+'-precise.png',!!row?.precise,'خرج النموذج الدقيق');
 image('directImage',key+'-direct.svg',good(row?.direct),'المسارات المباشرة على ورقة A4');
 image('viaImage',key+'-via-precise.svg',good(row?.precise),'المسارات بعد النموذج الدقيق على ورقة A4');
 $('directMetrics').innerHTML=metricHTML(row?.direct);$('viaMetrics').innerHTML=metricHTML(row?.precise);
 for(const [element,branch,file]of [['directSvg','direct','-direct.svg'],['preciseSvg','precise','-via-precise.svg']]){const link=$(element);link.hidden=!good(row?.[branch]);if(good(row?.[branch]))link.href=key+file;}
 const review=reviews.rows?.[key];
 $('visualReview').replaceChildren();const title=document.createElement('strong'),paragraph=document.createElement('p');title.textContent=review?.label||'الفحص البصري';paragraph.textContent=review?.text||'لم يُسجل تقييم بصري لهذه العينة بعد. عدد الضربات والزمن لا يقيسان التشابه أو اكتمال الملامح.';$('visualReview').append(title,paragraph);
 $('actualPrompt').textContent=row?.generation?.effectivePrompt||'بانتظار التوليد';
 $('generationStats').textContent=row?.generation?`المخرج ${row.generation.width}×${row.generation.height} · التوليد داخل العامل ${row.generation.seconds} ث · الزمن الكامل من الطلب ${row.generation.wallSeconds} ث · ذروة تخصيص PyTorch ${row.generation.peakMiB} MiB. قد يشمل الزمن الكامل انتظار مهمة أخرى وبدء البيئة.`:row?.error||'لم تكتمل هذه العينة بعد.';
}

function render(){
 const generated=data.rows.filter(r=>r.generation).length,complete=data.rows.filter(r=>r.state==='complete').length;
 const branches=data.rows.reduce((total,row)=>total+Number(good(row.direct))+Number(good(row.precise)),0);
 $('totalGenerated').textContent=number(generated)+' / 15';$('totalBranches').textContent=number(branches)+' / 30';
 $('progress').value=complete;$('progressCount').textContent=`${complete} / 15`;
 $('progressLabel').textContent=data.state==='complete'?(complete===15?'اكتملت المحاولات الـ15':'انتهى التشغيل؛ توجد محاولات متعثرة'):'توليد وقياس فعلي على الجهاز';
 const savings=data.rows.map(saving).filter(v=>v!==null).sort((a,b)=>a-b);
 const median=savings.length?(savings.length%2?savings[Math.floor(savings.length/2)]:(savings[savings.length/2-1]+savings[savings.length/2])/2):null;
 $('medianSaving').textContent=median===null?'—':`${median>=0?'+':''}${number(median,1)}%`;
 $('verdictTitle').textContent=reviews.title||'القياس جارٍ، والحكم البصري يأتي بعده.';
 $('verdictText').textContent=reviews.text||'انخفاض عدد الضربات وحده لا يثبت حفظ الملامح.';
 $('recommendations').replaceChildren();for(const item of reviews.recommendations||[]){const card=document.createElement('article'),h=document.createElement('strong'),p=document.createElement('p');card.className='recommendation';h.textContent=item.title;p.textContent=item.text;card.append(h,p);$('recommendations').append(card);}
 const rows=data.rows.slice().sort((a,b)=>casesOrder.indexOf(a.case)-casesOrder.indexOf(b.case)||styleOrder.indexOf(a.style)-styleOrder.indexOf(b.style));
 $('resultsBody').innerHTML=rows.map(row=>{const delta=saving(row),review=reviews.rows?.[row.id];return `<tr><td><button type="button" data-row="${escape(row.id)}">${escape(names[row.case])}</button></td><td>${escape(styles[row.style])}${row.state==='failed'?'<br>تعثر التوليد':row.state!=='complete'?'<br>قيد المعالجة':''}</td><td class="n"><bdi>${number(row.direct?.count)}</bdi></td><td class="n"><bdi>${number(row.precise?.count)}</bdi></td><td class="n"><bdi>${duration(row.direct?.seconds)}</bdi></td><td class="n"><bdi>${duration(row.precise?.seconds)}</bdi></td><td class="n ${delta===null?'':delta>=0?'positive':'negative'}"><bdi>${delta===null?'—':(delta>=0?'+':'')+number(delta,1)+'%'}</bdi></td><td>${escape(review?.short||row.error||row.direct?.error||row.precise?.error||'لم يُقيّم بصريًا بعد')}</td></tr>`;}).join('');
 for(const button of $('resultsBody').querySelectorAll('[data-row]'))button.onclick=()=>{const row=data.rows.find(r=>r.id===button.dataset.row);$('caseSelect').value=row.case;$('styleSelect').value=row.style;renderDetail();$('comparison').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});};
 renderDetail();
}

async function refresh(){try{
 const [resultResponse,reviewResponse]=await Promise.all([fetch('results.json',{cache:'no-store'}),fetch('reviews.json',{cache:'no-store'})]);
 if(resultResponse.ok)data=await resultResponse.json();if(reviewResponse.ok)reviews=await reviewResponse.json();render();
 }catch{$('progressLabel').textContent='تعذر تحديث الصفحة؛ القياس المحلي لا يتوقف.';}
 setTimeout(refresh,data.state==='complete'?30000:10000);
}
$('caseSelect').onchange=renderDetail;$('styleSelect').onchange=renderDetail;
$('print').onclick=()=>window.print();$('closeZoom').onclick=()=>$('zoomDialog').close();
refresh();
