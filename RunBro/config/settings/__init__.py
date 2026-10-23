"""
Точка входа настроек.

По умолчанию используется development-конфигурация. Для production задайте
``DJANGO_ENV=prod`` (или явный ``DJANGO_SETTINGS_MODULE=config.settings.prod``).
"""
import os

_ENV = os.environ.get('DJANGO_ENV', 'dev').strip().lower()

if _ENV in {'prod', 'production'}:
    from .prod import *  # noqa: F401,F403
else:
    from .dev import *  # noqa: F401,F403
