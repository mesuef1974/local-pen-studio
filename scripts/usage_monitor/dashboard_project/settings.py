"""Settings for the loopback-only dashboard service."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Qatar"
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ["dashboard_project.formats"]
ROOT_URLCONF = "dashboard_project.urls"
WSGI_APPLICATION = "dashboard_project.wsgi.application"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard_project.apps.DashboardProjectConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "dashboard_project" / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ],
    },
}]

USAGE_DATABASE = Path(os.environ.get(
    "USAGE_DATABASE",
    Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    / "usage-logs" / "usage.sqlite3",
))
ADMIN_DATABASE = USAGE_DATABASE.parent / "dashboard-admin.sqlite3"
ADMIN_DATABASE.parent.mkdir(parents=True, exist_ok=True)


def _secret_key() -> str:
    configured = os.environ.get("DJANGO_SECRET_KEY")
    if configured:
        return configured
    secret_path = ADMIN_DATABASE.parent / "dashboard-secret.key"
    try:
        return secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        generated = secrets.token_urlsafe(48)
        try:
            secret_path.write_text(generated, encoding="utf-8")
        except FileExistsError:
            return secret_path.read_text(encoding="utf-8").strip()
        return generated


SECRET_KEY = _secret_key()
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(ADMIN_DATABASE),
    },
    "workflow": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(USAGE_DATABASE),
    },
}
DATABASE_ROUTERS = ["dashboard_project.db_router.UsageReadOnlyRouter"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_REFERRER_POLICY = "same-origin"

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False
DATA_UPLOAD_MAX_MEMORY_SIZE = 128_000
FILE_UPLOAD_MAX_MEMORY_SIZE = 128_000
