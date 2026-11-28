"""Account rules. The API layer only translates requests into these calls."""
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts import throttle
from accounts.errors import DomainError
from accounts.models import Role, User
from audit import services as audit
from audit.models import AuditEvent

USERNAME = re.compile(r'[a-z0-9][a-z0-9._-]{2,63}')
LOGIN_AT = 'login_at'


def normalize_username(value):
    return value.strip().lower()


def _record_throttled(request, address, detail):
    """Once per address and window: rejected requests must not grow the append-only log."""
    since = timezone.now() - timedelta(seconds=settings.LOGIN_WINDOW_SECONDS)
    if not AuditEvent.objects.filter(action='auth.throttled', ip_address=address, created_at__gte=since).exists():
        audit.record('auth.throttled', request=request, detail=detail)


def _attempted(username):
    # Only real account names are logged: people type passwords into the name box.
    return {'username': username} if User.objects.filter(username=username).exists() else {}


def sign_in(request, username, password):
    username = normalize_username(username)[:64]
    if '\x00' in username:  # PostgreSQL text cannot hold it
        username = ''
    address = audit.client_address(request)
    try:
        throttle.reserve(username, address)
    except DomainError:
        _record_throttled(request, address, _attempted(username))
        raise
    user = authenticate(request, username=username, password=password)
    if user is None:
        # The same answer for unknown, disabled and wrong-password accounts.
        audit.record('auth.failed', request=request, detail=_attempted(username))
        raise DomainError('invalid_credentials', 'اسم الدخول أو كلمة المرور غير صحيحة.', 401)
    throttle.succeeded(username, address)
    login(request, user)
    request.session[LOGIN_AT] = timezone.now().timestamp()
    audit.record('auth.login', actor=user, request=request)
    return user


def sign_out(request):
    audit.record('auth.logout', actor=request.user, request=request)
    logout(request)


def _check_password_rules(password, user):
    if len(password) > 128:
        raise DomainError('weak_password', 'كلمة المرور أطول من 128 حرفًا.')
    try:
        validate_password(password, user)
    except ValidationError as error:
        raise DomainError('weak_password', ' '.join(error.messages)) from error


def change_password(request, current, new):
    user = request.user
    address = audit.client_address(request)
    # A stolen session must not be able to guess the current password without limit.
    throttle.reserve(user.username, address)
    if not user.check_password(current):
        audit.record('auth.password_change_failed', actor=user, request=request)
        raise DomainError('wrong_password', 'كلمة المرور الحالية غير صحيحة.')
    throttle.succeeded(user.username, address)
    if current == new:
        raise DomainError('same_password', 'اختر كلمة مرور تختلف عن الحالية.')
    _check_password_rules(new, user)
    with transaction.atomic():
        # A reset or disable that landed while we were hashing must win over this change.
        locked = User.objects.select_for_update().get(pk=user.pk)
        if locked.password != user.password or not locked.is_active:
            raise DomainError('session_ended', 'انتهت الجلسة. سجّل الدخول من جديد.', 401)
        user.set_password(new)
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])
        audit.record('auth.password_changed', actor=user, request=request)
    update_session_auth_hash(request, user)  # keeps this session; every other one is invalidated


def create_user(*, actor, username, full_name, role, password=None, request=None):
    """Without a password, generate a temporary one that must be changed at first sign-in."""
    username, full_name = normalize_username(username), full_name.strip()
    if not USERNAME.fullmatch(username):
        raise DomainError('invalid_username', 'اسم الدخول: 3 إلى 64 من الأحرف الإنجليزية والأرقام و . _ -')
    if not 1 <= len(full_name) <= 150 or '\x00' in full_name:
        raise DomainError('invalid_name', 'اكتب الاسم الكامل (حتى 150 حرفًا).')
    if role not in Role.values:
        raise DomainError('invalid_role', 'الدور غير معروف.')
    generated = password is None
    user = User(username=username, full_name=full_name, role=role, must_change_password=generated)
    if generated:
        password = secrets.token_urlsafe(15)
    else:
        _check_password_rules(password, user)
    user.set_password(password)
    try:
        with transaction.atomic():
            user.save()
            audit.record('user.created', actor=actor, target=user, request=request, detail={'role': role})
    except IntegrityError as error:
        raise DomainError('username_taken', 'اسم الدخول مستعمل.', 409) from error
    return user, password


def _locked_target(actor, user_id):
    """Lock the active supervisors first, so two supervisors cannot disable each other at once."""
    supervisors = set(User.objects.select_for_update().order_by('pk')
                      .filter(role=Role.SUPERVISOR, is_active=True).values_list('pk', flat=True))
    if actor.pk not in supervisors:
        raise DomainError('forbidden', 'هذا الإجراء للمشرف.', 403)
    user = User.objects.select_for_update().filter(pk=user_id).first()
    if user is None:
        raise DomainError('not_found', 'الحساب غير موجود.', 404)
    return user


def _end_sessions(user):
    """Delete them, or re-enabling the account would revive an old cookie."""
    for session in Session.objects.iterator():
        if session.get_decoded().get('_auth_user_id') == str(user.pk):
            session.delete()


def set_active(*, actor, user_id, active, request=None):
    """Idempotent: repeating the same state changes nothing and records nothing."""
    with transaction.atomic():
        user = _locked_target(actor, user_id)
        if actor.pk == user.pk and not active:
            raise DomainError('self_disable', 'لا يمكنك تعطيل حسابك.', 409)
        if user.is_active != active:
            user.is_active = active
            user.save(update_fields=['is_active'])
            if not active:
                _end_sessions(user)
            audit.record('user.enabled' if active else 'user.disabled', actor=actor, target=user, request=request)
    return user


def reset_password(*, actor, user_id, request=None):
    with transaction.atomic():
        user = _locked_target(actor, user_id)
        if actor.pk == user.pk:
            raise DomainError('self_reset', 'غيّر كلمة مرورك من صفحة تغيير كلمة المرور.', 409)
        password = secrets.token_urlsafe(15)
        user.set_password(password)
        user.must_change_password = True
        user.save(update_fields=['password', 'must_change_password'])
        throttle.clear_user(user.username)
        audit.record('user.password_reset', actor=actor, target=user, request=request)
    return user, password
