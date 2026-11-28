from ninja import NinjaAPI

from accounts.api import auth_router, users_router
from accounts.errors import DomainError
from audit.api import audit_router

# Interactive docs and the schema stay off: they would be readable without signing in.
api = NinjaAPI(title='Masar', docs_url=None, openapi_url=None)
api.add_router('/auth', auth_router)
api.add_router('/users', users_router)
api.add_router('/audit', audit_router)


@api.exception_handler(DomainError)
def domain_error(request, error):
    return api.create_response(request, {'detail': error.message, 'code': error.code}, status=error.status)
