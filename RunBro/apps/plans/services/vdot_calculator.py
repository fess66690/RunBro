"""
Расчет VDOT на основе результата пользователя.

Логика: ищем в VdotReference запись с ближайшим прогнозом на нужную
дистанцию. Возвращаем её vdot_value.
"""
from typing import Optional

from apps.plans.models import VdotReference

# Соответствие: дистанция (км) → поле в VdotReference
DISTANCE_TO_FIELD = {
    1.0: 'predicted_1000m_sec',
    1.5: 'predicted_1500m_sec',
    1.609: 'predicted_mile_sec',
    3.0: 'predicted_3000m_sec',
    3.218: 'predicted_2mile_sec',
    5.0: 'predicted_5k_sec',
    10.0: 'predicted_10k_sec',
    21.1: 'predicted_half_sec',
    42.195: 'predicted_marathon_sec',
}


def calculate_vdot(distance_km: float, time_sec: int) -> Optional[float]:
    """
    Возвращает VDOT для заданного результата.

    Args:
        distance_km: дистанция в км (1.0, 5.0, 21.1, 42.195...)
        time_sec: время в секундах

    Returns:
        VDOT (float) или None, если не удалось найти.
    """
    field = _get_field_for_distance(distance_km)
    if not field:
        return None

    # Ищем все VDOT, у которых прогноз на эту дистанцию > 0
    candidates = VdotReference.objects.exclude(**{field: 0})

    # Находим ближайший прогноз к нашему времени
    best_vdot = None
    best_diff = float('inf')

    for v in candidates:
        predicted = getattr(v, field)
        diff = abs(predicted - time_sec)
        if diff < best_diff:
            best_diff = diff
            best_vdot = v.vdot_value

    return best_vdot


def _get_field_for_distance(distance_km: float) -> Optional[str]:
    """Находит поле прогноза по дистанции (с допуском 0.05 км)."""
    for km, field in DISTANCE_TO_FIELD.items():
        if abs(km - distance_km) < 0.05:
            return field
    return None