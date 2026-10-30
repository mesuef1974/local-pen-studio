"""Django model facades for every application table in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.db import models
from django import forms


ADMIN_TABLES = {
    "coordination_actor_capabilities": "قدرات الجلسات والجهات",
    "coordination_actor_duties": "مهام الجلسات ومسؤولياتها في الفلو",
    "coordination_actor_endpoints": "نقاط اتصال الجلسات",
    "coordination_actors": "الجلسات والجهات",
    "coordination_assignments": "إسنادات البطاقات",
    "coordination_card_criteria": "معايير قبول البطاقات",
    "coordination_card_proposals": "اقتراحات بطاقات المتابعة",
    "coordination_card_proposal_criteria": "معايير اقتراحات المتابعة",
    "workflow_criterion_catalog": "كتالوج معايير الإنجاز",
    "coordination_card_dependencies": "اعتماديات البطاقات",
    "coordination_cards": "البطاقات",
    "coordination_command_cards": "بطاقات أوامر المالك",
    "coordination_command_receipts": "إيصالات أوامر المالك",
    "coordination_deliverables": "المخرجات المسلّمة",
    "coordination_delivery_attempts": "محاولات التسليم",
    "coordination_delivery_paths": "مسارات التسليم",
    "coordination_events": "سجل أحداث البطاقات",
    "coordination_git_events": "أحداث Git",
    "coordination_git_integrations": "تكاملات Git ومزامنة main",
    "coordination_issues": "عوائق التنفيذ",
    "coordination_opinion_history": "سجل آراء الجلسات",
    "coordination_opinions": "آراء الجلسات",
    "coordination_outbox": "صندوق إرسال المهام",
    "coordination_quality_checks": "فحوص الجودة",
    "coordination_quality_runs": "جولات فحص الجودة",
    "coordination_validation_results": "نتائج التحقق",
    "database_metadata": "بيانات تعريف القاعدة",
    "owner_decision_history": "سجل قرارات المالك",
    "owner_decisions": "قرارات المالك الحالية",
    "schema_migrations": "سجل ترحيلات المخطط",
    "usage_samples": "عينات استهلاك التوكنز",
    "usage_sessions": "جلسات الاستخدام",
    "usage_sources": "مصادر سجلات الاستخدام",
    "workflow_reason_definitions": "تعريفات أسباب الفلو",
    "workflow_status_definitions": "تعريفات حالات الفلو",
    "workflow_transition_rules": "قواعد انتقال الحالات",
    "workflow_admin_audit": "سجل تغييرات الإدارة",
    "workflow_text_originals": "النصوص الأصلية المحفوظة",
    "workflow_text_localizations": "الترجمات العربية لسجلات التدفق",
}

DISPLAY_COLUMNS = {
    "coordination_actor_capabilities": ("actor_id", "capability"),
    "coordination_actor_duties": ("actor_id", "assignment_scope", "flow_responsibility", "required_outputs", "verification_guidance"),
    "coordination_actor_endpoints": ("actor_id", "provider_code", "thread_id", "enabled", "updated_at"),
    "coordination_actors": ("actor_id", "display_name", "active"),
    "coordination_assignments": ("assignment_id", "card_id", "assigned_actor_id", "reason_code", "assigned_at"),
    "coordination_card_criteria": ("criterion_id", "card_id", "title", "required", "sort_order"),
    "coordination_card_proposals": ("proposal_id", "source_card_id", "proposed_by_actor_id", "title", "status_code", "created_at"),
    "coordination_card_proposal_criteria": ("proposal_criterion_id", "proposal_id", "title", "required", "sort_order"),
    "workflow_criterion_catalog": ("criterion_code", "category_code", "title", "check_method", "default_required", "active", "sort_order"),
    "coordination_card_dependencies": ("card_id", "depends_on_card_id", "relation", "created_at"),
    "coordination_cards": ("card_id", "title", "status", "assigned_actor_id", "created_at"),
    "coordination_command_cards": ("idempotency_key", "card_id", "role_code"),
    "coordination_command_receipts": ("idempotency_key", "root_card_id", "created_at"),
    "coordination_deliverables": ("deliverable_id", "card_id", "kind", "path", "created_at"),
    "coordination_delivery_attempts": ("attempt_id", "card_id", "attempt_number", "outcome", "submitted_at"),
    "coordination_delivery_paths": ("delivery_path_id", "attempt_id", "path", "scope_result"),
    "coordination_events": ("event_id", "card_id", "event_type", "actor_id", "recorded_at"),
    "coordination_git_events": ("git_event_id", "card_id", "action", "outcome", "recorded_at"),
    "coordination_git_integrations": ("integration_id", "card_id", "pull_request_number", "state_code", "updated_at"),
    "coordination_issues": ("issue_id", "card_id", "stage_code", "cause_code", "observed_at"),
    "coordination_opinion_history": ("opinion_history_id", "card_id", "actor_id", "recorded_at"),
    "coordination_opinions": ("opinion_id", "card_id", "actor_id", "recorded_at"),
    "coordination_outbox": ("outbox_id", "card_id", "target_actor_id", "state_code", "created_at"),
    "coordination_quality_checks": ("check_id", "quality_run_id", "check_code", "outcome"),
    "coordination_quality_runs": ("quality_run_id", "card_id", "outcome", "started_at", "finished_at"),
    "coordination_validation_results": ("validation_id", "card_id", "attempt_id", "outcome", "recorded_at"),
    "database_metadata": ("key", "value"),
    "owner_decision_history": ("decision_history_id", "card_id", "axis", "decided_by_actor_id", "decided_at"),
    "owner_decisions": ("decision_id", "card_id", "axis", "decided_at"),
    "schema_migrations": ("version", "name", "applied_at"),
    "usage_samples": ("sample_id", "session_id", "sampled_at", "model", "cumulative_total_tokens"),
    "usage_sessions": ("session_id", "session_name", "created_at", "updated_at"),
    "usage_sources": ("source_path", "session_id", "updated_at"),
    "workflow_reason_definitions": ("reason_code", "version", "category", "display_name"),
    "workflow_status_definitions": ("status_code", "version", "display_name", "terminal"),
    "workflow_transition_rules": ("from_status_code", "to_status_code", "version", "enabled"),
    "workflow_admin_audit": ("audit_id", "actor_username", "table_name", "object_pk", "action_code", "recorded_at"),
    "workflow_text_originals": ("table_name", "record_key", "field_name", "original_text", "localized_at"),
    "workflow_text_localizations": ("table_name", "record_key", "field_name", "localized_text"),
}

SEARCH_FIELDS = {
    "coordination_actor_duties": ("actor_id", "assignment_scope", "flow_responsibility", "required_outputs"),
    "workflow_criterion_catalog": ("criterion_code", "title", "description"),
    "coordination_card_proposals": ("proposal_id", "source_card_id", "title", "owner_request", "rationale"),
    "coordination_card_proposal_criteria": ("proposal_id", "title", "description"),
    "coordination_cards": ("card_id", "title", "owner_request"),
    "coordination_events": ("event_type", "card_id", "actor_id", "source_id"),
    "coordination_git_integrations": ("card_id", "repository", "pull_request_url", "last_error_code"),
    "coordination_assignments": ("card_id", "assigned_actor_id", "reason_code"),
    "coordination_opinions": ("card_id", "actor_id", "opinion", "recommendation"),
    "coordination_opinion_history": ("card_id", "actor_id", "opinion", "recommendation"),
    "owner_decisions": ("card_id", "axis", "decision"),
    "owner_decision_history": ("card_id", "axis", "decision"),
    "usage_sessions": ("session_id", "session_name"),
    "usage_samples": ("session_id", "model", "reasoning_effort", "service_tier"),
    "workflow_admin_audit": ("actor_username", "table_name", "object_pk"),
    "workflow_text_originals": ("table_name", "record_key", "field_name"),
    "workflow_text_localizations": ("table_name", "record_key", "field_name"),
}

FILTER_FIELDS = {
    "coordination_actors": ("active",),
    "coordination_card_proposals": ("status_code", "proposed_by_actor_id", "suggested_assignee_actor_id"),
    "coordination_assignments": ("assigned_actor_id", "reason_code"),
    "workflow_criterion_catalog": ("category_code", "active", "default_required"),
    "coordination_cards": ("status", "assigned_actor_id", "priority_code", "card_type_code"),
    "coordination_events": ("event_type", "actor_id", "stage_code"),
    "coordination_delivery_attempts": ("outcome", "submitted_by_actor_id"),
    "coordination_git_events": ("action", "outcome"),
    "coordination_git_integrations": ("state_code", "last_error_code"),
    "coordination_issues": ("stage_code", "cause_code"),
    "coordination_outbox": ("state_code", "target_actor_id"),
    "coordination_quality_runs": ("outcome", "profile_code"),
    "coordination_validation_results": ("outcome", "validator_actor_id"),
    "usage_samples": ("session_id", "model", "reasoning_effort", "service_tier"),
    "workflow_admin_audit": ("action_code", "table_name"),
    "workflow_text_originals": ("table_name",),
    "workflow_text_localizations": ("table_name",),
}

FIELD_LABELS = {
    "actor_id": "معرّف الجلسة أو الجهة", "active": "نشط", "attempt_id": "معرّف محاولة التسليم",
    "assignment_scope": "نطاق الإسناد", "flow_responsibility": "مسؤولية الجلسة في الفلو",
    "required_outputs": "المخرجات المطلوبة", "verification_guidance": "إرشادات التحقق",
    "object_pk": "معرّف السجل",
    "attempt_number": "رقم المحاولة", "assigned_actor_id": "الجلسة المسندة إليها",
    "assigned_by_actor_id": "الجهة المسندة", "assigned_at": "وقت الإسناد",
    "available_at": "موعد الإتاحة", "axis": "محور القرار", "branch_name": "اسم الفرع",
    "card_id": "معرّف البطاقة", "card_type_code": "نوع البطاقة", "cause_code": "سبب العائق",
    "cause_resolution": "توضيح سبب العائق", "certificate": "الشهادة", "check_code": "رمز الفحص",
    "check_method": "طريقة التحقق", "charter": "ميثاق الجلسة", "checksum_sha256": "بصمة SHA-256",
    "actor_username": "مستخدم الإدارة", "action_code": "نوع التغيير", "table_name": "الجدول المتأثر",
    "record_key": "معرّف السجل", "field_name": "الحقل", "original_text": "النص الأصلي المحفوظ",
    "localized_text": "النص العربي المعروض", "localized_at": "وقت التعريب",
    "closed_at": "وقت الإغلاق", "codex_session_id": "معرّف جلسة Codex",
    "command_code": "رمز الأمر", "commit_sha": "معرّف الالتزام", "context_cache_write_input_tokens": "توكنز كتابة الذاكرة المؤقتة",
    "context_cached_input_tokens": "توكنز الإدخال من الذاكرة المؤقتة", "context_input_tokens": "توكنز الإدخال",
    "context_output_tokens": "توكنز الإخراج", "context_reasoning_output_tokens": "توكنز الاستدلال",
    "context_total_tokens": "إجمالي توكنز السياق", "context_used_percent": "نسبة استخدام السياق",
    "context_window_tokens": "سعة نافذة السياق", "correlation_id": "معرّف الترابط",
    "created_at": "تاريخ الإنشاء", "current_status_code": "الحالة الحالية",
    "current_status_version": "إصدار الحالة", "cumulative_cached_input_tokens": "إجمالي توكنز الإدخال المخزّن",
    "cumulative_input_tokens": "إجمالي توكنز الإدخال", "cumulative_output_tokens": "إجمالي توكنز الإخراج",
    "cumulative_reasoning_output_tokens": "إجمالي توكنز الاستدلال", "cumulative_total_tokens": "إجمالي التوكنز التراكمي",
    "definition_version": "إصدار التعريف", "deliverable_id": "معرّف المخرج", "description": "الوصف",
    "details": "تفاصيل الحدث", "display_name": "الاسم المعروض", "duration_ms": "المدة بالمللي ثانية",
    "due_at": "الموعد النهائي", "effective_at": "تاريخ السريان", "enabled": "مفعّل",
    "ended_at": "وقت انتهاء الإسناد", "event_id": "معرّف الحدث", "event_type": "نوع الحدث",
    "evidence_ref": "مرجع الدليل", "finished_at": "وقت الانتهاء", "from_status_code": "الحالة السابقة",
    "idempotency_key": "مفتاح منع التكرار", "impact_summary": "ملخص الأثر", "kind": "نوع المخرج",
    "last_error_code": "رمز آخر خطأ", "locked_until": "موعد انتهاء القفل", "message_code": "رمز الرسالة",
    "model": "النموذج", "name": "الاسم", "next_status": "الحالة التالية", "notes": "ملاحظات",
    "observed_at": "وقت الرصد", "opinion": "الرأي", "opinion_history_id": "معرّف سجل الرأي",
    "opinion_id": "معرّف الرأي", "outcome": "النتيجة", "owner_actor_id": "المالك",
    "owner_request": "طلب المالك", "parent_card_id": "معرّف البطاقة الأم", "path": "المسار",
    "priority_code": "الأولوية", "profile_code": "رمز خطة الفحص", "provider_code": "مزود الجلسة",
    "quality_run_id": "معرّف جولة الجودة", "reason_code": "رمز السبب", "reason_resolution": "توضيح السبب",
    "recommendation": "التوصية", "recorded_at": "وقت التسجيل", "relation": "نوع العلاقة",
    "remote_commit_sha": "معرّف الالتزام على البعيد", "remote_message_id": "معرّف الرسالة البعيدة",
    "remote_name": "اسم المستودع البعيد", "required": "إلزامي", "resolved_at": "وقت الحل",
    "integration_id": "معرّف التكامل", "repository": "المستودع", "base_branch": "الفرع الأساس",
    "head_branch": "فرع المهمة", "head_sha": "التزام فرع المهمة", "pull_request_number": "رقم PR",
    "pull_request_url": "رابط PR", "base_sha": "التزام الفرع الأساس", "merge_sha": "التزام الدمج",
    "local_main_sha": "التزام main المحلي", "remote_main_sha": "التزام main البعيد",
    "resolved_by_actor_id": "الجهة التي عالجت العائق", "root_card_id": "معرّف البطاقة الأصلية",
    "runner_name": "اسم مشغّل الفحص", "runner_version": "إصدار مشغّل الفحص",
    "sample_id": "معرّف العينة", "sampled_at": "وقت أخذ العينة", "scope": "النطاق",
    "scope_result": "نتيجة فحص النطاق", "sensitivity": "مستوى الحساسية", "service_tier": "فئة الخدمة",
    "session_id": "معرّف الجلسة", "session_name": "اسم الجلسة", "source_event_id": "معرّف الحدث المصدر",
    "source_id": "معرّف المصدر", "source_path": "مسار المصدر", "source_type": "نوع المصدر",
    "stage_code": "مرحلة الفلو", "started_at": "وقت البدء", "state_code": "الحالة",
    "status": "الحالة", "status_code": "رمز الحالة", "summary": "الملخص", "title": "العنوان",
    "to_status_code": "الحالة التالية", "terminal": "حالة نهائية", "thread_id": "معرّف الجلسة الخارجية",
    "updated_at": "آخر تحديث", "used_percent": "نسبة الاستخدام", "validator_actor_id": "جهة التحقق",
    "validation_id": "معرّف نتيجة التحقق", "verified_at": "وقت التحقق", "version": "الإصدار",
    "weekly_plan_type": "نوع الخطة الأسبوعية", "weekly_remaining_percent": "نسبة الحصة المتبقية",
    "weekly_resets_at": "موعد تجديد الحصة", "weekly_used_percent": "نسبة الحصة المستخدمة",
    "weekly_window_minutes": "مدة نافذة الحصة بالدقائق", "workflow_stage_code": "مرحلة الفلو",
    "actor_id": "الجلسة أو الجهة", "capability": "القدرة", "criterion_code": "رمز المعيار",
    "category_code": "فئة المعيار", "default_required": "مطلوب افتراضيًا",
    "criterion_id": "معرّف المعيار", "decision": "قرار المالك", "decision_history_id": "معرّف سجل القرار",
    "decision_id": "معرّف القرار", "depends_on_card_id": "البطاقة المرتبطة", "event_id": "معرّف الحدث",
    "from_status_code": "من الحالة", "to_status_code": "إلى الحالة", "key": "المفتاح",
    "value": "القيمة", "sort_order": "ترتيب العرض", "stage_code": "مرحلة الفلو",
    "opinion_history_id": "معرّف سجل الرأي", "decision_history_id": "معرّف سجل القرار",
    "decision_id": "معرّف القرار", "delivery_path_id": "معرّف مسار التسليم",
    "git_event_id": "معرّف حدث Git", "issue_id": "معرّف العائق", "attempt_id": "معرّف المحاولة",
    "outbox_id": "معرّف سجل الإرسال", "check_id": "معرّف فحص الجودة", "check_code": "رمز الفحص",
    "quality_run_id": "معرّف جولة الجودة", "validation_id": "معرّف نتيجة التحقق",
    "decision_history_id": "معرّف سجل القرار", "decision_id": "معرّف القرار",
    "reason_code": "رمز السبب", "recorded_at": "وقت التسجيل", "decided_at": "وقت القرار",
    "decided_by_actor_id": "صاحب القرار", "assigned_at": "وقت الإسناد", "ended_at": "وقت الانتهاء",
    "provider_code": "مزود الخدمة", "source_event_id": "الحدث المصدر", "related_event_id": "الحدث المرتبط",
    "stage_code": "مرحلة الفلو", "previous_status": "الحالة السابقة", "next_status": "الحالة التالية",
    "outcome": "النتيجة", "attempt_count": "عدد المحاولات", "sent_at": "وقت الإرسال",
    "created_at": "تاريخ الإنشاء", "updated_at": "آخر تحديث", "resolved_at": "وقت الحل",
    "observed_at": "وقت الرصد", "finished_at": "وقت الانتهاء", "started_at": "وقت البدء",
    "applied_at": "وقت التطبيق", "retired_at": "وقت الإيقاف", "submitted_at": "وقت التسليم",
    "submitted_by_actor_id": "الجهة المسلّمة", "remote_message_id": "معرّف الرسالة الخارجية",
    "role_code": "دور البطاقة", "provider_code": "مزود الجلسة", "state_code": "حالة الإرسال",
    "action": "الإجراء", "remote_name": "المستودع البعيد", "profile_code": "ملف الفحص",
    "runner_name": "مشغّل الفحص", "runner_version": "إصدار المشغّل", "resolution": "المعالجة",
    "event_id": "معرّف الحدث", "card_type_code": "نوع البطاقة", "coordinator_actor_id": "منسق البطاقة",
    "created_at": "وقت الإنشاء", "updated_at": "وقت التحديث", "closed_at": "وقت الإغلاق",
    "started_at": "وقت البدء", "due_at": "الموعد النهائي", "owner_request": "طلب المالك",
    "scope": "نطاق المهمة", "current_status_code": "الحالة الحالية", "current_status_version": "إصدار الحالة الحالية",
    "reason_resolution": "شرح السبب", "previous_decision": "القرار السابق", "axis": "محور القرار",
    "decided_by_actor_id": "صاحب القرار", "source_path": "مسار المصدر", "offset_bytes": "موضع القراءة بالبايت",
    "reasoning_effort": "مستوى التفكير", "context_cache_write_input_tokens": "توكنز كتابة الذاكرة",
    "context_cached_input_tokens": "توكنز الذاكرة المستخدمة", "context_output_tokens": "توكنز الإخراج",
    "context_reasoning_output_tokens": "توكنز الاستدلال", "weekly_resets_at": "موعد تجديد الحصة",
    "weekly_window_minutes": "نافذة الحصة بالدقائق", "weekly_plan_type": "نوع الخطة",
    "weekly_remaining_percent": "الحصة المتبقية", "weekly_used_percent": "الحصة المستخدمة",
    "assignment_id": "معرّف الإسناد", "category": "فئة السبب",
    "coordination_card_id": "البطاقة المرتبطة بالعينة", "criterion": "معيار التحقق",
    "cumulative_cache_write_input_tokens": "إجمالي توكنز كتابة الذاكرة",
    "target_actor_id": "الجهة المستهدفة",
    "proposal_id": "معرّف اقتراح المتابعة", "source_card_id": "البطاقة الأصلية",
    "source_opinion_history_id": "نسخة الرأي المرتبطة", "proposed_by_actor_id": "الجلسة المقترحة",
    "rationale": "سبب الاقتراح", "suggested_assignee_actor_id": "الجلسة المقترحة للتنفيذ",
    "status_code": "حالة الاقتراح", "decision_notes": "ملاحظة قرار المالك",
    "issued_root_card_id": "أمر المالك الصادر", "request_hash_sha256": "بصمة طلب منع التكرار",
    "proposal_criterion_id": "معرّف معيار الاقتراح",
}

DATETIME_COLUMNS = {
    "applied_at", "assigned_at", "available_at", "closed_at", "created_at", "decided_at",
    "ended_at", "finished_at", "locked_until", "observed_at", "recorded_at", "resolved_at",
    "retired_at", "sampled_at", "sent_at", "started_at", "submitted_at", "updated_at", "verified_at",
}
UNIX_DATETIME_COLUMNS = {"weekly_resets_at"}
BOOLEAN_COLUMNS = {"active", "enabled", "required", "terminal"}


class UnixTimestampField(models.IntegerField):
    """Expose an epoch-seconds SQLite integer as a localized datetime."""

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return datetime.fromtimestamp(float(value), tz=datetime_timezone.utc)

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None:
            return None
        if isinstance(value, datetime):
            return int(value.timestamp())
        return super().get_db_prep_value(value, connection, prepared)

    def formfield(self, **kwargs):
        kwargs.setdefault("form_class", forms.DateTimeField)
        return super().formfield(**kwargs)


_SQLITE_TYPES = (
    ("INT", models.BigIntegerField),
    ("REAL", models.FloatField),
    ("FLOA", models.FloatField),
    ("DOUB", models.FloatField),
    ("BLOB", models.BinaryField),
)


def _make_admin_models() -> dict[str, type[models.Model]]:
    database = Path(settings.USAGE_DATABASE)
    if not database.is_file():
        return {}

    uri = f"file:{database.as_posix()}?mode=ro"
    generated: dict[str, type[models.Model]] = {}
    with sqlite3.connect(uri, uri=True) as connection:
        available = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table_name, label in ADMIN_TABLES.items():
            if table_name not in available:
                continue
            columns = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            primary_keys = [column for column in columns if column[5]]
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            ).fetchone()[0] or ""
            if len(primary_keys) != 1 and "WITHOUT ROWID" in sql.upper():
                continue

            attributes: dict[str, object] = {"__module__": __name__}
            for column in columns:
                name, sql_type, not_null, is_primary_key = column[1], (column[2] or "").upper(), column[3], column[5]
                if name in UNIX_DATETIME_COLUMNS:
                    field_type = UnixTimestampField
                elif name in DATETIME_COLUMNS:
                    field_type = models.DateTimeField
                elif name in BOOLEAN_COLUMNS:
                    field_type = models.BooleanField
                else:
                    field_type = models.TextField
                    for type_marker, candidate in _SQLITE_TYPES:
                        if type_marker in sql_type:
                            field_type = candidate
                            break
                attributes[name] = field_type(
                    primary_key=bool(is_primary_key) if len(primary_keys) == 1 else False,
                    null=not bool(not_null or is_primary_key),
                    blank=not bool(not_null or is_primary_key),
                    verbose_name=FIELD_LABELS.get(name, f"بيانات {name.replace('_', ' ')}"),
                )
            if len(primary_keys) != 1:
                attributes["admin_rowid"] = models.AutoField(
                    primary_key=True, db_column="rowid", auto_created=True,
                    verbose_name="معرّف السجل",
                )

            class Meta:
                app_label = "workflow_admin"
                db_table = table_name
                managed = False
                verbose_name = label
                verbose_name_plural = label
                default_permissions = (("add", "change", "delete", "view")
                                       if table_name == "workflow_criterion_catalog" else ("view",))

            attributes["Meta"] = Meta
            generated[table_name] = type(f"Admin_{table_name}", (models.Model,), attributes)
    return generated


ADMIN_MODELS = _make_admin_models()
globals().update({model.__name__: model for model in ADMIN_MODELS.values()})
