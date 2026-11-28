"""Sign-in rate limit, counted before the password is checked so parallel guesses cannot slip through."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.errors import DomainError
from accounts.models import LoginThrottle


def _keys(username, address):
    return [(f'user:{username}', settings.LOGIN_FAILURE_LIMIT_PER_USER),
            (f'ip:{address or "unknown"}', settings.LOGIN_FAILURE_LIMIT_PER_ADDRESS)]


def reserve(username, address):
    now = timezone.now()
    window = timedelta(seconds=settings.LOGIN_WINDOW_SECONDS)
    with transaction.atomic():
        for key, limit in _keys(username, address):
            row, _ = LoginThrottle.objects.select_for_update().get_or_create(
                key=key, defaults={'window_started_at': now})
            if now - row.window_started_at >= window:
                row.attempts, row.window_started_at = 0, now
            if row.attempts >= limit:
                raise DomainError('throttled', 'محاولات كثيرة. انتظر ربع ساعة ثم أعد المحاولة.', 429)
            row.attempts += 1
            row.save()


def succeeded(username, address):
    """Clear the account's count; give the address back only this one reservation."""
    (user_key, _), (address_key, _) = _keys(username, address)
    with transaction.atomic():
        LoginThrottle.objects.filter(key=user_key).delete()
        row = LoginThrottle.objects.select_for_update().filter(key=address_key).first()
        if row and row.attempts:
            row.attempts -= 1
            row.save()


def clear_user(username):
    LoginThrottle.objects.filter(key=f'user:{username}').delete()
