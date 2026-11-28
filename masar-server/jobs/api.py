from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Query, Router, Schema

from accounts.permissions import require_password_changed, session_auth
from jobs import services

jobs_router = Router(auth=session_auth)


class JobOut(Schema):
    id: UUID
    project_id: UUID | None
    kind: str
    inputs: dict
    status: str
    step: int
    total: int
    phase: str
    cancel_requested: bool
    result: str | None
    result_meta: dict
    error: str
    review: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @staticmethod
    def resolve_result(job):
        # The sha256, for GET /api/assets/{sha256}.
        return job.result.sha256 if job.result else None


class NewJob(Schema):
    inputs: dict
    idempotency_key: UUID
    project_id: UUID | None = None
    kind: Literal['generate'] = 'generate'


class ReviewIn(Schema):
    review: Literal['pending', 'accepted', 'rejected', 'revise']


@jobs_router.post('', response={200: JobOut, 201: JobOut})
def create_job(request, body: NewJob):
    require_password_changed(request)
    job, created = services.create_job(owner=request.user, inputs=body.inputs, key=body.idempotency_key,
                                       project_id=body.project_id, kind=body.kind, request=request)
    return (201 if created else 200), job


@jobs_router.get('', response=list[JobOut])
def list_jobs(request, project: UUID | None = None, limit: int = Query(50, ge=1, le=200),
              offset: int = Query(0, ge=0, le=1_000_000)):
    require_password_changed(request)
    return services.list_jobs(request.user, project_id=project, limit=limit, offset=offset)


@jobs_router.get('/{job_id}', response=JobOut)
def get_job(request, job_id: UUID):
    require_password_changed(request)
    return services.get_job(request.user, job_id)


@jobs_router.post('/{job_id}/cancel', response=JobOut)
def cancel_job(request, job_id: UUID):
    require_password_changed(request)
    return services.cancel_job(owner=request.user, job_id=job_id, request=request)


@jobs_router.post('/{job_id}/review', response=JobOut)
def review_job(request, job_id: UUID, body: ReviewIn):
    require_password_changed(request)
    return services.review_job(owner=request.user, job_id=job_id, review=body.review)
