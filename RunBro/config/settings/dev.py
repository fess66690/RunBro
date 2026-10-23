"""Настройки локальной разработки."""
from decouple import Csv, config

from .base import *  # noqa: F401,F403

DEBUG = True

# Безопасный только для разработки ключ: в production его обязательно
# переопределяет DJANGO_SECRET_KEY.
SECRET_KEY = config(
    'DJANGO_SECRET_KEY',
    default='django-insecure-runbro-dev-only-change-me',
)

ALLOWED_HOSTS = config(
    'DJANGO_ALLOWED_HOSTS',
    default='localhost,127.0.0.1,[::1]',
    cast=Csv(),
)

CSRF_TRUSTED_ORIGINS = config(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    default='http://localhost:8000,http://127.0.0.1:8000',
    cast=Csv(),
)

# В разработке удобно видеть письма в консоли.
EMAIL_BACKEND = config(
    'DJANGO_EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend',
)
