from django.db import models

from django.contrib.auth.models import User
from django.db import models

from apps.core.models import TimeStampedModel


class RunnerProfile(TimeStampedModel):
    """
    Профиль бегуна. Почти с User.
    Хранит физиологические данные и текущий уровень.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='runner_profile',
        verbose_name='Пользователь',
    )

    # Физиологические данные
    birth_year = models.IntegerField(
        verbose_name='Год рождения',
        help_text='Например, 1995',
    )
    resting_hr = models.IntegerField(
        default=60,
        verbose_name='Пульс покоя',
        help_text='Ударов в минуту утром после пробуждения',
    )
    experience_months = models.IntegerField(
        default=0,
        verbose_name='Опыт в беге (месяцев)',
        help_text='0 — новичок, 12 — год опыта',
    )

    # Текущий уровень
    current_vdot = models.FloatField(
        default=30.0,
        verbose_name='Текущий VDOT',
        help_text='От 30 (новичок) до 80 (элита)',
    )

    # Цель (пока просто числа — потом свяжем с RaceType)
    goal_race = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Целевая дистанция',
        help_text='1km, 5km, 10km, half, marathon',
    )
    goal_time_seconds = models.IntegerField(
        default=0,
        verbose_name='Целевое время (секунд)',
        help_text='Например, 3:45:00 = 13500',
    )
    target_vdot = models.FloatField(
        default=0.0,
        verbose_name='Необходимый VDOT для цели',
    )

    class Meta:
        verbose_name = 'Профиль бегуна'
        verbose_name_plural = 'Профили бегунов'

    def __str__(self):
        return f'{self.user.username} (VDOT: {self.current_vdot})'

    @property
    def age(self):
        """Возвращает возраст на основе года рождения."""
        from datetime import date
        return date.today().year - self.birth_year

    @property
    def max_hr(self):
        """Максимальный пульс по формуле 220 - возраст."""
        return 220 - self.age
