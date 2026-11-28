"""Rows that are written once: the guard shared by every append-only model."""
from django.db import models


class AppendOnlyError(RuntimeError):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError('these rows cannot be changed')

    def delete(self):
        raise AppendOnlyError('these rows cannot be deleted')


class AppendOnly(models.Model):
    """A model with reverse relations must also set base_manager_name='objects':
    a related manager's add() updates through the base manager, not through save()."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError('these rows cannot be changed')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError('these rows cannot be deleted')
