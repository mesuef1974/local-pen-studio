# مرسم — Local Pen Studio

تطبيق محلي لتحويل الصور إلى رسم خطي، ثم تحديد مسارات قلم ومراجعتها ومحاكاتها. الواجهة عربية باتجاه RTL.

## التطبيق الحالي والعمل على المستودع

التطبيق الحالي **مسار · FLUX** في [`flux-studio/`](flux-studio/README.md)، على المنفذ 8770.
الأوصاف التالية تشمل التطبيقات الأقدم ومحركاتها المشتركة.

- [المساهمة وطلبات الدمج](CONTRIBUTING.md)
- [اعتماد الإصدارات والنشر والرجوع](docs/RELEASING.md)
- [التعامل مع الأسرار والمشكلات الأمنية](SECURITY.md)
- [مراقب بطاقة التسليم 0001 — وضع الاختبار](docs/HANDOFF-AUTOMATION.md)

كل تغيير يمر بطلب دمج وفحوص `Quality gate`. لا ينفذ الدمج أو CI نشرًا تلقائيًا.

## مساحات العمل

| التطبيق | الوظيفة | التشغيل من جذر المستودع | المنفذ |
|---|---|---|---|
| مرسم | التطبيق الأصلي ومحاكاة القلم | `python drawing-simulator/launch.py` | 8765 |
| حافّة | ست خوارزميات OpenCV و52 تفضيلًا للحواف | `python edge-studio/launch.py` | 8766 |
| تريس | تجهيز الصور ثم مهارة التحويل إلى SVG | `python trace-studio/launch.py` | 8767 |
| مسار | أنبوب تجهيز الصورة ← Lineart الدقيق ← مسارات القلم | `python pipeline-studio/launch.py` | 8769 |

التفاصيل وحدود التشغيل والاختبارات في README داخل كل مجلد. التطبيقات الجديدة تعيد استخدام البيئات والأوزان الموجودة؛ لا يتضمن المستودع هذه الأوزان أو بيئات Python. صفحة مسار الجديدة لها انتقالات `/prepare` و`/model` و`/paths` مع اعتماد صريح وإبطال النتائج اللاحقة عند تغيير المدخل. الحفظ متاح للنتائج؛ جلسة الصور داخل التبويب لا تستعاد بعد تحديث الصفحة.

## مراحل العمل

1. تجهيز الصورة في صندوق الأدوات وتشغيل نموذج **Lineart الدقيق** محليًا.
2. استخراج مسارات القلم، تنقيتها، اختيار الخطوط وترتيبها، ثم تصدير SVG أو فتح المحاكاة.

تتضمن المرحلة الأولى أدوات رسم وتحديد وقص وتغيير دقة ومعالجة الصورة. إزالة الخلفية تستخدم **BiRefNet-General عبر rembg على CPU**. نموذج Lineart يستخدم CUDA إن كانت متاحة. هذه الخدمات مستقلة عن LM Studio.

## التشغيل على الجهاز الحالي

من مجلد المشروع:

```powershell
python drawing-simulator/launch.py
```

لتشغيل السيرفر وحده:

```powershell
python drawing-simulator/server.py
```

الرابط: <http://127.0.0.1:8765/>. يعمل السيرفر على الجهاز المحلي فقط.

## متطلبات النقل إلى جهاز آخر

هذه النسخة تحفظ الكود ولا تتضمن بيئة Python أو أوزان النماذج. التشغيل على جهاز جديد يحتاج تجهيزها أولًا؛ استنساخ المستودع وحده غير كافٍ.

- البيئة الأساسية المجربة: Python 3.12 وOpenCV contrib 4.10 وNumPy وPillow.
- `.venv-lineart`: PyTorch ملائم للجهاز، `controlnet-aux==0.0.10` و`timm==1.0.30` و`huggingface_hub` واعتمادياتها.
- أوزان `lllyasviel/Annotators/sk_model.pth` ضمن مخبأ Hugging Face في `drawing-simulator/models/lineart`؛ الخدمة تقرؤها بوضع محلي فقط.
- `.venv-background`: المتطلبات في `drawing-simulator/requirements-background.txt`.
- أوزان BiRefNet في `drawing-simulator/models/background/models/birefnet-general/birefnet-general.onnx`.

لم يُنفّذ اختبار تثبيت نظيف على جهاز آخر، ولا يوجد ملف قفل كامل للاعتماديات بعد. يجب مراجعة تراخيص المكتبات والنماذج عند إعادة توزيعها.

## التحقق

من `drawing-simulator`:

```powershell
python -m unittest test_editor_ops test_input_adjustments test_lineart_tools test_ink_copy test_centerline_routing -q
node test-lineart-workflow.cjs
node test-path-order.cjs
node test-editor-geometry.cjs
node test-worker-ink.cjs
node test-path-refinement.cjs
```

## حدود النسخة

المحاكاة لا ترسل أوامر لذراع حقيقي. أزمنة الرسم تقديرية ولا تمثل تحققًا حركيًا من التسارع أو الاصطدامات أو حدود المفاصل. السرعات في لوحة المسارات لتقدير الزمن، وتُضبط بشكل مستقل داخل المحاكاة.

لم تُحسم مشكلة جودة بعض ملامح الوجوه الحقيقية. كما أن بلاغ بطء إزالة الخلفية الأخير لم يُستكمل فحصه بعد تغيير الأولوية إلى مسارات القلم.

التقارير المحلية HTML موجودة في جذر المشروع وملف `drawing-simulator/path-methodology-ar.html`. بعض التقارير توثّق مراحل سابقة ولا تمثل بالضرورة آخر سلوك للكود. الأوزان والبيئات والسجلات وصور التجارب والأرشيف المستبعد تبقى على الجهاز.
