"""
Базовые настройки RunBro.

Общие настройки для всех окружений. Конкретное окружение выбирается через
``DJANGO_ENV`` (``dev`` по умолчанию) или через явный
``DJANGO_SETTINGS_MODULE=config.settings.dev`` / ``config.settings.prod``.

Значения читаются из переменных окружения и, если рядом с manage.py есть
файл ``.env``, из него (python-decouple).
"""
from pathlib import Path

from decouple import Csv, config
from django.contrib.messages import constants as message_constants

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# В dev.py есть безопасное значение по умолчанию только для разработки.
SECRET_KEY = config('DJANGO_SECRET_KEY', default='')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config(
    'DJANGO_ALLOWED_HOSTS',
    default='localhost,127.0.0.1',
    cast=Csv(),
)
CSRF_TRUSTED_ORIGINS = config(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    default='',
    cast=Csv(),
)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'apps.accounts',
    'apps.plans',
    'apps.training',
    'apps.dashboard',
    'apps.core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DB_ENGINE = config('DB_ENGINE', default='sqlite').strip().lower()

if DB_ENGINE in {'postgres', 'postgresql'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('POSTGRES_DB', default='runbro'),
            'USER': config('POSTGRES_USER', default='runbro'),
            'PASSWORD': config('POSTGRES_PASSWORD', default=''),
            'HOST': config('POSTGRES_HOST', default='localhost'),
            'PORT': config('POSTGRES_PORT', default='5432'),
            'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
        }
    }
else:
    sqlite_value = config('SQLITE_PATH', default='').strip()
    sqlite_path = Path(sqlite_value) if sqlite_value else BASE_DIR / 'db.sqlite3'
    if not sqlite_path.is_absolute():
        sqlite_path = BASE_DIR / sqlite_path
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': sqlite_path,
        }
    }


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = config('LANGUAGE_CODE', default='ru-ru')

TIME_ZONE = config('TIME_ZONE', default='Europe/Moscow')

USE_I18N = True

USE_TZ = True

LOCALE_PATHS = [BASE_DIR / 'locale']


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Auth
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'plan_list'
LOGOUT_REDIRECT_URL = 'home'

# Messages: Django uses "error", Bootstrap expects "danger".
MESSAGE_TAGS = {
    message_constants.DEBUG: 'secondary',
    message_constants.INFO: 'info',
    message_constants.SUCCESS: 'success',
    message_constants.WARNING: 'warning',
    message_constants.ERROR: 'danger',
}

# Email. Development uses the console backend; production can override it
# through DJANGO_EMAIL_BACKEND and SMTP_* variables.
EMAIL_BACKEND = config(
    'DJANGO_EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = config('EMAIL_HOST', default='')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='RunBro <noreply@runbro.local>')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Basic hardening that is safe in every environment.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
