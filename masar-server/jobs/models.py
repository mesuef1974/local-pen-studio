import uuid

from django.conf import settings
from django.db import models

from projects.models import Asset, Project


class Status(models.TextChoices):
    QUEUED = 'queued'
    RUNNING = 'running'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class Review(models.TextChoices):
    """The same four values the studio's history shows."""

    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    REVISE = 'revise'


class Kind(models.TextChoices):
    GENERATE = 'generate'


class Job(models.Model):
    """One request for local compute and what came of it. Rows are kept, never deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='jobs')
    project = models.ForeignKey(Project, null=True, on_delete=models.PROTECT, related_name='jobs')
    kind = models.CharField(max_length=20, choices=Kind, default=Kind.GENERATE)
    # What was asked. Images are "asset:<sha256>" references, also listed in `assets`.
    inputs = models.JSONField(default=dict)
    assets = models.ManyToManyField(Asset, related_name='input_of_jobs')
    result = models.ForeignKey(Asset, null=True, on_delete=models.PROTECT, related_name='result_of_jobs')
    # Seed, time, effective prompt and whatever else the engine reports, without the image.
    result_meta = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status, default=Status.QUEUED)
    step = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    phase = models.CharField(max_length=20, blank=True)
    cancel_requested = models.BooleanField(default=False)
    idempotency_key = models.UUIDField()
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    review = models.CharField(max_length=10, choices=Review, default=Review.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    heartbeat_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'], name='job_status_created')]
        constraints = [
            models.UniqueConstraint(fields=['owner', 'idempotency_key'], name='job_owner_key'),
            # One GPU: the database itself refuses a second running job.
            models.UniqueConstraint(fields=['status'], condition=models.Q(status=Status.RUNNING),
                                    name='job_one_running'),
        ]
