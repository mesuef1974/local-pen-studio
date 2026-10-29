-- Preserve the source text before localizing the two archived copies of the owner card
-- and its historical review notes. Identifiers and code references remain unchanged.
CREATE TABLE IF NOT EXISTS workflow_text_originals (
    table_name TEXT NOT NULL,
    record_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    original_text TEXT NOT NULL,
    localized_at TEXT NOT NULL,
    PRIMARY KEY(table_name,record_key,field_name)
);
CREATE TABLE IF NOT EXISTS workflow_text_localizations (
    table_name TEXT NOT NULL,
    record_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    localized_text TEXT NOT NULL,
    PRIMARY KEY(table_name,record_key,field_name)
);

INSERT OR IGNORE INTO workflow_text_originals(table_name,record_key,field_name,original_text,localized_at)
SELECT 'coordination_cards',card_id,'title',title,strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM coordination_cards WHERE card_id IN ('CARD-20261029-602AD20D','CARD-20261029-602AD20D-LASER') AND title GLOB '*[A-Za-z]*';
INSERT OR IGNORE INTO workflow_text_originals(table_name,record_key,field_name,original_text,localized_at)
SELECT 'coordination_cards',card_id,'owner_request',owner_request,strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM coordination_cards WHERE card_id IN ('CARD-20261029-602AD20D','CARD-20261029-602AD20D-LASER') AND owner_request GLOB '*[A-Za-z]*';
INSERT OR IGNORE INTO workflow_text_originals(table_name,record_key,field_name,original_text,localized_at)
SELECT 'coordination_cards',card_id,'scope',scope,strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM coordination_cards WHERE card_id IN ('CARD-20261029-602AD20D','CARD-20261029-602AD20D-LASER') AND scope GLOB '*[A-Za-z]*';

UPDATE coordination_cards
SET title='تنفيذ معالجة حدّ المسارات وأداء الخط المركزي وفحوص التوجيه',
    owner_request='تنفيذ مهمة معالجة واحدة لنتائج بطاقة المراجعة CARD-20261029-1ED06BD2-PATH_PEN. الأدلة ومراجع المصدر ونتائج الفحوص مسجلة في تشغيل فحوص الجودة رقم 2 بالبطاقة الأصلية. مرجع منع التكرار الأصلي: 200ec410-45f8-4931-98f8-11621682d3ca:path_pen. ابدأ من أساس حديث ومتحقق من main، وحافظ على التغييرات غير المتعلقة بالمهمة. 1) وحّد الحد الأقصى لعدد المسارات المدعوم في faithful_paths وpath_fidelity وdrawing-simulator/pen_paths.py واستيراد المتجهات في drawing-simulator/app.js. طابق السلوك الفعلي والعقد والأخطاء واختبارات الحدود عند 6000/6001 و10000/10001؛ ولا تغيّر الحدود إلا إذا دعمت الأدلة عقد 10000 مسار. 2) قِس أداء استخراج الخط المركزي وبناء مخطط الجوار في Python لكل مرحلة على مدخلات إنتاج ممثلة. سجّل أزمنة قبل التغيير وبعده قابلة لإعادة الإنتاج ومقاييس مطابقة المسارات. خفّض كلفة المعالجة لكل بكسل في Python، ولا تعتمد primitives على GPU إلا بعد قياس الفائدة من البداية إلى النهاية والتحقق من مطابقة المخرجات. لا تنسب تسريع الاستخراج إلى قياسات تدقيق WebGPU. 3) أصلح test_centerline_routing.py الذي يشير إلى photo-lineart-comparison/realistic.png غير الموجود؛ استخدم مرجع fixture الصحيح أو أضف الملف المقصود استنادًا إلى دليل المستودع، وأدرج اختبارات التوجيه في CI. سلّم فرعًا والتزامًا محدود النطاق، وشغّل الاختبارات الملائمة على أساس حديث من main، وأرفق قياسات الأداء والمطابقة قبل التغيير وبعده، واطلب مراجعة QA الآلية. لا تدمج ولا تنشر.',
    scope='النطاق: معالجة النتائج الثلاث الواردة أعلاه بأقل تغييرات لازمة على المصدر والاختبارات وCI، مع أدلة الأداء ومطابقة المسارات وتسليم محدود في Git. القبول: (أ) توحيد سلوك حد المسارات واجتياز اختبارات الحدود ذات الصلة؛ (ب) معالجة fixture المفقود وإدراج اختبارات التوجيه في CI؛ (ج) نجاح الاختبارات ذات الصلة على main حديث؛ (د) تقرير قياس أداء مرحلي قابل لإعادة الإنتاج ومقارنة مطابقة المخرجات دون الخلط بين تدقيق GPU واستخراج المسارات؛ (هـ) التزام محدود النطاق وأدلة مراجعة QA الآلية. المرجع: CARD-20261029-1ED06BD2-PATH_PEN، تشغيل فحوص الجودة 2؛ مرجع منع التكرار 200ec410-45f8-4931-98f8-11621682d3ca:path_pen.'
WHERE card_id IN ('CARD-20261029-602AD20D','CARD-20261029-602AD20D-LASER')
  AND (title GLOB '*[A-Za-z]*' OR owner_request GLOB '*[A-Za-z]*' OR scope GLOB '*[A-Za-z]*');

