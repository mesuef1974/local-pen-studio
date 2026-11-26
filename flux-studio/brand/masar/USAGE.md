# قواعد استعمال علامة «مسار»

المفهوم المعتمد: a1 «المدخل المفتوح (السكتش 14)». الفكرة بجملة: كلمة مسار كتلة أفقية منخفضة تخترقها قناة مفتوحة من فجوة الألف والراء إلى تجويف الميم فوق قاعدة سوداء متصلة.

## الصيغ
- `masar-mark.svg` الرمز بالألوان: للترويسة والواجهة على الورق الفاتح.
- `masar-mark-mono.svg` أحادي أسود: للطباعة بلون واحد والختم.
- `masar-mark-reversed.svg` أبيض على داكن: للوضع الداكن والخلفيات الداكنة.
- `masar-wordmark.svg` الكلمة «مسار» مسارات بلا نص حي.
- `masar-lockup.svg` الرمز والكلمة معًا (الرمز على اليمين في RTL).
- `favicon.svg`، `favicon.ico` (16/32/48)، `favicon-32.png`، `apple-touch-icon.png`، `icon-192.png`، `icon-512.png`، `maskable-512.png`، `site.webmanifest`.
- `tokens.css` متغيرات الألوان، `BrandMark.vue` مكوّن Vue 3 للرمز، و`BrandLockup.vue` للقفل (إن وُجد قفل).
- أين تجدها: كلها في حزمة سِمة (`package/` من الإصدار). في مشروع استلم بأمر التسليم: ملفات SVG وهذا الملف و`tokens.css` بجواره في `brand/masar/`، والأيقونات و`site.webmanifest` في `frontend/public/`، والمكوّنان في `frontend/src/components/`.

## المساحة الخالية والحد الأدنى
- اترك حول الرمز مساحة لا تقل عن ربع عرضه من كل جهة.
- الحد الأدنى للرمز وحده 16 بكسل على الشاشة و6 مم في الطباعة؛ للقفل مع الكلمة 24 بكسل ارتفاعًا.
- لا تدوير، لا تمديد، لا ظل، لا تدرج، لا حدود مضافة، لا تغيير نسب الرمز إلى الكلمة.

## الألوان
| الدور | القيمة | التباين على الورق #F3F6F8 |
|---|---|---|
| لون العلامة | #087C76 | 4.66:1 |
| الحبر | #1B2A33 | 13.57:1 |
| لون التمييز في الهوية (الرمز بلون واحد لا يستعمله) | #06665F | 6.3:1 |
| نص أبيض على لون العلامة | #FFFFFF | 5.05:1 |

## إعلان العناصر الزخرفية والمعلوماتية (WCAG 1.4.11)
- الرمز كاملًا عنصر معلوماتي: يجب أن يبقى تباينه مع خلفيته 3:1 على الأقل (محقَّق أعلاه).

## الربط في المشروع
مشروع استلم الحزمة بأمر التسليم (`sima deliver`) ربطُه منجز في فرع بطاقته ولا خطوة يدوية فيه: المكوّنان والأيقونات وروابط `<head>` في القالب، ومتغيرات الشعار (`--color-mark-*`) مكتوبة في `tokens.css` المشروع نفسه، حبرها لون العلامة على الفاتح وأبيض على الداكن. الخطوات الآتية لمشروع يربط بيده فقط:
1. انسخ `favicon.svg` و`favicon.ico` وملفات PNG و`site.webmanifest` إلى `public/`.
2. عرّف `--color-mark-ink` في رموز مشروعك بقيم `tokens.css` هذه، واجعل `--color-mark-ink` أبيض في الوضع الداكن.
3. استبدل `components/BrandMark.vue` و`components/BrandLockup.vue` بالمولَّدَين (لا تعدّل الملفات القديمة في مكانها: هذا إصدار جديد).
4. في `<head>`: `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`، و`<link rel="icon" href="/favicon.ico" sizes="any">`، و`<link rel="apple-touch-icon" href="/apple-touch-icon.png">`، و`<link rel="manifest" href="/site.webmanifest">`.

## الفحص الآلي عند الاعتماد
- أصغر سماكة عند 96 بكسل: 4.38 (الحد 1.5).
- تغطية صغير/256: 1.061؛ مكوّنات عند الحجم الصغير: 1.
- نقاط الارتكاز: 49؛ الأشكال: 1.
- أقرب مراجع إدراكيًا (للعلم؛ ليست تصريحًا قانونيًا): maven (5/64)، nats (5/64)، open-zeppelin (5/64)
- فحص العلامة التجارية رسميًا (وزارة التجارة والصناعة/WIPO) مسؤولية المالك قبل أي نشر تجاري.

## ملفات الحزمة
ما في `package/` من إصدار سِمة؛ المنسوخ منها إلى المشروع ومواضعه في قسم «الصيغ» أعلاه.
- BrandLockup.vue
- BrandMark.vue
- apple-touch-icon.png
- audit.json
- concept.json
- favicon-32.png
- favicon.ico
- favicon.svg
- icon-192.png
- icon-512.png
- masar-lockup-mono.svg
- masar-lockup.svg
- masar-mark-mono.svg
- masar-mark-reversed.svg
- masar-mark-white.svg
- masar-mark.svg
- masar-wordmark.svg
- maskable-512.png
- site.webmanifest
- tokens.css
- USAGE.md
