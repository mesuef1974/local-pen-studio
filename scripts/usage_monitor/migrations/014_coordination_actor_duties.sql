CREATE TABLE IF NOT EXISTS coordination_actors (
    actor_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    charter TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS coordination_actor_duties (
    actor_id TEXT PRIMARY KEY REFERENCES coordination_actors(actor_id) ON DELETE CASCADE,
    assignment_scope TEXT NOT NULL CHECK (length(trim(assignment_scope)) > 0),
    flow_responsibility TEXT NOT NULL CHECK (length(trim(flow_responsibility)) > 0),
    required_outputs TEXT NOT NULL CHECK (length(trim(required_outputs)) > 0),
    verification_guidance TEXT NOT NULL CHECK (length(trim(verification_guidance)) > 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO coordination_actors(actor_id, display_name, charter, active) VALUES
    ('brainstorm', 'عصف ذهني', 'تنسيق البطاقات والتقارير والتوصيات', 1),
    ('laser', 'ليزر', 'مراجعة العتاد الليزري والمصادر والسلامة والبرامج', 1),
    ('path_pen', 'مسار القلم', 'تطوير المسارات وقياساتها', 1),
    ('svg', 'تنسيق إنتاج SVG', 'عقد SVG والتحقق والتصدير', 1);

INSERT OR IGNORE INTO coordination_actor_duties (
    actor_id, assignment_scope, flow_responsibility, required_outputs, verification_guidance
)
SELECT actor_id,
       'تنسيق البطاقات والتقارير والتوصيات، وجمع آراء الجلسات عند طلب المالك',
       'توضيح نطاق المهمة وتسجيل الآراء والتوصيات في السجل المشترك وقاعدة المصنع، ثم تسليم المخرج المطلوب',
       'مخرج البطاقة ومصادر الآراء أو المراجع وأدلة التسليم',
       'التحقق من اكتمال المخرج، وصحة نسبة الآراء، وعدم تسجيل اعتماد دون قرار موثق'
FROM coordination_actors WHERE actor_id = 'brainstorm';

INSERT OR IGNORE INTO coordination_actor_duties (
    actor_id, assignment_scope, flow_responsibility, required_outputs, verification_guidance
)
SELECT actor_id,
       'العتاد الليزري والمواد والعمليات والسلامة والبرامج ومصادرها',
       'تنفيذ المراجعة الفنية المسندة وتسجيل المصادر والقيود والنتائج في البطاقة',
       'النتيجة الفنية والمصادر المباشرة والقيود وأدلة الفحص',
       'تمييز الحقائق الموثقة عن الاستنتاجات، والتحقق من المصدر والإصدار والسياق'
FROM coordination_actors WHERE actor_id = 'laser';

INSERT OR IGNORE INTO coordination_actor_duties (
    actor_id, assignment_scope, flow_responsibility, required_outputs, verification_guidance
)
SELECT actor_id,
       'هندسة المسارات وتطويرها وقياساتها',
       'إنتاج المسارات أو مراجعتها وتسجيل القياسات وطريقتها ونتائج التحقق في البطاقة',
       'ملفات المسار أو مراجعها، ووحدات القياس والعينة ونتائج الفحص',
       'تثبيت الوحدات وطريقة القياس والعينة المرجعية ومقارنة النتيجة بمعايير البطاقة'
FROM coordination_actors WHERE actor_id = 'path_pen';

INSERT OR IGNORE INTO coordination_actor_duties (
    actor_id, assignment_scope, flow_responsibility, required_outputs, verification_guidance
)
SELECT actor_id,
       'عقد SVG والتحقق من التحويل والتصدير',
       'تنفيذ عقد SVG المسند والتحقق من التحويل والتصدير وتسجيل الأدلة والفجوات في البطاقة',
       'ملفات SVG المسلّمة ونتائج التحقق ومراجع الأدلة والفجوات المعروفة',
       'فحص مطابقة العقد وسلامة التحويل والتصدير وفق معايير البطاقة'
FROM coordination_actors WHERE actor_id = 'svg';

CREATE INDEX IF NOT EXISTS idx_coord_actor_duties_updated
    ON coordination_actor_duties(updated_at DESC, actor_id);

CREATE TRIGGER IF NOT EXISTS trg_coord_actor_duties_updated_at
AFTER UPDATE OF assignment_scope, flow_responsibility, required_outputs, verification_guidance
ON coordination_actor_duties
FOR EACH ROW
BEGIN
    UPDATE coordination_actor_duties SET updated_at = CURRENT_TIMESTAMP WHERE actor_id = NEW.actor_id;
END;
