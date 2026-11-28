from datetime import datetime

from ninja import Query, Router, Schema

from accounts.permissions import require_supervisor, session_auth
from audit.models import AuditEvent

audit_router = Router(auth=session_auth)


class EventOut(Schema):
    id: int
    actor_username: str
    action: str
    target_type: str
    target_id: str
    ip_address: str | None
    detail: dict
    created_at: datetime


@audit_router.get('', response=list[EventOut])
def list_events(request, limit: int = Query(50, ge=1, le=200), before: int | None = None):
    require_supervisor(request)
    events = AuditEvent.objects.all()
    if before is not None:
        events = events.filter(id__lt=before)
    return list(events[:limit])
