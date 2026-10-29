"""Owner-only administration over the existing application data."""

from django.contrib import admin
from django.contrib.admin import AllValuesFieldListFilter
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import connections, transaction

from .models import ADMIN_MODELS, DISPLAY_COLUMNS, FILTER_FIELDS, SEARCH_FIELDS


CODE_LABELS = {
    "owner": "المالك",
    "laser": "ليزر",
    "brainstorm": "عصف ذهني",
    "path_pen": "مسار القلم",
    "svg": "تنسيق SVG",
    "draft": "مسودة",
    "queued": "في قائمة الانتظار",
    "assigned": "مسندة",
    "in_progress": "قيد التنفيذ",
    "blocked": "متعذرة",
    "needs_clarification": "تحتاج توضيحًا",
    "reassignment_requested": "طُلب إعادة الإسناد",
    "verifying": "قيد التحقق",
    "delivered": "تم التسليم",
    "awaiting_checks": "بانتظار فحوص GitHub",
    "awaiting_review": "بانتظار مراجعة GitHub",
    "merged_sync_pending": "بانتظار مزامنة main",
    "processing": "قيد المعالجة",
    "accepted": "مقبولة",
    "accepted_by_owner": "اعتمدها المالك",
    "awaiting_owner": "بانتظار المالك",
    "returned": "أعيدت للتعديل",
    "failed": "فشلت",
    "completed": "مكتملة",
    "archived": "مؤرشفة",
    "card_created": "إنشاء بطاقة",
    "card_assigned": "إسناد بطاقة",
    "session_opinion_recorded": "تسجيل رأي جلسة",
    "owner_decision_recorded": "تسجيل قرار المالك",
    "status_transition": "تغيير حالة",
    "deliverable_registered": "تسجيل مخرج",
    "delivery_attempt": "محاولة تسليم",
    "git_commit": "حفظ التزام Git",
    "git_push": "دفع إلى Git",
    "git_integration_state": "تقدم الدمج الآلي",
    "git_integration_completed": "اكتمال الدمج الآلي",
    "validation_result": "نتيجة تحقق",
    "pass": "اجتاز",
    "passed": "اجتاز",
    "fail": "لم يجتز",
    "success": "نجاح",
    "error": "خطأ",
    "pending": "قيد الانتظار",
    "rejected": "مرفوض",
    "enabled": "مفعّل",
    "disabled": "معطّل",
    "file": "ملف",
    "report": "تقرير",
    "commit": "التزام",
    "branch": "فرع",
    "owner_command": "أمر مالك",
    "intake": "استقبال الأمر",
    "assignment": "الإسناد",
    "advisory": "الرأي الاستشاري",
    "delivery": "التسليم",
    "git_delivery": "التسليم عبر Git",
    "owner_decision": "قرار المالك",
    "verification": "التحقق",
    "create": "إنشاء",
    "update": "تعديل",
    "delete": "حذف",
    "general": "عام",
    "urgent": "عاجلة",
    "high": "عالية",
    "normal": "عادية",
    "low": "منخفضة",
}

READ_ONLY_WORKFLOW_TABLES = {
    "coordination_command_receipts",
    "coordination_command_cards",
    "coordination_events",
    "coordination_git_events",
    "coordination_git_integrations",
    "coordination_delivery_attempts",
    "coordination_delivery_paths",
    "coordination_opinion_history",
    "owner_decision_history",
    "coordination_quality_runs",
    "coordination_quality_checks",
    "coordination_validation_results",
    "schema_migrations",
    "workflow_admin_audit",
    "workflow_text_originals",
    "workflow_text_localizations",
}

WORKFLOW_ADMIN_GROUPS = (
    ("أوامر المالك والبطاقات", "commands", (
        "coordination_cards", "coordination_command_cards", "coordination_command_receipts",
        "coordination_assignments", "coordination_card_criteria", "coordination_card_dependencies",
    )),
    ("الجلسات والتوجيه", "sessions", (
        "coordination_actors", "coordination_actor_capabilities", "coordination_actor_endpoints", "usage_sessions",
    )),
    ("التنفيذ والتسليم", "delivery", (
        "coordination_deliverables", "coordination_delivery_attempts", "coordination_delivery_paths",
        "coordination_git_events", "coordination_issues", "coordination_outbox",
        "coordination_git_integrations",
    )),
    ("الآراء والقرارات والجودة", "reviews", (
        "coordination_opinions", "coordination_opinion_history", "owner_decisions", "owner_decision_history",
        "coordination_quality_runs", "coordination_quality_checks", "coordination_validation_results",
    )),
    ("القياس والسجلات والإعدادات", "records", (
        "coordination_events", "workflow_admin_audit", "usage_samples", "usage_sources", "database_metadata",
        "schema_migrations", "workflow_reason_definitions", "workflow_status_definitions", "workflow_transition_rules",
        "workflow_text_originals", "workflow_text_localizations",
    )),
)


