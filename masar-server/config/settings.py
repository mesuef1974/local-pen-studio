import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent
load_env_file()


def required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f'{name} is not set. See masar-server/README.md.')
    return value


SECRET_KEY = required('MASAR_SECRET_KEY')
DEBUG = False
ALLOWED_HOSTS = os.environ.get('MASAR_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

INSTALLED_APPS = [
    'django.contrib.admin.apps.SimpleAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'audit',
    'accounts',
    'projects',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'config.middleware.ResponseHeadersMiddleware',
    'config.middleware.RefuseMultipartMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.SessionLifetimeMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
STATIC_URL = '/static/'
WSGI_APPLICATION = 'config.wsgi.application'

# SQLite exists only for quick tests without a database server; real data lives in PostgreSQL.
if os.environ.get('MASAR_DB') == 'sqlite':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
else:
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('MASAR_DB_NAME', 'masar'),
        'USER': os.environ.get('MASAR_DB_USER', 'masar'),
        'PASSWORD': required('MASAR_DB_PASSWORD'),
        'HOST': os.environ.get('MASAR_DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('MASAR_DB_PORT', '5432'),
    }}

AUTH_USER_MODEL = 'accounts.User'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher']
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
     'OPTIONS': {'user_attributes': ('username', 'full_name')}},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

# Cookies are Secure unless local plain-HTTP development explicitly says otherwise.
SECURE_COOKIES = os.environ.get('MASAR_INSECURE_COOKIES') != '1'
SESSION_COOKIE_NAME = 'masar_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 30 * 60  # idle timeout: refreshed on every request
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_ABSOLUTE_AGE = 12 * 60 * 60
CSRF_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SAMESITE = 'Strict'

LOGIN_FAILURE_LIMIT_PER_USER = 5
LOGIN_FAILURE_LIMIT_PER_ADDRESS = 20
LOGIN_WINDOW_SECONDS = 15 * 60

SECURE_REFERRER_POLICY = 'no-referrer'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
# Project files live outside git. The two upload endpoints enforce their own limits.
FILES_DIR = os.environ.get('MASAR_FILES_DIR') or BASE_DIR / 'var' / 'files'
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_STATE_BYTES = 16 * 1024 * 1024

LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Qatar'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
