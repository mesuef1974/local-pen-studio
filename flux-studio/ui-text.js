// Stage wording and the page state derived from it. No DOM here, so screens can be rearranged without touching this.
const STAGES=[
 {step:'المرحلة الأولى · FLUX',title:'الصورة',description:'FLUX هو نموذج الصور المعتمد؛ أدوات التهيئة وإزالة الخلفية اختيارية.',workspace:'صورتك في استوديو FLUX',workspaceDescription:'الأصل محفوظ؛ انتقل للمراجعة عندما تصبح الصورة جاهزة.',input:'مدخل التحرير',output:'نتيجة التحرير',run:'تطبيق أدوات الصورة',recipes:'أدوات تهيئة اختيارية',waiting:'بانتظار صورة'},
 {step:'المرحلة الثانية · الاعتماد',title:'الاعتماد',description:'قارن بالأصل ثم أكّد كل بند. تُعتمد الصورة المعروضة كما هي، وأي تعديل لاحق يبطل الاعتماد.',workspace:'الصورة التي سيرسمها القلم',workspaceDescription:'قارن الملامح، ثم اعتمد هذه النسخة نفسها للمسارات.',input:'الصورة الأصلية للمقارنة',output:'نسخة المراجعة · دون معالجة إضافية',run:'مراجعة الصورة',recipes:'اعتماد الصورة',waiting:'بانتظار نسخة للمراجعة'},
 {step:'المرحلة الثالثة · القلم',title:'راجع مسار القلم',description:'نفس الرسم المعتمد، على ورقة وبوحدات واضحة.',workspace:'حركة قلم قابلة للمراجعة',workspaceDescription:'راجع تطابق الحبر بسماكة القلم الفعلية، ثم حاكِ الحركة وصدّرها.',input:'الصورة المعتمدة للقلم',output:'مسارات القلم المختارة',run:'تحديث المسارات',recipes:'تفضيلات مسار القلم',waiting:'بانتظار اعتماد الصورة'},
 {step:'المرحلة الرابعة · الإخراج',title:'الإخراج',description:'قلم أو ليزر، مخرجان متساويان.',workspace:'محاكاة الأداة والتصدير',workspaceDescription:'اختر الأداة، راجع معاينتها وتحذيراتها، ثم صدّر.',input:'الصورة المعتمدة للقلم',output:'مسارات القلم المختارة',run:'تحديث المسارات',recipes:'تفضيلات مسار القلم',waiting:'بانتظار المسارات'},
];
export const stageText=stage=>STAGES[stage];
// The line under a stage name in the header. state holds the Workflow arrays.
export function stageStateText({fresh,approved,outputs,source,canEnter},i){
 if(i===3)return canEnter?'جاهز للتصدير':STAGES[i].waiting;
 if(fresh[i])return i===0?'نسخة جاهزة':i===1?(approved[1]?'معتمدة للقلم':'بانتظار اعتمادك'):'مسارات جاهزة';
 if(outputs[i])return 'تحديث مطلوب';
 if(i===0&&source)return 'جاهز للتجهيز';
 return i>0&&canEnter?'جاهز للتشغيل':STAGES[i].waiting;
}
export const nextLabel=stage=>['راجِع الصورة','اعتمد الصورة','إلى الإخراج','صدّر'][stage];
export const editLabel=stage=>stage===1?'العودة إلى محرر الصورة':'محرر الصورة والأدوات';
export const saveLabel='حفظ نتيجة المرحلة';
// The server reports a plan that is too complex in words only; these openings match faithful_paths.py.
export const COMPLEXITY_ERRORS=['تجاوزت خطة المطابقة حد التعقيد','تجاوزت العلامات والخطوط حد التعقيد'];
export const isComplexityError=message=>COMPLEXITY_ERRORS.some(text=>message.includes(text));
export function remainingChecksText(n){
 if(!n)return 'اكتملت قائمة الفحص';
 return 'بقي '+(n===1?'بند واحد':n===2?'بندان':n+' بنود')+' قبل الاعتماد';
}
