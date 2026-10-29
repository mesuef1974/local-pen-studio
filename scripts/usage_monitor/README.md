# Codex Usage Monitor

أداة محلية تقرأ أحداث `token_count` من سجلات Codex وتحفظ القياسات في SQLite. لا تستدعي نموذجًا ولا تحفظ نصوص المحادثات.

- الدليل التشغيلي: [`docs/CODEX-USAGE-MONITORING.md`](../../docs/CODEX-USAGE-MONITORING.md)
- المصدر: `codex_usage_logger.py`
- خادم الويب: Django في `dashboard_project/`؛ ملف `dashboard_server.py` يبقي أمر التشغيل القديم متوافقًا.
- قاعدة البيانات: `%USERPROFILE%\.codex\usage-logs\usage.sqlite3`، ومخططها المرقم في `usage_database.py` و`migrations/`.
- جداول الفلو تميز الحالة الحالية عن سجل الأحداث غير القابل للتعديل، وتحفظ الإسنادات والآراء وقرارات المالك ومحاولات التسليم والتحقق والتعثرات وقواميس الحالة/السبب المرقمة. واجهة الكتابة المعاملاتية في `coordination_repository.py`.
- يمكن ربط عينة القياس ببطاقة ومرحلة، وربط الحدث بجلسة Codex، عبر معرّفات صريحة فقط؛ لا يستنتج النظام العلاقة من الوقت.
- الاختبارات المركزة: `python -m unittest discover -s scripts/usage_monitor -p test_*.py`
- تثبيت/تحديث المهمة المجدولة من جذر المشروع: `./scripts/install_codex_usage_logger.ps1`
- تشغيل يدوي من جذر المشروع: `python scripts/usage_monitor/codex_usage_logger.py`
- نسخة احتياطية متسقة: `python scripts/usage_monitor/backup_usage_database.py` (SQLite Backup API + `integrity_check`).
- تثبيت خادم اللوحة مرة واحدة: `python -m pip install -r scripts/usage_monitor/requirements-dashboard.txt`.
- فتح لوحة المتابعة في المتصفح: `./scripts/usage_monitor/open_dashboard.ps1`؛ يشغل Django على `127.0.0.1:8769` ويقرأ من endpoint `/api/dashboard` دون إنشاء لقطة JSON.
- إدارة Django: افتح `http://127.0.0.1:8769/admin/`. أنشئ حساب المالك مرة واحدة عبر `python scripts/usage_monitor/manage.py createsuperuser` واختر بيانات الدخول تفاعليًا. تعرض لوحة الإدارة جداول البطاقات والأحداث والآراء والقرارات والتسليم والتحقق والاستخدام للقراءة فقط، منعًا لتجاوز سجل الأحداث. تحفظ قاعدة دخول Django منفصلة في `%USERPROFILE%\.codex\usage-logs\dashboard-admin.sqlite3`؛ وتُفتح قاعدة القياس والفلو عبر اتصال SQLite للقراءة فقط.
- تعرض اللوحة رسمًا إجماليًا وأربعة رسوم مستقلة لجلسات ليزر وعصف ذهني ومسار القلم وتنسيق إنتاج SVG. تتضمن الرسوم نسب ضغط السياق والحصة الأسبوعية، وتواريخ القمم وتجاوز عتبة 80٪، وتتجدد كل دقيقة.
- أسفل بطاقات الملخص تظهر بطاقة مختصرة للحصة الأسبوعية فقط: حالة تحديث القياس، نسبة المتبقي، وشريط الحصة وموعد التجديد.
- أمر محادثة سريع: «افتح لوحة استهلاك التوكنز المحلية من `scripts/usage_monitor/dashboard.html` وراجع مؤشرات الجلسات والاتجاه العام.»

في التشغيل الأول تُستورد عينات ملفات الجلسات ومواضع المعالجة من JSON مرة واحدة، مع إبقاء الملفات القديمة دون تعديل. لا تحذفها قبل مطابقة البيانات واعتماد الأرشفة. قاعدة البيانات والنسخ الاحتياطية خارج Git في `%USERPROFILE%\.codex\usage-logs\`، والخادم مربوط حصريًا بـ`127.0.0.1:8769`. يعمل Django كطبقة HTTP فوق قاعدة SQLite الحالية؛ لا ينشئ جداول Django ولا يغيّر مخطط القياس والفلو.
