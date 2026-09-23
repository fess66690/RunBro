from django.db import models

from django.db import models


class TimeStampedModel(models.Model):
    """
    Абстрактная модель с полями created_at и updated_at.
    Все остальные модели RunBro будут наследоваться от неё.
    """
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлено')

    class Meta:
        abstract = True  # не создает таблицу в БД
        ordering = ['-created_at']