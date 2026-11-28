from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone

from accounts.services import LOGIN_AT


class SessionLifetimeMiddleware:
    """End a session after a fixed age, however active it is."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            started = request.session.get(LOGIN_AT, 0)
            if timezone.now().timestamp() - started >= settings.SESSION_ABSOLUTE_AGE:
                logout(request)
        return self.get_response(request)
