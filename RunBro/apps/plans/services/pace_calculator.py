"""
Получение тренировочных темпов по VDOT.
"""
from typing import Dict, Optional

from django.db.models import F
from django.db.models.functions import Abs

from apps.plans.models import VdotReference


ZONE_KEYS = {
    'E': 'easy_pace_sec',
    'M': 'marathon_pace_sec',
    'T': 'threshold_pace_sec',
    'I': 'interval_pace_sec',
    'R': 'repetition_pace_200m_sec',
    'F': 'fast_reps_pace_200m_sec',
}


def get_paces(vdot: float) -> Optional[Dict[str, int]]:
    """
    Возвращает словарь темпов для заданного VDOT.

    Пример:
        get_paces(45.0)
        # → {'E': 346, 'M': 296, 'T': 278, 'I': 256, 'R': 47, 'F': 43}

    Единицы:
        E, M, T, I — секунды на 1 км
        R, F       — секунды на 200 м
    """
    try:
        ref = VdotReference.objects.get(vdot_value=vdot)
    except VdotReference.DoesNotExist:
        ref = VdotReference.objects.annotate(
            diff=Abs(F('vdot_value') - vdot)
        ).order_by('diff').first()
        if not ref:
            return None

    return {
        zone: getattr(ref, field)
        for zone, field in ZONE_KEYS.items()
    }


def get_pace_for_zone(vdot: float, zone: str) -> Optional[int]:
    """Возвращает темп только для одной зоны."""
    paces = get_paces(vdot)
    if not paces:
        return None
    return paces.get(zone.upper())


def format_pace(seconds: int, per_km: bool = True) -> str:
    """
    Форматирует секунды в 'M:SS'.

    Пример:
        format_pace(346) → '5:46'
        format_pace(47, per_km=False) → '0:47'
    """
    minutes = seconds // 60
    secs = seconds % 60
    return f'{minutes}:{secs:02d}'