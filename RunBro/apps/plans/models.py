from django.db import models

from apps.core.models import TimeStampedModel


class RaceType(TimeStampedModel):
    """Справочник дистанций: 1000м, 3000м, 5к, 10к, полумарафон, марафон."""
    name = models.CharField(max_length=20, unique=True, verbose_name='Название')
    distance_km = models.FloatField(
        verbose_name='Дистанция (км)',
        help_text='1000м = 1.0, марафон = 42.195',
    )
    default_plan_weeks = models.IntegerField(
        default=12,
        verbose_name='Недель по умолчанию',
    )

    class Meta:
        verbose_name = 'Тип гонки'
        verbose_name_plural = 'Типы гонок'
        ordering = ['distance_km']

    def __str__(self):
        return f'{self.name} ({self.distance_km} км)'


class VdotReference(TimeStampedModel):
    """
    Справочник VDOT. Содержит тренировочные темпы (сек/км, сек/200м)
    и прогнозы на гонки (секунды). Данные из книги Джека Дэниелса.
    """
    vdot_value = models.FloatField(
        unique=True,
        verbose_name='VDOT',
        help_text='От 30 (новичок) до 85 (элита)',
    )

    # --- Тренировочные темпы (из TrainingTemp.xlsx) ---
    easy_pace_sec = models.IntegerField(verbose_name='Л-темп (Easy), сек/км')
    marathon_pace_sec = models.IntegerField(verbose_name='М-темп (Marathon), сек/км')
    threshold_pace_sec = models.IntegerField(verbose_name='П-темп (Threshold), сек/км')
    interval_pace_sec = models.IntegerField(verbose_name='И-темп (Interval), сек/км')
    repetition_pace_200m_sec = models.IntegerField(
        verbose_name='ПВ-темп на 200м, сек',
        help_text='ПВ-темп измеряется в секундах на 200 м',
    )
    fast_reps_pace_200m_sec = models.IntegerField(
        default=0,
        verbose_name='Б-повторы на 200м, сек',
        help_text='Быстрые повторы для дистанций менее 1500 м.',
    )

    # --- Прогнозы на гонки (из VDOT.xlsx) ---
    predicted_1000m_sec = models.IntegerField(default=0, verbose_name='Прогноз 1000м, сек')
    predicted_1500m_sec = models.IntegerField(default=0, verbose_name='Прогноз 1500м, сек')
    predicted_mile_sec = models.IntegerField(default=0, verbose_name='Прогноз мили, сек')
    predicted_3000m_sec = models.IntegerField(default=0, verbose_name='Прогноз 3000м, сек')
    predicted_2mile_sec = models.IntegerField(default=0, verbose_name='Прогноз 2 миль, сек')
    predicted_5k_sec = models.IntegerField(default=0, verbose_name='Прогноз 5к, сек')
    predicted_10k_sec = models.IntegerField(default=0, verbose_name='Прогноз 10к, сек')
    predicted_half_sec = models.IntegerField(default=0, verbose_name='Прогноз полумарафона, сек')
    predicted_marathon_sec = models.IntegerField(default=0, verbose_name='Прогноз марафона, сек')

    class Meta:
        verbose_name = 'Справочник VDOT'
        verbose_name_plural = 'Справочники VDOT'
        ordering = ['vdot_value']

    def __str__(self):
        return f'VDOT: {self.vdot_value}'


class StandardPlanTemplate(TimeStampedModel):
    """
    Шаблон плана тренировок.
    Хранит структуру (без цифр), темпы и километраж подставляются при генерации.
    """
    name = models.CharField(max_length=100, verbose_name='Название шаблона')
    race_type = models.ForeignKey(
        RaceType,
        on_delete=models.CASCADE,
        related_name='templates',
        verbose_name='Тип гонки',
    )
    weeks_count = models.IntegerField(default=16, verbose_name='Количество недель')
    is_default = models.BooleanField(default=False, verbose_name='По умолчанию')
    description = models.TextField(blank=True, verbose_name='Описание')

    structure = models.JSONField(
        verbose_name='Структура плана',
        help_text='JSON с фазами, неделями и тренировками',
    )

    class Meta:
        verbose_name = 'Шаблон плана'
        verbose_name_plural = 'Шаблоны планов'
        ordering = ['race_type', 'name']

    def __str__(self):
        return f'{self.name} ({self.race_type.name}, {self.weeks_count} нед.)'


class GeneratedPlan(TimeStampedModel):
    """Персональный план пользователя."""
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='plans',
        verbose_name='Пользователь',
    )
    template = models.ForeignKey(
        StandardPlanTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Использованный шаблон',
    )

    snapshot_vdot = models.FloatField(verbose_name='VDOT на момент генерации')
    goal_race = models.CharField(max_length=20, verbose_name='Целевая дистанция')
    goal_time_seconds = models.IntegerField(default=0, verbose_name='Целевое время (сек)')

    plan_data = models.JSONField(
        verbose_name='Данные плана',
        help_text='Готовый JSON с подставленными темпами и километражем',
    )
    adjustment_factor = models.FloatField(
        default=1.0,
        verbose_name='Коэффициент коррекции',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен',
    )

    class Meta:
        verbose_name = 'Сгенерированный план'
        verbose_name_plural = 'Сгенерированные планы'
        ordering = ['-created_at']

    def __str__(self):
        return f'План {self.user.username} ({self.goal_race})'