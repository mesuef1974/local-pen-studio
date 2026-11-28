"""Project and asset rules. Every lookup is scoped to the owner."""
import hashlib
import json
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.errors import DomainError
from audit import services as audit
from projects import storage
from projects.models import Asset, Project

ASSET_REF = re.compile(r'asset:([0-9a-f]{64})')
EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}


def _image_type(data):
    """Trust the bytes, not the declared Content-Type."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def store_asset(owner, data):
    """Idempotent: the same bytes from the same owner give the same asset."""
    content_type = _image_type(data)
    if content_type is None:
        raise DomainError('unsupported_file', 'المقبول صور PNG أو JPEG أو WebP.', 415)
    sha256 = hashlib.sha256(data).hexdigest()
    storage.write(sha256, data)
    asset, _ = Asset.objects.get_or_create(owner=owner, sha256=sha256,
                                           defaults={'content_type': content_type, 'size': len(data)})
    return asset


def get_asset(owner, sha256):
    # Checked before the query: PostgreSQL text cannot hold NUL.
    asset = None
    if re.fullmatch(r'[0-9a-f]{64}', sha256):
        asset = Asset.objects.filter(owner=owner, sha256=sha256).first()
    if asset is None:
        raise DomainError('not_found', 'الملف غير موجود.', 404)
    return asset


def _clean_title(title):
    title = title.strip()
    if not 1 <= len(title) <= 150 or '\x00' in title:
        raise DomainError('invalid_title', 'اكتب عنوانًا (حتى 150 حرفًا).')
    return title


def _live(owner):
    return Project.objects.filter(owner=owner, deleted_at__isnull=True)


def list_projects(owner):
    return list(_live(owner).defer('state'))


def get_project(owner, project_id, *, lock=False):
    query = _live(owner).select_for_update() if lock else _live(owner)
    project = query.filter(pk=project_id).first()
    if project is None:
        # The same answer for missing, deleted and someone else's project.
        raise DomainError('not_found', 'المشروع غير موجود.', 404)
    return project


def create_project(*, owner, title, client_key=None, request=None):
    title = _clean_title(title)
    with transaction.atomic():
        if client_key is None:
            project, created = Project.objects.create(owner=owner, title=title), True
        else:
            project, created = Project.objects.get_or_create(owner=owner, client_key=client_key,
                                                             defaults={'title': title})
        if project.deleted_at is not None:
            raise DomainError('project_deleted', 'هذا المشروع محذوف.', 409)
        if created:
            audit.record('project.created', actor=owner, target=project, request=request)
    return project, created


def rename_project(*, owner, project_id, title):
    title = _clean_title(title)
    with transaction.atomic():
        project = get_project(owner, project_id, lock=True)
        if project.title != title:
            project.title = title
            project.save(update_fields=['title', 'updated_at'])
    return project


def _canonical(value):
    # Python calls 1, 1.0 and True equal; as saved work they are different.
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def parse_state(raw):
    """Parse a snapshot strictly enough that PostgreSQL JSONB will accept it."""
    def reject(_):
        raise ValueError('non-finite number')

    try:
        body = json.loads(raw.decode('utf-8'), parse_constant=reject)
        revision, state = body['revision'], body['state']
        # Re-encoding finds NUL, lone surrogates and 1e999 wherever they hide.
        encoded = json.dumps(state, ensure_ascii=False, allow_nan=False)
        encoded.encode('utf-8')
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise DomainError('invalid_state', 'بيانات المشروع غير صالحة.') from error
    if type(revision) is not int or not isinstance(state, dict) or re.search(r'(?<!\\)(\\\\)*\\u0000', encoded):
        raise DomainError('invalid_state', 'بيانات المشروع غير صالحة.')
    if 'data:image/' in encoded:
        raise DomainError('inline_image', 'ارفع الصور ملفات وأشر إليها، لا تضمّنها.')
    return revision, state, set(ASSET_REF.findall(encoded))


def save_state(*, owner, project_id, raw):
    """Optimistic concurrency: a stale revision is refused, an identical resend is a no-op."""
    if len(raw) > settings.MAX_STATE_BYTES:
        raise DomainError('too_large', 'بيانات المشروع أكبر من المسموح.', 413)
    revision, state, refs = parse_state(raw)
    with transaction.atomic():
        project = get_project(owner, project_id, lock=True)
        if _canonical(project.state) == _canonical(state):
            return project
        if project.revision != revision:
            raise DomainError('stale_revision', 'حُفظ المشروع من مكان آخر. أعد فتحه.', 409)
        assets = list(Asset.objects.filter(owner=owner, sha256__in=refs))
        if len(assets) != len(refs):
            raise DomainError('unknown_asset', 'المشروع يشير إلى ملف لم يُرفع.')
        project.state = state
        project.revision += 1
        project.save(update_fields=['state', 'revision', 'updated_at'])
        project.assets.set(assets)
    return project


def delete_project(*, owner, project_id, request=None):
    """Soft delete: rows and files stay until a purge policy exists."""
    with transaction.atomic():
        project = get_project(owner, project_id, lock=True)
        project.deleted_at = timezone.now()
        project.save(update_fields=['deleted_at', 'updated_at'])
        audit.record('project.deleted', actor=owner, target=project, request=request)
