# Codex Usage Monitor

أداة محلية تقرأ أحداث `token_count` من سجلات Codex وتحفظ القياسات في SQLite. لا تستدعي نموذجًا ولا تحفظ نصوص المحادثات.

- الدليل التشغيلي: [`docs/CODEX-USAGE-MONITORING.md`](../../docs/CODEX-USAGE-MONITORING.md)
- المصدر: `codex_usage_logger.py`
- قاعدة البيانات: `%USERPROFILE%\.codex\usage-logs\usage.sqlite3`، ومخططها المرقم في `usage_database.py` و`migrations/`.
- جداول الفلو تميز الحالة الحالية عن سجل الأحداث غير القابل للتعديل، وتحفظ الإسنادات والآراء وقرارات المالك ومحاولات التسليم والتحقق والتعثرات وقواميس الحالة/السبب المرقمة. واجهة الكتابة المعاملاتية في `coordination_repository.py`.
- يمكن ربط عينة القياس ببطاقة ومرحلة، وربط الحدث بجلسة Codex، عبر معرّفات صريحة فقط؛ لا يستنتج النظام العلاقة من الوقت.
- مصنع البطاقات يعمل عبر `dashboard_server.py` و`workflow_service.py`؛ أمر المالك يسجل بطاقة جذر وبطاقات الجلسات المختصة في SQLite بمفتاح يمنع تكرار الأمر.
- يرسل خادم اللوحة المهام من Outbox إلى جلسات Codex المسجلة باستخدام `codex queue`. تعني `sent` قبول Codex وضع الرسالة في الجلسة فقط؛ إكمال البطاقة يتطلب إثبات الدفع وفحوص الجودة.
- تُحفظ معرّفات الجلسات وقدراتها محليًا في جدولي `coordination_actor_endpoints` و`coordination_actor_capabilities`، ولا تحفظ في Git. اربط كل جلسة مرة واحدة:

  ```powershell
  python scripts/usage_monitor/codex_session_dispatcher.py register --actor-id laser --thread-id <CODEX-THREAD-UUID> --capability frontend --capability interface
  ```

- حالات Outbox هي `pending`, `processing`, `sent`, `retry`, و`dead_letter`. نتيجة الإرسال غير المحسومة تُعزل ولا تعاد تلقائيًا، لتجنب تكرار التكليف.
- الاختبارات المركزة: `python -m unittest discover -s scripts/usage_monitor -p test_*.py`
- تثبيت/تحديث المهمة المجدولة من جذر المشروع: `./scripts/install_codex_usage_logger.ps1`
- تشغيل يدوي من جذر المشروع: `python scripts/usage_monitor/codex_usage_logger.py`
- نسخة احتياطية متسقة: `python scripts/usage_monitor/backup_usage_database.py` (SQLite Backup API + `integrity_check`).
- فتح لوحة المتابعة في المتصفح: `./scripts/usage_monitor/open_dashboard.ps1`؛ تقرأ اللوحة من endpoint محلي `/api/dashboard` ولا تنشئ لقطة JSON.
- تعرض اللوحة رسمًا إجماليًا وأربعة رسوم مستقلة لجلسات ليزر وعصف ذهني ومسار القلم وتنسيق إنتاج SVG. تتضمن الرسوم نسب ضغط السياق والحصة الأسبوعية، وتواريخ القمم وتجاوز عتبة 80٪، وتتجدد كل دقيقة.
- أسفل بطاقات الملخص تظهر بطاقة مختصرة للحصة الأسبوعية فقط: حالة تحديث القياس، نسبة المتبقي، وشريط الحصة وموعد التجديد.
- أمر محادثة سريع: «افتح لوحة استهلاك التوكنز المحلية من `scripts/usage_monitor/dashboard.html` وراجع مؤشرات الجلسات والاتجاه العام.»

في التشغيل الأول تُستورد عينات ملفات الجلسات ومواضع المعالجة من JSON مرة واحدة، مع إبقاء الملفات القديمة دون تعديل. لا تحذفها قبل مطابقة البيانات واعتماد الأرشفة. قاعدة البيانات والنسخ الاحتياطية خارج Git في `%USERPROFILE%\.codex\usage-logs\`، والخادم مربوط حصريًا بـ`127.0.0.1:8769`؛ يستخدم منفذًا مستقلًا كي لا يوقف خادم اللوحة السابق أثناء التحقق.