INSERT OR IGNORE INTO workflow_text_originals(table_name,record_key,field_name,original_text,localized_at)
SELECT 'coordination_issues',CAST(issue_id AS TEXT),'impact_summary',impact_summary,strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM coordination_issues WHERE card_id IN ('CARD-20261029-1ED06BD2','CARD-20261029-1ED06BD2-PATH_PEN') AND impact_summary GLOB '*[A-Za-z]*';
INSERT OR IGNORE INTO workflow_text_localizations(table_name,record_key,field_name,localized_text)
SELECT 'coordination_issues',CAST(issue_id AS TEXT),'impact_summary',CASE cause_code
  WHEN 'path_limit_mismatch' THEN 'يسمح المخطط faithful_paths ومدقق المسارات بحد 10000 مسار، بينما يرفض drawing-simulator/pen_paths.py ما زاد على 6000، ولا يقبل drawing-simulator/app.js استيراد المتجهات فوق 6000. لذلك يبقى الحد الفعلي من البداية إلى النهاية 6000، ولا يمكن بلوغ إعداد 10000. التوصية: وحّد العقد في الاستخراج والنقل والاستيراد والتدقيق، مع اختبارات حدود عند 6000/6001 و10000/10001.'
  WHEN 'cpu_bound_centerline' THEN 'يبني استخراج الخط المركزي مجموعة عقد وقاموس تجاور لكل بكسل في Python، ثم يوجّه المسارات على الرسم البياني في Python. كما تعمل مسافة التحويل وSobel والبحث عن الحدود وتصوير CairoSVG وتجهيز قناع المصدر على CPU. تُظهر بيانات WebGPU المقترنة أن الاستخراج يستغرق 3.99 إلى 21.76 ثانية في عشر حالات، بينما يقتصر تشغيل GPU من NVIDIA على تحويل صورة التدقيق واحتساب نتيجته مباشرةً (وسيط ثلاث محاولات نحو 43 إلى 114 مللي ثانية). هذا يسرّع التدقيق ولا يسرّع الاستخراج. التوصية: قِس مدخل إنتاج لكل مرحلة، ثم خفّض كلفة مخطط البكسلات في Python، واختبر primitives على GPU بصورة مستقلة مع بوابة مطابقة للمخرجات.'
  WHEN 'routing_test_fixture_missing' THEN 'يتوقع drawing-simulator/test_centerline_routing.py وجود photo-lineart-comparison/realistic.png، بينما يحتوي المستودع على original.png فقط. تُظهر نتيجة التشغيل المستقل اجتياز 4 اختبارات وفشل اختبار واحد بسبب FileNotFoundError، كما أن CI لا يشغّل وحدة الاختبار هذه. التوصية: صحّح مرجع fixture أو أضف الصورة المقصودة بدليل من المستودع، وأدرج مجموعة اختبارات التوجيه في CI.'
END FROM coordination_issues
WHERE card_id IN ('CARD-20261029-1ED06BD2','CARD-20261029-1ED06BD2-PATH_PEN') AND cause_code IN ('path_limit_mismatch','cpu_bound_centerline','routing_test_fixture_missing') AND impact_summary GLOB '*[A-Za-z]*';

INSERT OR IGNORE INTO workflow_text_originals(table_name,record_key,field_name,original_text,localized_at)
SELECT 'coordination_events',CAST(event_id AS TEXT),'details',details,strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM coordination_events WHERE card_id IN ('CARD-20261029-602AD20D','CARD-20261029-602AD20D-LASER','CARD-20261029-1ED06BD2','CARD-20261029-1ED06BD2-PATH_PEN') AND details GLOB '*[A-Za-z]*';
INSERT OR IGNORE INTO workflow_text_localizations(table_name,record_key,field_name,localized_text)
SELECT 'coordination_events',CAST(event_id AS TEXT),'details',CASE
  WHEN event_type='card_queued_to_session' THEN 'قبلت واجهة Codex CLI إسناد البطاقة في الجلسة المسجلة.'
  WHEN event_type='validation_result' THEN 'نتيجة بوابة التحقق الآلي: مشروط. اكتملت مراجعة الكود على origin/main عند الالتزام 36058c65d368ee307965c7742f752b446c6cac6f.'
  WHEN event_type='git_push' THEN 'لم تُجر تغييرات على المصدر ضمن بطاقة المراجعة؛ لذلك لم يلزم الدفع. تمت مراجعة main عند الالتزام 36058c65d368ee307965c7742f752b446c6cac6f.'
  WHEN source_id='path_limit_mismatch' THEN 'نتيجة الفحص: اختلاف حد المسارات. يسمح المخطط والمدقق بحد 10000، لكن الاستيراد والتنفيذ يرفضان ما فوق 6000. يلزم توحيد الحد واختبار 6000/6001 و10000/10001.'
  WHEN source_id='cpu_bound_centerline' THEN 'نتيجة الفحص: استخراج الخط المركزي محدود بأداء CPU وبناء مخطط الجوار لكل بكسل في Python. يلزم قياس المراحل على مدخلات ممثلة، وتحسين الكلفة، والتحقق من مطابقة المخرجات.'
  WHEN source_id='routing_test_fixture_missing' THEN 'نتيجة الفحص: اختبار التوجيه يشير إلى realistic.png غير الموجودة، ولا تدرجها CI. يلزم تصحيح المرجع أو إضافة fixture المناسبة وتشغيل مجموعة الاختبارات في CI.'
END FROM coordination_events
WHERE details GLOB '*[A-Za-z]*' AND (
  (event_type='card_queued_to_session' AND source_id LIKE '200ec410-45f8-4931-98f8-11621682d3ca:path_pen:remediation-v1:%')
  OR (event_type IN ('validation_result','git_push') AND card_id IN ('CARD-20261029-1ED06BD2','CARD-20261029-1ED06BD2-PATH_PEN'))
  OR (event_type='review_finding' AND source_id IN ('path_limit_mismatch','cpu_bound_centerline','routing_test_fixture_missing') AND card_id IN ('CARD-20261029-1ED06BD2','CARD-20261029-1ED06BD2-PATH_PEN'))
);
