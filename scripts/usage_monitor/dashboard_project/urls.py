"""URL routing for the local dashboard and its JSON API."""

from django.urls import path, re_path

from .admin import owner_admin_site
from . import views


urlpatterns = [
    path("admin/", owner_admin_site.urls),
    path("", views.dashboard),
    path("dashboard.html", views.dashboard),
    path("api/dashboard", views.dashboard_api),
    path("api/workflow/board", views.workflow_board_api),
    path("api/workflow/metrics", views.workflow_metrics_api),
    re_path(r"^api/workflow/cards/(?P<card_id>[^/]+)$", views.workflow_card_api),
    path("api/workflow/commands", views.workflow_commands_api),
    path("identity.css", views.identity_asset),
    re_path(r"^static/(?P<asset_path>.+)$", views.admin_static_asset),
    re_path(r"^fonts/(?P<font_name>[^/]+)$", views.identity_asset),
    re_path(r"^(?P<asset_name>dashboard\.js|workflow\.js|workflow\.css)$", views.dashboard_asset),
]
