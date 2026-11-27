// The four figures and the note shown under the preview for the current stage. It reads nothing but its arguments.
// out is the stage output, ready says it is fresh, plan is the pen plan of the paths stage, approved says the review image is approved.
export function fmt(seconds){const n=Math.max(0,Math.round(seconds));return Math.floor(n/60)+':'+String(n%60).padStart(2,'0');}
export function stageSummary({stage:s,ready,out,plan,approved,excludedCount}){
 if(!ready||(s===2&&!plan))return {labels:['أبعاد المخرج','زمن المعالجة','نوع المعالجة','جاهزية المرحلة'],values:['—','—','—','—'],info:out?'النتيجة السابقة تحتاج تحديثًا قبل الاعتماد.':'راجع المعاينة بعد تشغيل المرحلة.'};
 if(s===0)return {labels:['أبعاد المخرج','زمن المعالجة','مصدر الصورة','جاهزية المرحلة'],values:[`${out.width||out.meta?.width} × ${out.height||out.meta?.height}`,(out.seconds||0)+' ث',out.generated?(out.model||'FLUX.2 Klein 4B'):out.unmodified?'الصورة المستوردة':out.manual?'محرر الصورة':'أدوات الصور',out.generated?'نسخة فنية للمراجعة':'جاهز للمراجعة'],info:out.generated?`بذرة النتيجة: ${out.seed} · خرج FLUX المباشر · راجع الملامح قبل الاعتماد.`:out.backgroundCached?'فصل الخلفية محفوظ؛ لم يُعد تشغيله.':out.unmodified?(out.resized?`نسخة عمل مصغرة من ${out.originalWidth} × ${out.originalHeight} بكسل؛ ملف الصورة الأصلي لم يتغير.`:'الصورة المستوردة دون تطبيق أدوات التهيئة.'):'تعديل محلي اختياري من المدخل الحالي.'};
 if(s===1)return {labels:['أبعاد الصورة','مرجع المسارات','معالجة وسيطة','جاهزية الاعتماد'],values:[`${out.width} × ${out.height}`,'النسخة المعروضة نفسها','لا توجد',approved?'معتمدة':'بانتظار اعتمادك'],info:'لن تُستخرج المسارات قبل اعتماد هذه النسخة. أي تعديل لاحق يلغي اعتماد المسارات السابقة.'};
 return {labels:['ضربات القلم','طول الحبر','طول الانتقال','زمن حركة تقديري'],values:[plan.count.toLocaleString('ar-u-nu-latn'),(plan.ink/1000).toFixed(2)+' م',(plan.movement/1000).toFixed(2)+' م',fmt(plan.seconds)],info:`${out.paths.length} مستخرج · ${excludedCount} مستبعد يدويًا · ${plan.items.reduce((n,v)=>n+v.p.length,0)} نقطة · دون تسارع أو تحقق حركي`};}
// The smallest minimum line length (0.1 mm steps, up to the slider's 5 mm) that brings the drawing under the limit.
// The remaining strokes keep their order, so the time is an estimate; null when no longer minimum would drop anything.
export function lighterPlan({items,current,limit,measure,timeline}){
 const sized=items.map(item=>[item,measure(item)]),at=tenth=>{const kept=sized.filter(([,mm])=>mm>=tenth/10).map(([item])=>item);return {minimum:tenth/10,dropped:items.length-kept.length,kept:kept.length,seconds:timeline(kept).seconds};};
 let low=Math.floor(current*10+1e-6)+1,high=50;if(low>high)return null;
 const most=at(high);if(!most.dropped||!most.kept)return null;if(most.seconds>=limit)return {...most,reaches:false};
 while(low<high){const middle=(low+high)>>1;if(at(middle).seconds<limit)high=middle;else low=middle+1;}
 return {...at(low),reaches:true};
}
