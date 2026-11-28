import uuid

from django.conf import settings
from django.db import models


class Asset(models.Model):
    """One uploaded file of one user. The bytes live on disk, named by their sha256."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assets')
    sha256 = models.CharField(max_length=64)
    content_type = models.CharField(max_length=20)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Per owner: one user must not learn that another already holds the same file.
        constraints = [models.UniqueConstraint(fields=['owner', 'sha256'], name='asset_owner_sha256')]


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='projects')
    title = models.CharField(max_length=150)
    # The studio's work snapshot. Images are "asset:<sha256>" references, never inline.
    state = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)
    # Set by the client so that retrying a create (or the one-time import) makes one project.
    client_key = models.UUIDField(null=True)
    assets = models.ManyToManyField(Asset, related_name='projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['owner', 'client_key'], name='project_owner_client_key')]
