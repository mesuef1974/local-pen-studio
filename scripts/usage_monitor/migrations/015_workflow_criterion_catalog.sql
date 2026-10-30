CREATE TABLE IF NOT EXISTS workflow_criterion_catalog (
    criterion_code TEXT PRIMARY KEY,
    category_code TEXT NOT NULL,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT NOT NULL DEFAULT '',
    check_method TEXT NOT NULL,
    default_required INTEGER NOT NULL DEFAULT 0 CHECK (default_required IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_criterion_catalog_active_order
    ON workflow_criterion_catalog(active, category_code, sort_order, criterion_code);

INSERT OR IGNORE INTO workflow_criterion_catalog
    (criterion_code,category_code,title,description,check_method,default_required,active,sort_order,created_at,updated_at)
VALUES
    ('automated_delivery_qa','quality','التحقق الآلي من الإنجاز','تشغيل الفحوص المناسبة للمهمة وتسجيل النتيجة ودليلها في المصنع.','automated_quality_gate',1,1,10,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
    ('automated_tests','quality','اجتياز الاختبارات ذات الصلة','تشغيل مجموعة الاختبارات المناسبة للتغيير وتسجيل نتيجة التشغيل.','automated_tests',0,1,20,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
    ('scope_match','delivery','مطابقة التغيير لنطاق البطاقة','التحقق من أن الملفات والتغييرات المسلّمة تقع ضمن النطاق المطلوب.','scope_match',0,1,30,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
    ('documented_evidence','delivery','توثيق مخرجات وأدلة التسليم','تسجيل الملفات أو الروابط والملخص الذي يثبت اكتمال المخرج.','manual_evidence',0,1,40,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
    ('source_citations','research','توثيق المصادر والادعاءات','ربط المعلومات الأساسية بمصادرها وفصل الحقائق عن الاستنتاجات.','source_review',0,1,50,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
    ('rtl_accessibility','interface','سلامة RTL وإمكانية الوصول','مراجعة اتجاه RTL وتسميات الحقول والتنقل بلوحة المفاتيح والتباين.','accessibility_review',0,1,60,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
