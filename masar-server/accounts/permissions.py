from ninja.security import SessionAuth

from accounts.errors import DomainError
from accounts.models import Role

session_auth = SessionAuth()  # also enforces CSRF on unsafe methods


def require_supervisor(request):
    if request.user.must_change_password:
        raise DomainError('password_change_required', 'غيّر كلمة المرور المؤقتة أولًا.', 403)
    if request.user.role != Role.SUPERVISOR:
        raise DomainError('forbidden', 'هذا الإجراء للمشرف.', 403)
