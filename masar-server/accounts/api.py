from uuid import UUID

from django.middleware.csrf import get_token
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.utils import check_csrf

from accounts import services
from accounts.models import User
from accounts.permissions import require_password_changed, require_supervisor, session_auth

auth_router = Router()
users_router = Router(auth=session_auth)


class UserOut(Schema):
    id: UUID
    username: str
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool


class Credentials(Schema):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)


class PasswordChange(Schema):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., max_length=128)


class NewUser(Schema):
    username: str = Field(..., max_length=64)
    full_name: str = Field(..., max_length=150)
    role: str = Field('teacher', max_length=10)


class UserWithPassword(Schema):
    user: UserOut
    temporary_password: str  # shown once; only its hash is stored


@auth_router.get('/csrf')
def csrf(request):
    return {'csrf_token': get_token(request)}


@auth_router.post('/login', response=UserOut)
def login(request, body: Credentials):
    # No session yet, so SessionAuth cannot check CSRF here; check explicitly against login CSRF.
    if check_csrf(request):
        raise HttpError(403, 'CSRF check Failed')
    return services.sign_in(request, body.username, body.password)


@auth_router.post('/verify', auth=session_auth, response={204: None})
def verify(request):
    # Asked by the studio before it computes anything: a live session, its CSRF token, a permanent password.
    require_password_changed(request)
    return 204, None


@auth_router.get('/me', auth=session_auth, response=UserOut)
def me(request):
    return request.user


@auth_router.post('/logout', auth=session_auth, response={204: None})
def logout(request):
    services.sign_out(request)
    return 204, None


@auth_router.post('/change-password', auth=session_auth, response={204: None})
def change_password(request, body: PasswordChange):
    services.change_password(request, body.current_password, body.new_password)
    return 204, None


@users_router.get('', response=list[UserOut])
def list_users(request):
    require_supervisor(request)
    return list(User.objects.all())


@users_router.post('', response={201: UserWithPassword})
def create_user(request, body: NewUser):
    require_supervisor(request)
    user, password = services.create_user(actor=request.user, username=body.username,
                                          full_name=body.full_name, role=body.role, request=request)
    return 201, {'user': user, 'temporary_password': password}


@users_router.post('/{user_id}/disable', response=UserOut)
def disable_user(request, user_id: UUID):
    require_supervisor(request)
    return services.set_active(actor=request.user, user_id=user_id, active=False, request=request)


@users_router.post('/{user_id}/enable', response=UserOut)
def enable_user(request, user_id: UUID):
    require_supervisor(request)
    return services.set_active(actor=request.user, user_id=user_id, active=True, request=request)


@users_router.post('/{user_id}/reset-password', response=UserWithPassword)
def reset_password(request, user_id: UUID):
    require_supervisor(request)
    user, password = services.reset_password(actor=request.user, user_id=user_id, request=request)
    return {'user': user, 'temporary_password': password}
