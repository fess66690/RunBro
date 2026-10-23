"""
Views для приложения plans.
"""
from copy import deepcopy

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.plans.forms import PlanCreateForm
from apps.plans.models import CompletedWorkout, GeneratedPlan
from apps.plans.services.completion import (
    REST_TYPE_LABELS,
    WORKOUT_TYPE_LABELS,
    first_incomplete_active_plan,
    iter_completion_items,
    plan_is_completed,
)
from apps.plans.services.plan_service import (
    ADJUSTMENT_STEP,
    MAX_ADJUSTMENT_FACTOR,
    MIN_ADJUSTMENT_FACTOR,
    PlanGenerationError,
    adjust_plan_for_feedback,
    create_plan_for_user,
)


def _format_number(value) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f'{value:.2f}'.rstrip('0').rstrip('.')
    return str(value)


def _format_value_with_unit(value, unit: str) -> str:
    if isinstance(value, (list, tuple)):
        if len(value) == 2:
            return f'{_format_number(value[0])}–{_format_number(value[1])} {unit}'
        return ', '.join(f'{_format_number(item)} {unit}' for item in value)
    return f'{_format_number(value)} {unit}'


def _format_zones(zone) -> str:
    if isinstance(zone, (list, tuple)):
        return ', '.join(str(item) for item in zone)
    return str(zone) if zone else ''


def _format_rest(block: dict) -> str:
    parts = []
    rest_type = block.get('rest_type_display')
    if rest_type:
        parts.append(rest_type)
    if block.get('rest_sec') is not None:
        seconds = float(block['rest_sec'])
        if seconds >= 60 and seconds % 60 == 0:
            parts.append(f'{_format_number(seconds / 60)} мин')
        else:
            parts.append(f'{_format_number(seconds)} сек')
    if block.get('rest_m') is not None:
        parts.append(_format_value_with_unit(block['rest_m'], 'м'))
    return ' / '.join(parts)


def _decorate_block(block: dict) -> None:
    block_type = block.get('type', '')
    block['display_type'] = WORKOUT_TYPE_LABELS.get(
        block_type,
        block_type.replace('_', ' ').capitalize(),
    )
    block['rest_type_display'] = REST_TYPE_LABELS.get(
        block.get('rest_type', ''),
        '',
    )
    block['display_zone'] = _format_zones(block.get('zone'))
    block['display_zone_class'] = (
        block.get('zone') if isinstance(block.get('zone'), str) else ''
    )
    repeats = block.get('repeats', 1)
    if isinstance(repeats, list) and len(repeats) == 2:
        repeats = (repeats[0] + repeats[1]) / 2
    if not isinstance(repeats, (int, float)) or repeats <= 0:
        repeats = 1
    total_km = block.get('total_km')
    has_total_km = isinstance(total_km, (int, float)) and total_km > 0
    if 'distance_km' in block:
        display_distance = block['distance_km']
        if has_total_km:
            display_distance = total_km / repeats
        block['display_distance'] = _format_value_with_unit(
            display_distance, 'км'
        )
    elif 'distance_m' in block:
        display_distance = block['distance_m']
        if has_total_km:
            display_distance = total_km * 1000 / repeats
        block['display_distance'] = _format_value_with_unit(
            display_distance, 'м'
        )
    else:
        block['display_distance'] = ''
    block['display_time'] = (
        _format_value_with_unit(block['time_min'], 'мин')
        if 'time_min' in block else ''
    )
    block['display_repeats'] = (
        _format_number(block['repeats'])
        if block.get('repeats') is not None else ''
    )
    block['display_rest'] = _format_rest(block)


@login_required
def plan_create(request):
    """Форма создания плана + обработка POST."""
    active_plan = first_incomplete_active_plan(request.user)
    if active_plan:
        messages.info(
            request,
            'Сначала заверши все пункты текущего плана, чтобы создать новый.',
        )
        return redirect('plan_detail', pk=active_plan.pk)

    if request.method == 'POST':
        form = PlanCreateForm(request.POST)
        if form.is_valid():
            race_type = form.cleaned_data['race_type']
            total_seconds = form.cleaned_data['total_seconds']

            try:
                plan = create_plan_for_user(
                    user=request.user,
                    race_type=race_type,
                    goal_time_seconds=total_seconds,
                )
                messages.success(
                    request,
                    f'🎉 План на {race_type.name} готов! VDOT: {plan.snapshot_vdot}'
                )
                return redirect('plan_detail', pk=plan.pk)
            except PlanGenerationError as error:
                messages.error(request, str(error))
    else:
        form = PlanCreateForm()

    return render(request, 'plans/plan_create.html', {'form': form})


