from datetime import datetime
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.http import FileResponse
from ninja import Field, Router, Schema

from accounts.errors import DomainError
from accounts.permissions import require_password_changed, session_auth
from projects import services, storage, versions

projects_router = Router(auth=session_auth)
assets_router = Router(auth=session_auth)


class ProjectSummary(Schema):
    id: UUID
    title: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ProjectOut(ProjectSummary):
    state: dict


class NewProject(Schema):
    title: str = Field(..., max_length=200)
    client_key: UUID | None = None


class Title(Schema):
    title: str = Field(..., max_length=200)


class AssetOut(Schema):
    sha256: str
    content_type: str
    size: int


class ApprovalOut(Schema):
    id: UUID
    approved_by: str
    created_at: datetime

    @staticmethod
    def resolve_approved_by(approval):
        return approval.approved_by.username


class VersionOut(Schema):
    id: UUID
    asset: str
    source: str
    parent_id: UUID | None
    approvals: list[ApprovalOut]
    created_at: datetime

    @staticmethod
    def resolve_asset(version):
        # The sha256, for GET /api/assets/{sha256}.
        return version.asset.sha256

    @staticmethod
    def resolve_approvals(version):
        return list(version.approvals.all())


class NewVersion(Schema):
    asset: str = Field(..., max_length=64)
    source: Literal['upload', 'generate', 'prepare']
    parent_id: UUID | None = None


def _read_body(request, limit):
    """Read at most limit bytes. runserver still drains the rest: a deployment must cap bodies upstream."""
    data = request.read(limit + 1)
    if len(data) > limit:
        raise DomainError('too_large', 'الملف أكبر من المسموح.', 413)
    if len(data) < int(request.META.get('CONTENT_LENGTH') or 0):
        raise DomainError('incomplete_body', 'انقطع الرفع. أعد المحاولة.')
    return data


@projects_router.get('', response=list[ProjectSummary])
def list_projects(request):
    require_password_changed(request)
    return services.list_projects(request.user)


@projects_router.post('', response={200: ProjectOut, 201: ProjectOut})
def create_project(request, body: NewProject):
    require_password_changed(request)
    project, created = services.create_project(owner=request.user, title=body.title,
                                               client_key=body.client_key, request=request)
    return (201 if created else 200), project


@projects_router.get('/{project_id}', response=ProjectOut)
def get_project(request, project_id: UUID):
    require_password_changed(request)
    return services.get_project(request.user, project_id)


@projects_router.post('/{project_id}/rename', response=ProjectSummary)
def rename_project(request, project_id: UUID, body: Title):
    require_password_changed(request)
    return services.rename_project(owner=request.user, project_id=project_id, title=body.title)


@projects_router.post('/{project_id}/state', response=ProjectSummary)
def save_state(request, project_id: UUID):
    # Body: {"revision": n, "state": {...}}, read here because it exceeds the global body limit.
    require_password_changed(request)
    raw = _read_body(request, settings.MAX_STATE_BYTES)
    return services.save_state(owner=request.user, project_id=project_id, raw=raw)


@projects_router.post('/{project_id}/delete', response={204: None})
def delete_project(request, project_id: UUID):
    require_password_changed(request)
    services.delete_project(owner=request.user, project_id=project_id, request=request)
    return 204, None


@projects_router.get('/{project_id}/versions', response=list[VersionOut])
def list_versions(request, project_id: UUID):
    require_password_changed(request)
    return versions.list_versions(owner=request.user, project_id=project_id)


@projects_router.post('/{project_id}/versions', response={200: VersionOut, 201: VersionOut})
def create_version(request, project_id: UUID, body: NewVersion):
    require_password_changed(request)
    version, created = versions.create_version(owner=request.user, project_id=project_id, sha256=body.asset,
                                               source=body.source, parent_id=body.parent_id, request=request)
    return (201 if created else 200), version


@projects_router.get('/{project_id}/versions/{version_id}', response=VersionOut)
def get_version(request, project_id: UUID, version_id: UUID):
    require_password_changed(request)
    return versions.get_version(owner=request.user, project_id=project_id, version_id=version_id)


@projects_router.post('/{project_id}/versions/{version_id}/approve', response={200: ApprovalOut, 201: ApprovalOut})
def approve_version(request, project_id: UUID, version_id: UUID):
    require_password_changed(request)
    approval, created = versions.approve_version(owner=request.user, project_id=project_id,
                                                 version_id=version_id, request=request)
    return (201 if created else 200), approval


@assets_router.post('', response=AssetOut)
def upload_asset(request):
    # Body: the raw image bytes.
    require_password_changed(request)
    return services.store_asset(request.user, _read_body(request, settings.MAX_ASSET_BYTES))


@assets_router.get('/{sha256}')
def download_asset(request, sha256: str):
    require_password_changed(request)
    asset = services.get_asset(request.user, sha256)
    name = f'{asset.sha256}.{services.EXTENSIONS[asset.content_type]}'
    return FileResponse(storage.open_for_read(asset.sha256), content_type=asset.content_type,
                        as_attachment=True, filename=name)
