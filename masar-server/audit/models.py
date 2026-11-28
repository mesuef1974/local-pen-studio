from django.db import models


class AppendOnlyError(RuntimeError):
    pass


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError('audit events cannot be changed')

    def delete(self):
        raise AppendOnlyError('audit events cannot be deleted')


class AuditEvent(models.Model):
    """Who did what, to what, from where. No foreign keys, so history outlives accounts."""

    actor_id = models.UUIDField(null=True)
    actor_username = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=50)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ['-id']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError('audit events cannot be changed')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError('audit events cannot be deleted')
