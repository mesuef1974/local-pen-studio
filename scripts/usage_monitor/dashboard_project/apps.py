"""Application registration for read-only workflow administration."""

from django.apps import AppConfig


class DashboardProjectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard_project"
    label = "workflow_admin"
    verbose_name = "بيانات الفلو والاستخدام"
