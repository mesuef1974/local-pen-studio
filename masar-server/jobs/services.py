"""Job rules. Owner actions are scoped to the owner; the worker functions are not reachable over HTTP."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.errors import DomainError
from audit import services as audit
from jobs.models import Job, Kind, Review, Status
from projects import services as projects
from projects.models import Asset

# The keys the FLUX engine accepts. The worker validates their values with the engine's own rules.
INPUT_KEYS = {'image', 'style', 'prompt', 'resolution', 'seed', 'mode', 'references', 'aspect', 'controls',
              'preserve'}
MAX_REFERENCES = 2


def _invalid():
    return DomainError('invalid_inputs', 'طلب التوليد غير صالح.')


def _image_hash(value):
    match = projects.ASSET_REF.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise _invalid()
    return match[1]


def _input_hashes(inputs):
    """The sha256 of every image the inputs name."""
    encoded = projects.storable_json(inputs)
    if encoded is None or not isinstance(inputs, dict) or set(inputs) - INPUT_KEYS:
        raise _invalid()
    if 'data:image/' in encoded:
        raise DomainError('inline_image', 'ارفع الصور ملفات وأشر إليها، لا تضمّنها.')
    mode, image, references = inputs.get('mode', 'edit'), inputs.get('image'), inputs.get('references', [])
    if mode not in ('edit', 'generate', 'multi') or not isinstance(references, list):
        raise _invalid()
    if mode == 'generate':
        if image is not None or references:
            raise _invalid()
        return set()
    if len(references) > MAX_REFERENCES:
        raise _invalid()
    hashes = {_image_hash(image)}
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {'image', 'role'}:
            raise _invalid()
        hashes.add(_image_hash(reference['image']))
    return hashes


def _same_request(job, kind, project_id, inputs):
    return (job.kind, job.project_id) == (kind, project_id) and (
        projects.storable_json(job.inputs, canonical=True) == projects.storable_json(inputs, canonical=True))


def create_job(*, owner, inputs, key, project_id=None, kind=Kind.GENERATE, request=None):
    """Idempotent per owner and key: a resend returns the first job, even when the queue is full."""
    hashes = _input_hashes(inputs)
    with transaction.atomic():
        # Locking the account row makes the key lookup and the queue limit safe against parallel requests.
        get_user_model().objects.select_for_update().get(pk=owner.pk)
        job = _owned(owner).filter(idempotency_key=key).first()
        if job is not None:
            if not _same_request(job, kind, project_id, inputs):
                raise DomainError('key_reused', 'استُعمل مفتاح الطلب لطلب آخر.', 409)
            return job, False
        project = None if project_id is None else projects.get_project(owner, project_id)
        if _owned(owner).filter(status=Status.QUEUED).count() >= settings.MAX_QUEUED_JOBS:
            raise DomainError('queue_full', 'في الانتظار ثلاث مهام. انتظر أو ألغِ إحداها.', 429)
        assets = list(Asset.objects.filter(owner=owner, sha256__in=hashes))
        if len(assets) != len(hashes):
            raise DomainError('unknown_asset', 'الطلب يشير إلى ملف لم يُرفع.')
        job = Job.objects.create(owner=owner, project=project, kind=kind, inputs=inputs, idempotency_key=key)
        job.assets.set(assets)
        audit.record('job.created', actor=owner, target=job, request=request)
    return job, True


def _owned(owner):
    return Job.objects.filter(owner=owner).select_related('result')


def list_jobs(owner, *, project_id=None, limit=50, offset=0):
    query = _owned(owner)
    if project_id is not None:
        query = query.filter(project=projects.get_project(owner, project_id))
    return list(query[offset:offset + limit])


def get_job(owner, job_id, *, lock=False):
    query = _owned(owner)
    if lock:
        query = query.select_for_update(of=('self',))
    job = query.filter(pk=job_id).first()
    if job is None:
        raise DomainError('not_found', 'المهمة غير موجودة.', 404)
    return job


def cancel_job(*, owner, job_id, request=None):
    """A queued job stops at once; a running one is asked to stop. Finished jobs are left alone."""
    with transaction.atomic():
        job = get_job(owner, job_id, lock=True)
        if job.status == Status.QUEUED:
            job.status, job.finished_at = Status.CANCELLED, timezone.now()
        elif job.status != Status.RUNNING or job.cancel_requested:
            return job
        job.cancel_requested = True
        job.save(update_fields=['status', 'finished_at', 'cancel_requested'])
        audit.record('job.cancelled', actor=owner, target=job, request=request)
    return job


def review_job(*, owner, job_id, review):
    with transaction.atomic():
        job = get_job(owner, job_id, lock=True)
        if job.status != Status.SUCCEEDED:
            raise DomainError('no_result', 'لا نتيجة لتقييمها.', 409)
        job.review = Review(review)
        job.save(update_fields=['review'])
    return job


# Worker side. `attempt` is the number claim_next gave: a worker whose job was taken back is refused.

def _finish(job, status, **changes):
    changes.update(status=status, finished_at=timezone.now())
    for name, value in changes.items():
        setattr(job, name, value)
    job.save(update_fields=list(changes))


def _recover_silent():
    cutoff = timezone.now() - timedelta(seconds=settings.JOB_HEARTBEAT_TIMEOUT)
    silent = Job.objects.select_for_update(skip_locked=True).filter(status=Status.RUNNING, heartbeat_at__lt=cutoff)
    for job in silent:
        if job.cancel_requested:
            _finish(job, Status.CANCELLED)
        elif job.attempts < settings.MAX_JOB_ATTEMPTS:
            job.status, job.step, job.total, job.phase = Status.QUEUED, 0, 0, ''
            job.save(update_fields=['status', 'step', 'total', 'phase'])
        else:
            _finish(job, Status.FAILED, error='انقطعت عملية المعالجة ولم تكتمل.')


def claim_next():
    """Take the oldest queued job, or None when there is none or one is already running."""
    with transaction.atomic():
        _recover_silent()
    try:
        with transaction.atomic():
            if Job.objects.filter(status=Status.RUNNING).exists():
                return None
            job = (Job.objects.select_for_update(skip_locked=True).filter(status=Status.QUEUED)
                   .order_by('created_at').first())
            if job is None:
                return None
            job.status, job.attempts = Status.RUNNING, job.attempts + 1
            job.started_at = job.heartbeat_at = timezone.now()
            job.save(update_fields=['status', 'attempts', 'started_at', 'heartbeat_at'])
    except IntegrityError:  # another worker claimed first: job_one_running
        return None
    return job


def _held(job_id, attempt):
    return Job.objects.select_for_update().filter(pk=job_id, status=Status.RUNNING, attempts=attempt).first()


def heartbeat(job_id, attempt, *, step=None, total=None, phase=None):
    """Record that the worker is alive. Returns True when the owner asked to cancel."""
    with transaction.atomic():
        job = _held(job_id, attempt)
        if job is None:
            raise DomainError('job_lost', 'لم تعد المهمة عند هذه العملية.', 409)
        changes = {name: value for name, value in (('step', step), ('total', total), ('phase', phase))
                   if value is not None}
        Job.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now(), **changes)
    return job.cancel_requested


def complete(job_id, attempt, image, meta):
    """Store the result. A cancel that arrived first wins and the image is dropped."""
    with transaction.atomic():
        job = _held(job_id, attempt)
        if job is None:
            return False
        if job.cancel_requested:
            _finish(job, Status.CANCELLED)
        else:
            _finish(job, Status.SUCCEEDED, result=projects.store_asset(job.owner, image), result_meta=meta)
    return True


def fail(job_id, attempt, error):
    with transaction.atomic():
        job = _held(job_id, attempt)
        if job is None:
            return False
        if job.cancel_requested:
            _finish(job, Status.CANCELLED)
        else:
            _finish(job, Status.FAILED, error=error[:500])
    return True