class TranslatedAllValuesFieldListFilter(AllValuesFieldListFilter):
    def choices(self, changelist):
        for choice in super().choices(changelist):
            display = str(choice["display"])
            for code, label in CODE_LABELS.items():
                if display == code:
                    choice = {**choice, "display": label}
                    break
                prefix = f"{code} ("
                if display.startswith(prefix) and display.endswith(")"):
                    choice = {**choice, "display": f"{label} {display[len(code):]}"}
                    break
            yield choice


class OwnerOnlyAdminSite(admin.AdminSite):
    site_header = "إدارة الفلو واستهلاك Codex"
    site_title = "إدارة Local Pen Studio"
    index_title = "بيانات البطاقات والجلسات"
    site_url = "/"

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        if app_label:
            return app_list
        grouped_apps = []
        for app in app_list:
            if app["app_label"] != "workflow_admin":
                grouped_apps.append(app)
                continue
            models_by_table = {item["model"]._meta.db_table: item for item in app["models"]}
            assigned = set()
            for name, slug, table_names in WORKFLOW_ADMIN_GROUPS:
                group_models = [models_by_table[table] for table in table_names if table in models_by_table]
                if not group_models:
                    continue
                assigned.update(table_names)
                selected_url = next((item["admin_url"] for item in group_models
                                     if item.get("admin_url") and item["admin_url"] in request.path), None)
                grouped_apps.append({
                    **app,
                    "name": name,
                    "app_label": f"workflow_admin_{slug}",
                    "app_url": selected_url or group_models[0].get("admin_url") or app["app_url"],
                    "models": group_models,
                })
            remainder = [item for table, item in models_by_table.items() if table not in assigned]
            if remainder:
                grouped_apps.append({**app, "name": "جداول أخرى", "app_label": "workflow_admin_other", "models": remainder})
        return grouped_apps


owner_admin_site = OwnerOnlyAdminSite(name="admin")
owner_admin_site.register(get_user_model(), UserAdmin)
owner_admin_site.register(Group, admin.ModelAdmin)


