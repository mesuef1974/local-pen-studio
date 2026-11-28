from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.http import FileResponse
from ninja import Field, Router, Schema

from accounts.errors import DomainError
from accounts.permissions import require_password_changed, session_auth
from projects import services, storage

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