@login_required
def plan_detail(request, pk):
    """Показывает детали плана и прогресс выполнения тренировок."""
    plan = get_object_or_404(GeneratedPlan, pk=pk, user=request.user)
    plan_data = deepcopy(plan.plan_data or {})
    completed_keys = set(
        CompletedWorkout.objects.filter(plan=plan).values_list('workout_key', flat=True)
    )
    completion_items = list(iter_completion_items(plan_data))
    total_workouts = len(completion_items)
    completed_workouts = sum(key in completed_keys for key, _, _ in completion_items)
    next_workout_key = next(
        (key for key, _, _ in completion_items if key not in completed_keys),
        None,
    )

    for workout_key, item_type, item in completion_items:
        is_completed = workout_key in completed_keys
        item['completion_key'] = workout_key
        item['is_completed'] = is_completed
        item['can_complete'] = not is_completed and workout_key == next_workout_key
        if item_type == 'phase':
            item['completion_label'] = 'Тренировочный блок по описанию'
            continue

        day = item.get('day', '')
        item['display_day'] = {
            'T1': 'Работа №1',
            'T2': 'Работа №2',
            'T3': 'Работа №3',
        }.get(day, day)
        workout_type = item.get('type', '')
        item['display_type'] = WORKOUT_TYPE_LABELS.get(
            workout_type,
            workout_type.replace('_', ' ').capitalize(),
        )
        item['display_zone'] = _format_zones(item.get('zone'))
        item['display_zone_class'] = (
            item.get('zone') if isinstance(item.get('zone'), str) else ''
        )
        for block in item.get('blocks', []):
            if isinstance(block, dict):
                _decorate_block(block)

    progress_percent = int(completed_workouts * 100 / total_workouts) if total_workouts else 0
    return render(
        request,
        'plans/plan_detail.html',
        {
            'plan': plan,
            'plan_data': plan_data,
            'total_workouts': total_workouts,
            'completed_workouts': completed_workouts,
            'progress_percent': progress_percent,
            'plan_unknown_count': plan.unknown_volume_count,
            'plan_estimated_count': plan.estimated_volume_count,
            'plan_description_only_count': plan.description_only_week_count,
            'can_create_plan': first_incomplete_active_plan(request.user) is None,
            'adjustment_percent': round(plan.adjustment_factor * 100),
            'can_reduce_adjustment': round(
                plan.adjustment_factor - ADJUSTMENT_STEP, 2
            ) >= MIN_ADJUSTMENT_FACTOR,
            'can_increase_adjustment': round(
                plan.adjustment_factor + ADJUSTMENT_STEP, 2
            ) <= MAX_ADJUSTMENT_FACTOR,
        },
    )


@login_required
@require_POST
def adjust_plan(request: HttpRequest, pk: int):
    """Перегенерирует активный план по сигналу пользователя о нагрузке."""
    plan = get_object_or_404(GeneratedPlan, pk=pk, user=request.user, is_active=True)
    adjustment_delta = {
        'fatigued': -ADJUSTMENT_STEP,
        'easy': ADJUSTMENT_STEP,
    }.get(request.POST.get('feedback'))
    if adjustment_delta is None:
        return HttpResponseBadRequest('Неизвестная оценка нагрузки.')

    try:
        updated_plan = adjust_plan_for_feedback(plan, adjustment_delta)
    except PlanGenerationError as error:
        messages.error(request, str(error))
        return redirect('plan_detail', pk=plan.pk)

    messages.success(
        request,
        f'План обновлён. Новый объём тренировок: '
        f'{round(updated_plan.adjustment_factor * 100)}%.',
    )
    return redirect('plan_detail', pk=updated_plan.pk)


@login_required
@require_POST
def complete_workout(request: HttpRequest, pk: int):
    """Отмечает только следующую тренировку или блок плана."""
    workout_key = request.POST.get('workout_key', '')
    with transaction.atomic():
        plan = get_object_or_404(
            GeneratedPlan.objects.select_for_update(),
            pk=pk,
            user=request.user,
            is_active=True,
        )
        ordered_keys = [
            key for key, _, _ in iter_completion_items(plan.plan_data or {})
        ]
        if workout_key not in ordered_keys:
            return HttpResponseBadRequest('Некорректная тренировка.')

        completed_keys = set(
            CompletedWorkout.objects.filter(plan=plan).values_list(
                'workout_key', flat=True
            )
        )
        if workout_key in completed_keys:
            return redirect('plan_detail', pk=plan.pk)

        next_workout_key = next(
            (key for key in ordered_keys if key not in completed_keys),
            None,
        )
        if workout_key != next_workout_key:
            messages.warning(
                request,
                'Сначала отметь предыдущую тренировку или блок плана.',
            )
            return redirect('plan_detail', pk=plan.pk)

        try:
            # Savepoint защищает транзакцию от гонки двух одновременных
            # запросов с одинаковым workout_key.
            with transaction.atomic():
                CompletedWorkout.objects.create(plan=plan, workout_key=workout_key)
        except IntegrityError:
            pass
        completed_keys.add(workout_key)
        if plan_is_completed(plan, completed_keys):
            plan.is_active = False
            plan.save(update_fields=['is_active', 'updated_at'])
            messages.success(
                request,
                'План полностью выполнен! Теперь можно создать новый.',
            )

    return redirect('plan_detail', pk=plan.pk)


@login_required
@require_POST
def delete_plan(request: HttpRequest, pk: int):
    """Удаляет план текущего пользователя."""
    plan = get_object_or_404(GeneratedPlan, pk=pk, user=request.user)
    plan.delete()
    messages.success(request, 'План удалён.')
    return redirect('plan_list')


@login_required
def plan_list(request):
    """Список всех планов пользователя."""
    plans = GeneratedPlan.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'plans/plan_list.html', {'plans': plans})