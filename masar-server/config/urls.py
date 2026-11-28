from django.contrib.staticfiles.views import serve
from django.urls import path

from config.admin import site
from config.api import api

urlpatterns = [
    path('api/', api.urls),
    path('admin/', site.urls),
    # Local runserver only (the admin's own files). A deployment serves static files itself.
    path('static/<path:path>', serve, {'insecure': True}),
]
