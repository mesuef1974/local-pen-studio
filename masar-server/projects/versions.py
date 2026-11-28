"""Image versions and their approval. Every lookup goes through the owner's live project."""
from django.db import transaction

from accounts.errors import DomainError
from audit import services as audit
from projects import services as projects
from projects.models import Approval, ImageVersion, Source


def _versions(project):
    return project.versions.select_related('asset').prefetch_related('approvals__approved_by')


def _find(project, version_id):
    version = _versions(project).filter(pk=version_id).first()
    if version is None:
        raise DomainError('not_found', 'النسخة غير موجودة.', 404)
    return version


def list_versions(*, owner, project_id):
    return list(_versions(projects.get_project(owner, project_id)))


def get_version(*, owner, project_id, version_id):
    return _find(projects.get_project(owner, project_id), version_id)


def create_version(*, owner, project_id, sha256, source, parent_id=None, request=None):
    """Idempotent: the same picture, source and parent in a project are one version."""
    source = Source(source)
    with transaction.atomic():
        # The project lock keeps two identical requests from making two versions.
        project = projects.get_project(owner, project_id, lock=True)
        asset = projects.get_asset(owner, sha256)
        parent = None if parent_id is None else _find(project, parent_id)
        version = _versions(project).filter(asset=asset, source=source, parent=parent).first()
        if version is not None:
            return version, False
        version = ImageVersion.objects.create(project=project, asset=asset, source=source, parent=parent)
        audit.record('version.created', actor=owner, target=version, request=request,
                     detail={'project': str(project.pk), 'source': source.value})
    return version, True


def approve_version(*, owner, project_id, version_id, request=None):
    """Idempotent: approving again returns the first approval."""
    with transaction.atomic():
        project = projects.get_project(owner, project_id, lock=True)
        version = _find(project, version_id)
        approval, created = Approval.objects.get_or_create(version=version, approved_by=owner)
        if created:
            audit.record('version.approved', actor=owner, target=version, request=request,
                         detail={'project': str(project.pk)})
    return approval, created
