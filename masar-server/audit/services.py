from audit.models import AuditEvent


def client_address(request):
    # REMOTE_ADDR only: forwarded headers are forgeable until a trusted proxy exists (phase 5).
    return (request.META.get('REMOTE_ADDR') or None) if request else None


def record(action, *, actor=None, target=None, request=None, detail=None):
    """Callers pass only non-secret detail: never passwords, tokens or images."""
    return AuditEvent.objects.create(
        action=action,
        actor_id=actor.pk if actor else None,
        actor_username=actor.username if actor else '',
        target_type=type(target).__name__ if target else '',
        target_id=str(target.pk) if target else '',
        ip_address=client_address(request),
        detail=detail or {},
    )
