"""
Сервис для создания персонального плана пользователя.

Объединяет: vdot_calculator + plan_generator + сохранение в БД.
"""
from django.db import transaction

from apps.plans.models import (
    CompletedWorkout,
    GeneratedPlan,
    RaceType,
    StandardPlanTemplate,
)
from apps.plans.services.completion import completion_keys, plan_is_completed
from apps.plans.services.plan_generator import generate_plan
from apps.plans.services.vdot_calculator import calculate_vdot


ADJUSTMENT_STEP = 0.1
MIN_ADJUSTMENT_FACTOR = 0.5
MAX_ADJUSTMENT_FACTOR = 1.5


class PlanGenerationError(Exception):
    """Ошибка при генерации плана."""
    pass


def create_plan_for_user(
    user,
    race_type: RaceType,
    goal_time_seconds: int,
    adjustment_factor: float = 1.0,
) -> GeneratedPlan:
    """
    Создает персональный план тренировок для пользователя.

    Args:
        user: Django User
        race_type: RaceType (1000 м, 5000 м, Марафон...)
        goal_time_seconds: целевое время в секундах
        adjustment_factor: коэффициент коррекции объёма (1.0 = 100%)

    Returns:
        Созданный GeneratedPlan

    Raises:
        PlanGenerationError: если не удалось найти VDOT или шаблон
    """
    # 1. Считаем VDOT
    vdot = calculate_vdot(race_type.distance_km, goal_time_seconds)
    if not vdot:
        raise PlanGenerationError(
            f'Не удалось определить VDOT для дистанции '
            f'{race_type.name} и времени {goal_time_seconds} сек'
        )

    # 2. Ищем шаблон
    template = StandardPlanTemplate.objects.filter(
        race_type=race_type,
        is_default=True,
    ).first()

    if not template:
        template = StandardPlanTemplate.objects.filter(
            race_type=race_type,
        ).first()

    if not template:
        raise PlanGenerationError(
            f'Не найден шаблон плана для {race_type.name}'
        )

    # 3. Генерируем план
    plan_data = generate_plan(
        structure=template.structure,
        vdot=vdot,
        adjustment_factor=adjustment_factor,
    )
    if not plan_data:
        raise PlanGenerationError('Ошибка генерации плана')

    # 4. Сохраняем в БД
    with transaction.atomic():
        locked_user = type(user).objects.select_for_update().get(pk=user.pk)
        active_plans = list(
            GeneratedPlan.objects.select_for_update().filter(
                user=locked_user,
                is_active=True,
            )
        )
        if any(not plan_is_completed(active_plan) for active_plan in active_plans):
            raise PlanGenerationError(
                'Сначала заверши все пункты текущего активного плана.'
            )

        GeneratedPlan.objects.filter(
            user=locked_user,
            is_active=True,
        ).update(is_active=False)

        plan = GeneratedPlan.objects.create(
            user=locked_user,
            template=template,
            snapshot_vdot=vdot,
            goal_race=race_type.name,
            goal_time_seconds=goal_time_seconds,
            plan_data=plan_data,
            adjustment_factor=adjustment_factor,
            is_active=True,
        )

    return plan


def adjust_plan_for_feedback(
    plan: GeneratedPlan,
    adjustment_delta: float,
) -> GeneratedPlan:
    """Создаёт новую версию плана, сохраняя VDOT и меняя только нагрузку."""
    if adjustment_delta not in (-ADJUSTMENT_STEP, ADJUSTMENT_STEP):
        raise ValueError('Допустим только шаг коррекции 0.1.')

    with transaction.atomic():
        current_plan = GeneratedPlan.objects.select_for_update().select_related(
            'template'
        ).get(pk=plan.pk, user_id=plan.user_id)
        type(current_plan.user).objects.select_for_update().get(
            pk=current_plan.user_id
        )
        other_active_plans = GeneratedPlan.objects.select_for_update().filter(
            user_id=current_plan.user_id,
            is_active=True,
        ).exclude(pk=current_plan.pk)
        if any(not plan_is_completed(other) for other in other_active_plans):
            raise PlanGenerationError(
                'Сначала заверши все пункты другого активного плана.'
            )
        if not current_plan.is_active:
            raise PlanGenerationError('Корректировать можно только активный план.')
        if current_plan.template is None:
            raise PlanGenerationError('У плана нет исходного шаблона для перегенерации.')

        new_factor = round(current_plan.adjustment_factor + adjustment_delta, 2)
        if not MIN_ADJUSTMENT_FACTOR <= new_factor <= MAX_ADJUSTMENT_FACTOR:
            raise PlanGenerationError(
                f'Коэффициент нагрузки должен быть от '
                f'{MIN_ADJUSTMENT_FACTOR:.1f} до {MAX_ADJUSTMENT_FACTOR:.1f}.'
            )

        plan_data = generate_plan(
            structure=current_plan.template.structure,
            vdot=current_plan.snapshot_vdot,
            adjustment_factor=new_factor,
        )
        if not plan_data:
            raise PlanGenerationError('Не удалось перегенерировать план.')

        GeneratedPlan.objects.filter(
            user_id=current_plan.user_id,
            is_active=True,
        ).update(is_active=False)

        new_plan = GeneratedPlan.objects.create(
            user=current_plan.user,
            template=current_plan.template,
            snapshot_vdot=current_plan.snapshot_vdot,
            goal_race=current_plan.goal_race,
            goal_time_seconds=current_plan.goal_time_seconds,
            plan_data=plan_data,
            adjustment_factor=new_factor,
            is_active=True,
        )

        # Структура плана сохраняется, поэтому ключи выполненных пунктов
        # можно перенести в новую версию. Некорректные/исчезнувшие ключи
        # просто отбрасываем.
        old_keys = list(
            CompletedWorkout.objects.filter(plan=current_plan).values_list(
                'workout_key', flat=True
            )
        )
        valid_keys = set(completion_keys(plan_data))
        copied_keys = {key for key in old_keys if key in valid_keys}
        if copied_keys:
            CompletedWorkout.objects.bulk_create(
                [
                    CompletedWorkout(plan=new_plan, workout_key=key)
                    for key in sorted(copied_keys)
                ],
                ignore_conflicts=True,
            )
            if plan_is_completed(new_plan, copied_keys):
                new_plan.is_active = False
                new_plan.save(update_fields=['is_active', 'updated_at'])

        return new_plan