class WorkflowTableAdmin(admin.ModelAdmin):
    list_per_page = 50
    show_full_result_count = False
    actions = None
    code_display_fields = {
        "status": ("status_label", "الحالة"),
        "event_type": ("event_type_label", "نوع الحدث"),
        "actor_id": ("actor_label", "الجلسة أو الجهة"),
        "assigned_actor_id": ("assigned_actor_label", "الجهة المسندة إليها"),
        "assigned_by_actor_id": ("assigned_by_actor_label", "الجهة المسندة"),
        "submitted_by_actor_id": ("submitted_by_actor_label", "الجهة المسلّمة"),
        "owner_actor_id": ("owner_actor_label", "المالك"),
        "validator_actor_id": ("validator_actor_label", "جهة التحقق"),
        "outcome": ("outcome_label", "النتيجة"),
        "state_code": ("state_label", "حالة الإرسال"),
        "stage_code": ("stage_label", "مرحلة الفلو"),
        "action": ("action_label", "الإجراء"),
        "kind": ("kind_label", "نوع المخرج"),
        "card_type_code": ("card_type_label", "نوع البطاقة"),
        "priority_code": ("priority_label", "الأولوية"),
        "terminal": ("terminal_label", "حالة نهائية"),
        "active": ("active_label", "نشط"),
        "enabled": ("enabled_label", "مفعّل"),
        "required": ("required_label", "إلزامي"),
    }

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        available = {field.name for field in model._meta.fields}
        self.list_display = tuple(
            self.code_display_fields.get(name, (name, ""))[0]
            if name in self.code_display_fields else name
            for name in DISPLAY_COLUMNS.get(model._meta.db_table, ())
            if name in available
        ) or (model._meta.pk.name,)
        self.search_fields = tuple(
            name for name in SEARCH_FIELDS.get(model._meta.db_table, ()) if name in available
        )
        self.list_filter = tuple(
            (name, TranslatedAllValuesFieldListFilter)
            for name in FILTER_FIELDS.get(model._meta.db_table, ()) if name in available
        )
        # Django's date hierarchy raises AttributeError when a table has rows
        # but every value in its selected timestamp column is NULL. These
        # workflow tables are sparse and use nullable timestamps, so keep the
        # changelist available instead of rendering a fragile date drilldown.
        self.date_hierarchy = None
        self.ordering = (model._meta.pk.name,)

    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)
        content_fields = {
            "coordination_cards": ("title", "owner_request", "scope"),
            "coordination_card_criteria": ("title", "description"),
            "coordination_issues": ("impact_summary",),
            "coordination_opinions": ("opinion", "recommendation"),
            "owner_decisions": ("notes",),
        }.get(self.model._meta.db_table, ())
        if not content_fields:
            return base_form

        class ArabicWorkflowContentForm(base_form):
            def clean(self):
                import re
                cleaned = super().clean()
                for field in content_fields:
                    value = str(cleaned.get(field) or "").strip()
                    if value and not re.search(r"[\u0600-\u06ff]", value):
                        self.add_error(field, "اكتب هذا المحتوى باللغة العربية.")
                return cleaned

        return ArabicWorkflowContentForm

    def get_queryset(self, request):
        return super().get_queryset(request).using("workflow")

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def _is_read_only_workflow_table(self):
        return self.model._meta.db_table in READ_ONLY_WORKFLOW_TABLES

    def has_add_permission(self, request):
        return not self._is_read_only_workflow_table() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return not self._is_read_only_workflow_table() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._is_read_only_workflow_table() and super().has_delete_permission(request, obj)

    @staticmethod
    def _audit_snapshot(obj):
        return type(obj).objects.using("workflow").filter(pk=obj.pk).values().first()

    def _write_audit(self, request, obj, action, before, after):
        import json
        from usage_database import utc_now
        with connections["workflow"].cursor() as cursor:
            cursor.execute("""INSERT INTO workflow_admin_audit
                (actor_username,table_name,object_pk,action_code,before_json,after_json,recorded_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""", [
                request.user.get_username(), obj._meta.db_table, str(obj.pk), action,
                json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
                json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
                utc_now(),
            ])

    def save_model(self, request, obj, form, change):
        with transaction.atomic(using="workflow"):
            before = self._audit_snapshot(obj) if change else None
            super().save_model(request, obj, form, change)
            self._write_audit(request, obj, "update" if change else "create", before,
                              self._audit_snapshot(obj))

    def delete_model(self, request, obj):
        with transaction.atomic(using="workflow"):
            before = self._audit_snapshot(obj)
            self._write_audit(request, obj, "delete", before, None)
            super().delete_model(request, obj)

    def _label(self, obj, field):
        value = getattr(obj, field)
        return CODE_LABELS.get(str(value), value)

    @admin.display(description="الحالة", ordering="status")
    def status_label(self, obj): return self._label(obj, "status")

    @admin.display(description="نوع الحدث", ordering="event_type")
    def event_type_label(self, obj): return self._label(obj, "event_type")

    @admin.display(description="الجلسة أو الجهة", ordering="actor_id")
    def actor_label(self, obj): return self._label(obj, "actor_id")

    @admin.display(description="الجهة المسندة إليها", ordering="assigned_actor_id")
    def assigned_actor_label(self, obj): return self._label(obj, "assigned_actor_id")

    @admin.display(description="الجهة المسندة", ordering="assigned_by_actor_id")
    def assigned_by_actor_label(self, obj): return self._label(obj, "assigned_by_actor_id")

    @admin.display(description="الجهة المسلّمة", ordering="submitted_by_actor_id")
    def submitted_by_actor_label(self, obj): return self._label(obj, "submitted_by_actor_id")

    @admin.display(description="المالك", ordering="owner_actor_id")
    def owner_actor_label(self, obj): return self._label(obj, "owner_actor_id")

    @admin.display(description="جهة التحقق", ordering="validator_actor_id")
    def validator_actor_label(self, obj): return self._label(obj, "validator_actor_id")

    @admin.display(description="النتيجة", ordering="outcome")
    def outcome_label(self, obj): return self._label(obj, "outcome")

    @admin.display(description="حالة الإرسال", ordering="state_code")
    def state_label(self, obj): return self._label(obj, "state_code")

    @admin.display(description="مرحلة الفلو", ordering="stage_code")
    def stage_label(self, obj): return self._label(obj, "stage_code")

    @admin.display(description="الإجراء", ordering="action")
    def action_label(self, obj): return self._label(obj, "action")

    @admin.display(description="نوع المخرج", ordering="kind")
    def kind_label(self, obj): return self._label(obj, "kind")

    @admin.display(description="نوع البطاقة", ordering="card_type_code")
    def card_type_label(self, obj): return self._label(obj, "card_type_code")

    @admin.display(description="الأولوية", ordering="priority_code")
    def priority_label(self, obj): return self._label(obj, "priority_code")

    @admin.display(description="حالة نهائية", boolean=True, ordering="terminal")
    def terminal_label(self, obj): return getattr(obj, "terminal")

    @admin.display(description="نشط", boolean=True, ordering="active")
    def active_label(self, obj): return getattr(obj, "active")

    @admin.display(description="مفعّل", boolean=True, ordering="enabled")
    def enabled_label(self, obj): return getattr(obj, "enabled")

    @admin.display(description="إلزامي", boolean=True, ordering="required")
    def required_label(self, obj): return getattr(obj, "required")


for model in ADMIN_MODELS.values():
    owner_admin_site.register(model, WorkflowTableAdmin)
