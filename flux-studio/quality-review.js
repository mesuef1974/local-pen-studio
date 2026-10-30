const bundle=window.REVIEW_DATA;
const $=id=>document.getElementById(id);
const axes=[['face','حفظ معالم الوجه'],['outlinePose','حفظ المحيط والوضعية'],['compositionCrop','حفظ التكوين والقص'],['traceability','وضوح الخطوط وقابليتها للتتبع']];
let index=0,ratings={};
const storageKey='flux-blind-round:'+bundle.roundId;
try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');if(saved?.roundId===bundle.roundId){ratings=saved.ratings||{};$('reviewer').value=saved.reviewer||'';}}catch{}
for(const [id,title] of axes){const label=document.createElement('label');label.htmlFor=id;label.textContent=title;const select=document.createElement('select');select.id=id;select.required=true;for(const [value,text] of [['','اختر التقييم'],['1','1 · اختلاف كبير / ضعيف'],['2','2'],['3','3 · متوسط'],['4','4'],['5','5 · حفظ شديد / واضح'],['na','غير منطبق'],['uncertain','غير حاسم']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}const group=document.createElement('div');group.append(label,select);$('scores').append(group);}
$('reviewer').disabled=Object.keys(ratings).length>0;
function show(){const item=bundle.cases[index],saved=ratings[item.id];$('source').src=bundle.sources[item.sourceId];$('sourceLink').href=bundle.sources[item.sourceId];$('candidate').src=item.candidate;$('candidateLink').href=item.candidate;for(const [id] of axes)$(id).value=saved?.scores[id]||'5';$('notes').value=saved?.notes||'';$('progress').textContent=`الصورة ${index+1} من ${bundle.cases.length} · المحفوظ ${Object.keys(ratings).length}`;$('previous').disabled=index===0;}
function record(){if(!$('reviewer').value.trim()){$('reviewer').reportValidity();$('reviewer').focus();return false;}const scores=Object.fromEntries(axes.map(([id])=>[id,$(id).value]));$('reviewer').disabled=true;ratings[bundle.cases[index].id]={scores,notes:$('notes').value.trim(),recordedAt:new Date().toISOString()};try{localStorage.setItem(storageKey,JSON.stringify(exportData()));$('status').textContent='حُفظ التقييم محليًا.';}catch{$('status').textContent='تعذر الحفظ المحلي؛ نزّل الإجابات الآن.';}return true;}
function exportData(){return {version:bundle.version,roundId:bundle.roundId,reviewer:$('reviewer').value.trim(),ratings};}
$('ratingForm').onsubmit=e=>{e.preventDefault();if(record()){if(index<bundle.cases.length-1){index++;show();}else{$('status').textContent='اكتملت الجولة. نزّل الإجابات وأرسل الملف للتحليل.';}}};
$('previous').onclick=()=>{if(index>0){index--;show();}};
$('download').onclick=()=>{if(!$('reviewer').value.trim()){$('reviewer').focus();return;}const blob=new Blob([JSON.stringify(exportData(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='blind-review-'+bundle.roundId+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
show();
