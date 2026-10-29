const rows=await fetch('audit.json').then(r=>r.json());
const $=id=>document.getElementById(id);
const clock=s=>`${Math.floor(Math.round(s)/60)}:${String(Math.round(s)%60).padStart(2,'0')}`;
function render(){const key=$('subject').value+'-'+$('style').value,row=rows.find(r=>r.key===key);if(!row)return;
 for(const [id,suffix]of [['raw','flux'],['old','old-reconstruction'],['new','reconstruction'],['target','target'],['difference','difference']]){$(id).src=key+'-'+suffix+'.png';$(id+'Link').href=$(id).src;$(id+'Link').target='_blank';$(id+'Link').rel='noopener';}
 $('caseSummary').textContent=`تطابق الحبر ${row.score.inkIoU}% · الاسترجاع ${row.score.inkRecall}% · الدقة ${row.score.inkPrecision}% · خطأ الرمادي ${row.score.grayErrorInkRegion}% · ${row.count.toLocaleString('ar-u-nu-latn')} ضربة · زمن تقديري ${clock(row.motion.seconds)} · تخطيط ${row.planningSeconds} ث.`;
}
$('subject').onchange=$('style').onchange=render;$('print').onclick=()=>window.print();render();
