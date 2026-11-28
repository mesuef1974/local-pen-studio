from django.db import models

from config.appendonly import AppendOnly


class AuditEvent(AppendOnly):
    """Who did what, to what, from where. No foreign keys, so history outlives accounts."""

    actor_id = models.UUIDField(null=True)
    actor_username = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=50)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-id']
