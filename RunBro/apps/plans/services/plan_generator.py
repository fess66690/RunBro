"""
Генерация персонального плана тренировок.

Берет структуру шаблона + VDOT пользователя, возвращает JSON с
подставленными темпами и посчитанным километражем.
"""
import copy
import math
import re
from typing import Any, Dict, Optional

from apps.plans.services.pace_calculator import get_paces, format_pace


RANGE_FIELDS = {
    'distance_km', 'distance_m', 'repeats', 'total_repeats', 'time_min',
    'rest_sec', 'rest_m', 'target_weekly_percent',
}


def _runner_group(vdot: float) -> str:
    if vdot < 46:
        return 'beginner'
    if vdot <= 70:
        return 'confident'
    return 'elite'


def _select_range(value: list, group: str, integer: bool = False):
    if len(value) == 3:
        selected = {'beginner': value[0], 'confident': value[1], 'elite': value[2]}[group]
    else:
        low, high = value
        if group == 'beginner':
            selected = low
        elif group == 'elite':
            selected = high
        else:
            selected = (low + high) / 2
    if integer:
        return math.floor(selected + 0.5)
    return int(selected) if float(selected).is_integer() else selected


def _apply_vdot_ranges(value: Any, group: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in RANGE_FIELDS
                and isinstance(item, list)
                and len(item) in (2, 3)
                and all(isinstance(part, (int, float)) for part in item)
            ):
                value[key] = _select_range(
                    item, group, integer=key in {'repeats', 'total_repeats'}
                )
            else:
                _apply_vdot_ranges(item, group)
    elif isinstance(value, list):
        for item in value:
            _apply_vdot_ranges(item, group)


def _sync_repeat_description(training: Dict[str, Any]) -> None:
    repeats = training.get('total_repeats')
    description = training.get('description')
    if not isinstance(repeats, int) or not isinstance(description, str):
        return
    training['description'] = re.sub(
        r'^(\s*(?:Серии из\s*)?)\d+\s*[–-]\s*\d+\s*[×x]',
        rf'\g<1>{repeats} ×', description, count=1,
    )


def generate_plan(
    structure: Dict[str, Any],
    vdot: float,
    adjustment_factor: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """Генерирует персональный план на основе шаблона и VDOT."""
    paces = get_paces(vdot)
    if not paces:
        return None

    plan = copy.deepcopy(structure)
    group = _runner_group(vdot)
    _apply_vdot_ranges(plan, group)
    plan['vdot'] = vdot
    plan['vdot_group'] = group
    plan['adjustment_factor'] = adjustment_factor

    for phase in plan.get('phases', []):
        for week in phase.get('weeks', []):
            trainings = week.get('trainings', [])

            # 1. Блоки, темпы и объём по описанию.
            for training in trainings:
                _process_training(training, paces, adjustment_factor)
                _estimate_description_volume(
                    training, paces, adjustment_factor, group
                )
                _sync_repeat_description(training)

            # 2. Серии с явным series_config адаптируются под недельный объём.
            for training in trainings:
                config = training.get('series_config') or _infer_series_config(
                    training, group
                )
                if config:
                    training['series_config'] = config
                    other_weekly_km = _other_weekly_km(trainings, training)
                    _process_series_training(
                        training, other_weekly_km, adjustment_factor, paces
                    )

            # 3. Длительные, у которых в шаблоне только заметка
            #    («2 ч», «25% недельного километража» и т.п.).
            for training in trainings:
                _resolve_long_run_volume(
                    training, trainings, paces, adjustment_factor
                )

            # 4. Ограничения по проценту недельного объёма.
            for training in trainings:
                if not training.get('series_config'):
                    _apply_block_volume_limit(
                        training, trainings, paces, adjustment_factor
                    )

            # 5. Если объём так и не удалось определить, не показываем
            #    вводящий в заблуждение 0 км.
            for training in trainings:
                if training.get('volume_unknown'):
                    training['total_km'] = None

    return plan


def _other_weekly_km(trainings: list, current: Dict[str, Any]) -> float:
    return sum(
        item['total_km'] for item in trainings
        if item is not current and isinstance(item.get('total_km'), (int, float))
    )


def _training_constraint(training: Dict[str, Any]) -> str:
    constraint = training.get('constraint', '')
    if constraint:
        return str(constraint)
    return ' '.join(
        str(block.get('note', ''))
        for block in training.get('blocks', [])
        if block.get('type') == 'constraint'
    )


def _infer_series_config(training: Dict[str, Any], group: str) -> Optional[Dict[str, Any]]:
    description = training.get('description', '')
    constraint = _training_constraint(training).lower().replace('ё', 'е')
    text = description.lower().replace('ё', 'е')
    if not description or not constraint:
        return None

    percent_match = re.search(
        r'(\d+(?:[,.]\d+)?)(?:\s*[–-]\s*(\d+(?:[,.]\d+)?))?\s*%',
        constraint,
    )
    if not percent_match:
        return None
    percent_values = [float(value.replace(',', '.')) for value in percent_match.groups() if value]
    target_percent = min(percent_values) if percent_values else 4.0
    target_is_max = True

    work_zone = training.get('zone') or 'I'
    if 'пв-темп' in constraint:
        work_zone = 'R'
    elif 'и-темп' in constraint:
        work_zone = 'I'
    elif 'п-темп' in constraint:
        work_zone = 'T'
    elif 'б-темп' in constraint:
        work_zone = 'F'

    sequence = None
    if '2 мин и, 1 мин трусцой + 1 мин и' in text or '2 мин напряженный бег, 1 мин' in text:
        sequence = [
            {'time_min': 2, 'zone': work_zone}, {'time_min': 1, 'zone': 'E'},
            {'time_min': 1, 'zone': work_zone}, {'time_min': 0.5, 'zone': 'E'},
            {'time_min': 0.5, 'zone': work_zone}, {'time_min': 0.5, 'zone': 'E'},
        ]
    elif '1000, 1200 или 1600 м в и-темпе' in text:
        sequence = [
            {'distance_m': [1000, 1200, 1600], 'zone': 'I'},
            {'time_min': [3, 4, 5], 'zone': 'E'},
        ]
    elif '1200–1600 м' in description and '4–5 мин' in description and 'напряженном и-темпе' in text:
        sequence = [
            {'distance_m': [1200, 1400, 1600], 'zone': 'I'},
            {'time_min': [3, 3.5, 4], 'zone': 'E'},
        ]
    elif '(1000, 1200, 1600 м в и-темпе' in text:
        sequence = [
            {'distance_m': [1000, 1200, 1600], 'zone': 'I'},
            {'time_min': 3, 'zone': 'E'},
        ]
    elif '800 или 1000 м в и-темпе' in text:
        sequence = [
            {'distance_m': [800, 1000], 'zone': 'I'},
            {'time_min': 2, 'zone': 'E'},
        ]
    elif '4 мин напряженного бега + 3 мин бега трусцой' in text:
        sequence = [
            {'time_min': 4, 'zone': work_zone}, {'time_min': 3, 'zone': 'E'},
        ]
    elif '200 м в пв-темпе + 200 м бега трусцой' in text and '1 × 400 м' in text:
        sequence = [
            {'distance_m': 200, 'zone': 'R'}, {'distance_m': 200, 'zone': 'E'},
            {'distance_m': 400, 'zone': 'R'}, {'distance_m': 400, 'zone': 'E'},
        ]
    elif '1 × 800 м' in text and '2 × 400 м' in text and '4 × 200 м' in text:
        sequence = [
            {'distance_m': 800, 'repeats': 1, 'zone': 'R'},
            {'distance_m': 800, 'zone':  'E'},
            {'distance_m': 400, 'repeats': 2, 'zone': 'R'},
            {'distance_m': 400, 'zone': 'E'},
            {'distance_m': 200, 'repeats': 4, 'zone': 'R'},
            {'distance_m': 200, 'zone': 'E'},
        ]
    elif work_zone == 'F' and '2 × 200 м' in text and '1 × 400 м' in text:
        sequence = [
            {'distance_m': 200, 'repeats': 2, 'zone': 'F'},
            {'distance_m': [200, 300, 400], 'zone': 'E'},
            {'distance_m': 400, 'zone': 'F'},
            {'distance_m': [600, 700, 800], 'zone': 'E'},
        ]
    if sequence is None:
        return None

    max_match = re.search(
        r'(?:не более|максимум|или)\s*(\d+(?:[,.]\d+)?)\s*(км|м)\b',
        constraint,
    )
    max_work_km = None
    if max_match:
        max_work_km = float(max_match.group(1).replace(',', '.'))
        if max_match.group(2) == 'м':
            max_work_km /= 1000
    config = {
        'target_zone': work_zone,
        'target_weekly_percent': target_percent,
        'target_is_max': target_is_max,
        'sequence': sequence,
        'max_work_km': max_work_km,
    }
    _apply_vdot_ranges(config, group)
    return config


_DESCRIPTION_TOKEN_RE = re.compile(
    r'(?P<num>\d+(?:[.,]\d+)?(?:\s*[–\-—]\s*\d+(?:[.,]\d+)?)?)'
    r'|(?P<mul>[×x])'
    r'|(?P<plus>\+)'
    r'|(?P<lparen>\()'
    r'|(?P<rparen>\))'
    r'|(?P<semi>;)'
    r'|(?P<or>\bили\b)'
    r'|(?P<unit>\b(?:км|мин|м|ч)\b)'
    r'|(?P<zone>\b(?:Пв|И|П|Б|Л|М)\b|трусцой|отдых\w*)'
    r'|(?P<word>[^\s+×x();]+)',
    re.IGNORECASE,
)


def _normalise_description(text: str) -> str:
    """Приводит описание к виду, удобному для разбора объёма."""
    text = text.replace('–', '-').replace('—', '-').replace('−', '-')
    # «Пв+3» / «Пв−1» — это поправка к темпу, а не отдельный отрезок.
    text = re.sub(
        r'(Пв|И|П|Б|Л|М)\s*[+\-]\s*\d+(?:[.,]\d+)?'
        r'(?!\d)(?!\s*[-–—]\s*\d)(?!\s*(?:м|км|мин|ч)\b)',
        r'\1',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'^\s*серии\s+из\s*', '', text, flags=re.IGNORECASE)
    return text


def _normalise_zone(text: str) -> Optional[str]:
    upper = text.upper().replace('Ё', 'Е')
    if upper.startswith('ПВ'):
        return 'R'
    if upper.startswith('И'):
        return 'I'
    if upper.startswith('П'):
        return 'T'
    if upper.startswith('Б'):
        return 'F'
    if upper.startswith('Л'):
        return 'E'
    if upper.startswith('М'):
        return 'M'
    if 'ТРУСЦ' in upper or 'ОТДЫХ' in upper:
        return 'E'
    return None


def _description_number(text: str, group: str) -> float:
    text = text.replace(',', '.')
    if '-' in text:
        low, high = (part.strip() for part in text.split('-', 1))
        return float(_select_range([float(low), float(high)], group))
    return float(text)


def _time_km(minutes: float, zone: Optional[str], paces: Dict[str, int]) -> float:
    pace = paces.get(zone or 'E') or paces.get('E') or 300
    if zone in ('R', 'F'):
        pace *= 5
    return minutes * 60 / pace


def _parse_training_description(
    description: str,
    paces: Dict[str, int],
    group: str,
) -> Optional[tuple[float, float]]:
    """
    Оценивает общий и рабочий километраж по текстовому описанию.

    Это не заменяет структурированные series_config, а закрывает старые
    шаблоны, где сохранилось только описание тренировки.
    """
    if not description:
        return None

    tokens = [
        (match.lastgroup, match.group())
        for match in _DESCRIPTION_TOKEN_RE.finditer(_normalise_description(description))
        if match.lastgroup
    ]
    if not tokens:
        return None

    def skip_alternatives(index: int) -> int:
        """Пропускает `;`/`или` до закрывающей скобки текущей группы."""
        depth = 0
        while index < len(tokens):
            kind, _ = tokens[index]
            if kind == 'lparen':
                depth += 1
            elif kind == 'rparen':
                if depth == 0:
                    return index
                depth -= 1
            index += 1
        return index

    def parse_expression(index: int) -> tuple[tuple[float, float], int]:
        total = 0.0
        work = 0.0
        while index < len(tokens):
            kind, _ = tokens[index]
            if kind in {'rparen', 'semi', 'or'}:
                break
            if kind == 'plus':
                index += 1
                continue
            (part_total, part_work), index = parse_term(index)
            total += part_total
            work += part_work
        return (total, work), index

    def parse_term(index: int) -> tuple[tuple[float, float], int]:
        kind, text = tokens[index]

        if kind == 'num' and index + 1 < len(tokens) and tokens[index + 1][0] == 'mul':
            repeats = _description_number(text, group)
            (total, work), index = parse_term(index + 2)
            return (total * repeats, work * repeats), index

        if kind == 'num':
            value = _description_number(text, group)
            index += 1
            unit = None
            if index < len(tokens) and tokens[index][0] == 'unit':
                unit = tokens[index][1].lower()
                index += 1

            # Ищем зону вплоть до следующего «+»/закрывающей скобки.
            zone = None
            depth = 0
            while index < len(tokens):
                next_kind, next_text = tokens[index]
                if depth == 0 and next_kind in {
                    'plus', 'rparen', 'semi', 'or', 'mul', 'num'
                }:
                    break
                if next_kind == 'lparen':
                    depth += 1
                elif next_kind == 'rparen':
                    if depth == 0:
                        break
                    depth -= 1
                elif next_kind == 'zone' and zone is None:
                    zone = _normalise_zone(next_text)
                index += 1

            if unit in {'м', 'км'}:
                km = value / 1000 if unit == 'м' else value
            elif unit in {'мин', 'ч'}:
                minutes = value * 60 if unit == 'ч' else value
                km = _time_km(minutes, zone, paces)
            else:
                km = 0.0
            work = km if zone not in (None, 'E') else 0.0
            return (km, work), index

        if kind == 'lparen':
            (total, work), index = parse_expression(index + 1)
            if index < len(tokens) and tokens[index][0] == 'rparen':
                index += 1
            elif index < len(tokens) and tokens[index][0] in {'semi', 'or'}:
                index = skip_alternatives(index)
                if index < len(tokens) and tokens[index][0] == 'rparen':
                    index += 1
            return (total, work), index

        # Слова «в», «темпе», «бега» и т.п. просто пропускаем.
        return (0.0, 0.0), index + 1

    (total, work), _ = parse_expression(0)
    if total <= 0:
        return None
    return total, work


def _estimate_description_volume(
    training: Dict[str, Any],
    paces: Dict[str, int],
    adjustment_factor: float,
    group: str,
) -> bool:
    if training.get('blocks') or training.get('series_config'):
        return False
    if training.get('type') not in {'series', 'intervals', 'fartlek'}:
        return False
    parsed = _parse_training_description(
        str(training.get('description', '')),
        paces,
        group,
    )
    if not parsed:
        training['total_km'] = None
        training['volume_unknown'] = True
        return False
    total_km, work_km = parsed
    training['total_km'] = round(total_km * adjustment_factor, 2)
    training['series_work_km'] = round(work_km * adjustment_factor, 2)
    training['volume_estimated'] = True
    training.pop('volume_unknown', None)
    return True


def _note_volume_candidates(
    note: str,
    other_weekly_km: float,
    paces: Dict[str, int],
    adjustment_factor: float,
) -> list[float]:
    """Возвращает возможные километры длительной тренировки из заметки."""
    normalised = note.lower().replace('ё', 'е').replace(',', '.')
    candidates = []

    distance_match = re.search(r'(\d+(?:\.\d+)?)\s*км\b', normalised)
    if distance_match:
        candidates.append(float(distance_match.group(1)) * adjustment_factor)

    time_minutes = None
    hours_match = re.search(r'(\d+(?:\.\d+)?)\s*ч\b', normalised)
    if hours_match:
        time_minutes = float(hours_match.group(1)) * 60
    else:
        minutes_match = re.search(r'(\d+(?:\.\d+)?)\s*мин\b', normalised)
        if minutes_match:
            time_minutes = float(minutes_match.group(1))
    if time_minutes is not None:
        candidates.append(_time_km(time_minutes, 'E', paces) * adjustment_factor)

    # Процент недельного объёма используем только тогда, когда в заметке
    # нет явного времени/дистанции. В старых шаблонах общая лёгкая база
    # может отсутствовать, и процент даёт нереалистичные 200–500 м.
    percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', normalised)
    if not candidates and percent_match and other_weekly_km > 0:
        percent = float(percent_match.group(1))
        if 0 < percent < 100:
            percent_km = other_weekly_km * percent / (100 - percent)
            if percent_km >= 3:
                candidates.append(percent_km)

    return candidates


def _resolve_long_run_volume(
    training: Dict[str, Any],
    trainings: list,
    paces: Dict[str, int],
    adjustment_factor: float,
) -> bool:
    """Заполняет объём длительных тренировок, заданных только заметкой."""
    if training.get('type') not in {'long', 'long_run'}:
        return False
    adjustment_factor = adjustment_factor or 1.0
    changed = False
    other_weekly_km = _other_weekly_km(trainings, training)
    for block in training.get('blocks', []):
        if not isinstance(block, dict) or block.get('type') != 'long':
            continue
        if any(key in block for key in ('distance_km', 'distance_m', 'time_min')):
            continue
        note = str(block.get('note', ''))
        candidates = _note_volume_candidates(
            note, other_weekly_km, paces, adjustment_factor
        )
        if not candidates:
            continue
        # «или ... — что меньше» означает выбор меньшего варианта. Для
        # одиночных значений остаётся единственный кандидат. Кандидаты уже
        # умножены на adjustment_factor, поэтому возвращаем базовую дистанцию
        # и пересчитываем тренировку с тем же коэффициентом.
        block['distance_km'] = round(min(candidates) / adjustment_factor, 2)
        changed = True

    if changed:
        _process_training(training, paces, adjustment_factor)
        training['volume_estimated'] = True
        training.pop('volume_unknown', None)
    return changed


def _segment_km(segment: Dict[str, Any], paces: Dict[str, int]) -> float:
    zone = segment.get('zone')
    if 'distance_m' in segment:
        return float(segment['distance_m']) / 1000
    if 'distance_km' in segment:
        return float(segment['distance_km'])
    if 'time_min' in segment:
        pace = paces.get(zone) if isinstance(zone, str) else None
        if not pace:
            return float(segment['time_min']) / 5
        if zone in ('R', 'F'):
            pace *= 5
        return float(segment['time_min']) * 60 / pace
    return 0.0


def _constraint_limits(constraint: str) -> tuple[Optional[float], Optional[float]]:
    percent_match = re.search(
        r'(\d+(?:[,.]\d+)?)(?:\s*[–-]\s*(\d+(?:[,.]\d+)?))?\s*%',
        constraint.lower(),
    )
    percent = None
    if percent_match:
        values = [float(value.replace(',', '.')) for value in percent_match.groups() if value]
        percent = min(values) if len(values) == 2 else values[0]
    max_match = re.search(
        r'(?:не более|максимум|или)\s*(\d+(?:[,.]\d+)?)\s*(км|м)\b',
        constraint.lower(),
    )
    max_km = None
    if max_match:
        max_km = float(max_match.group(1).replace(',', '.'))
        if max_match.group(2) == 'м':
            max_km /= 1000
    return percent, max_km


def _apply_block_volume_limit(
    training: Dict[str, Any], trainings: list, paces: Dict[str, int], adjustment_factor: float
) -> None:
    constraint = _training_constraint(training)
    percent, max_km = _constraint_limits(constraint)
    if not percent or not (0 < percent < 100) or not training.get('blocks'):
        return
    lowered = constraint.lower().replace('ё', 'е')
    if 'пв-темп' in lowered:
        target_zone = 'R'
    elif 'и-темп' in lowered:
        target_zone = 'I'
    elif 'п-темп' in lowered:
        target_zone = 'T'
    elif 'б-темп' in lowered:
        target_zone = 'F'
    else:
        target_zone = training.get('zone')
    if not target_zone:
        return

    candidates = []
    work_km = 0.0
    for block in training['blocks']:
        zone = block.get('zone')
        if block.get('type') not in {'interval', 'tempo', 'series', 'fartlek'}:
            continue
        if zone != target_zone and not (isinstance(zone, list) and target_zone in zone):
            continue
        block_km = float(block.get('total_km', 0) or 0)
        work_km += block_km
        repeats = block.get('repeats', 1)
        if isinstance(repeats, (int, float)) and repeats > 1 and block_km > 0:
            candidates.append((block, block_km / repeats))
    if not candidates or work_km <= 0:
        return

    other_km = _other_weekly_km(trainings, training)
    non_work_km = max(0.0, float(training.get('total_km') or 0) - work_km)
    target_fraction = percent / 100
    allowed_work_km = target_fraction * (other_km + non_work_km) / (1 - target_fraction)
    if max_km is not None:
        allowed_work_km = min(allowed_work_km, max_km)
    if work_km <= allowed_work_km:
        return

    repeats_changed = False
    while work_km - allowed_work_km > 1e-6:
        adjustable = [item for item in candidates if item[0].get('repeats', 1) > 1]
        if not adjustable:
            break
        block, km_per_repeat = max(adjustable, key=lambda item: item[1])
        block['repeats'] -= 1
        work_km -= km_per_repeat
        repeats_changed = True
    if repeats_changed:
        _process_training(training, paces, adjustment_factor)
        training['volume_limit_km'] = round(allowed_work_km, 2)
        training['volume_limit_applied'] = True


def _format_km(value: float) -> str:
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _process_series_training(
    training: Dict[str, Any],
    other_weekly_km: float,
    adjustment_factor: float,
    paces: Dict[str, int],
) -> None:
    config = training['series_config']
    sequence = config.get('sequence', [])
    target_zone = config.get('target_zone', 'R')
    work_km_per_series = sum(
        _segment_km(segment, paces) * segment.get('repeats', 1)
        for segment in sequence if segment.get('zone') == target_zone
    ) * adjustment_factor
    total_km_per_series = sum(
        _segment_km(segment, paces) * segment.get('repeats', 1)
        for segment in sequence
    ) * adjustment_factor
    if work_km_per_series <= 0 or total_km_per_series <= 0:
        return

    target_percent = config.get('target_weekly_percent', 4)
    if not isinstance(target_percent, (int, float)) or not (0 < target_percent < 100):
        return
    target_fraction = target_percent / 100
    max_work_km = config.get('max_work_km')
    denominator = work_km_per_series - target_fraction * total_km_per_series
    ideal_series_count = (
        target_fraction * other_weekly_km / denominator
        if denominator > 0 and other_weekly_km > 0 else 1
    )
    max_series_count = (
        max(1, math.floor(max_work_km / work_km_per_series))
        if isinstance(max_work_km, (int, float)) else max(1, math.ceil(ideal_series_count))
    )
    rounded_series_count = (
        math.floor(ideal_series_count)
        if config.get('target_is_max') else math.floor(ideal_series_count + 0.5)
    )
    series_count = max(1, min(max_series_count, rounded_series_count))
    work_km = work_km_per_series * series_count
    workout_km = total_km_per_series * series_count
    weekly_km = other_weekly_km + workout_km
    actual_percent = work_km / weekly_km * 100 if weekly_km else 0

    training['total_repeats'] = series_count
    training['series_work_km'] = round(work_km, 2)
    training['total_km'] = round(workout_km, 2)
    training.pop('volume_unknown', None)
    description_template = config.get('description_template')
    if description_template:
        labels = [segment['label'] for segment in sequence if segment.get('label')]
        training['description'] = description_template.format(
            repeats=series_count, sequence=' + '.join(labels)
        )
    else:
        description = training.get('description', '')
        repeat_prefix = re.match(r'^(\s*(?:Серии из\s*)?)(\d+(?:\s*[–-]\s*\d+)?)\s*[×x]\s*', description)
        if repeat_prefix:
            training['description'] = (
                f'{repeat_prefix.group(1)}{series_count} × '
                f'{description[repeat_prefix.end():]}'
            )
        else:
            remainder = re.sub(r'^\s*Серии из\s*', '', description, flags=re.IGNORECASE)
            if not remainder:
                remainder = ' + '.join(
                    segment['label'] for segment in sequence if segment.get('label')
                )
            if remainder:
                training['description'] = f'Серии из {series_count} × ({remainder})'
            else:
                training['description'] = f'Серии из {series_count} повторений'
    zone_names = {'R': 'Пв', 'I': 'И', 'T': 'П', 'F': 'Б'}
    zone_label = zone_names.get(target_zone, target_zone)
    max_text = (
        f', максимум {_format_km(max_work_km)} км' if max_work_km is not None else ''
    )
    training['constraint'] = (
        f'Рабочий объём в {zone_label}-темпе: '
        f'{_format_km(training["series_work_km"])} км '
        f'({actual_percent:.1f}% недельного километража; целевой уровень '
        f'{target_percent}%{max_text}).'
    )


def _process_training(
        training: Dict[str, Any],
        paces: Dict[str, int],
        adjustment_factor: float,
) -> None:
    """Обрабатывает одну тренировку."""

    # --- Если у тренировки нет blocks, но есть description (series, fartlek) ---
    if 'blocks' not in training or not training['blocks']:
        zone = training.get('zone')
        if zone and isinstance(zone, str) and zone in paces:
            pace_sec = paces[zone]
            training['pace_sec'] = pace_sec
            if zone in ('R', 'F'):
                training['pace_formatted'] = f'{format_pace(pace_sec)} /200м'
            else:
                training['pace_formatted'] = f'{format_pace(pace_sec)} /км'
        training['total_km'] = None
        return

    # --- Обычная обработка блоков ---
    blocks = training.get('blocks', [])
    total_km = 0.0
    has_volume_source = False
    for block in blocks:
        if any(key in block for key in ('distance_km', 'distance_m', 'time_min')):
            has_volume_source = True
        km = _process_block(block, paces, adjustment_factor)
        total_km += km
    training['total_km'] = round(total_km, 2)
    if total_km <= 0 and not has_volume_source:
        training['total_km'] = None
        training['volume_unknown'] = True
    else:
        training.pop('volume_unknown', None)


def _process_block(
    block: Dict[str, Any],
    paces: Dict[str, int],
    adjustment_factor: float,
) -> float:
    """
    Обрабатывает один блок. Возвращает километраж этого блока.
    """
    km = 0.0
    # Автоматическая зона для лёгких блоков-заглушек.
    if not block.get('zone') and block.get('type') in {
        'easy', 'warmup', 'cooldown', 'recovery', 'long',
    }:
        block['zone'] = 'E'
    zone = block.get('zone')

    # --- 1. Подставляем темп ---
    if zone:
        if isinstance(zone, list):
            # Список зон — альтернативы. Показываем все.
            pace_info = []
            for z in zone:
                if z in paces:
                    pace_sec = paces[z]
                    if z in ('R', 'F'):
                        pace_info.append(f'{format_pace(pace_sec)} /200м ({z})')
                    else:
                        pace_info.append(f'{format_pace(pace_sec)} /км ({z})')
            if pace_info:
                block['pace_formatted'] = ' или '.join(pace_info)
                block['pace_sec'] = paces.get(zone[0], 0)
        elif isinstance(zone, str) and zone in paces:
            pace_sec = paces[zone]
            block['pace_sec'] = pace_sec
            if zone in ('R', 'F'):
                block['pace_formatted'] = f'{format_pace(pace_sec)} /200м'
            else:
                block['pace_formatted'] = f'{format_pace(pace_sec)} /км'

    # --- 2. Считаем километраж ---

    # Блок с distance_km
    if 'distance_km' in block:
        dist = block['distance_km']
        if isinstance(dist, list) and len(dist) == 2:
            dist = (dist[0] + dist[1]) / 2
        elif not isinstance(dist, (int, float)):
            dist = 0.0
        repeats = block.get('repeats', 1)
        if isinstance(repeats, list) and len(repeats) == 2:
            repeats = (repeats[0] + repeats[1]) / 2
        elif not isinstance(repeats, (int, float)):
            repeats = 1
        km = dist * repeats
        km *= adjustment_factor

    # Блок с distance_m + repeats
    elif 'distance_m' in block:
        dist_m = block['distance_m']
        repeats = block.get('repeats', 1)
        if isinstance(repeats, list) and len(repeats) == 2:
            repeats = (repeats[0] + repeats[1]) / 2
        elif not isinstance(repeats, (int, float)):
            repeats = 1
        km = (dist_m * repeats) / 1000
        km *= adjustment_factor

    # Блок с time_min
    elif 'time_min' in block:
        time_min = block['time_min']
        if isinstance(time_min, list) and len(time_min) == 2:
            time_min = (time_min[0] + time_min[1]) / 2
        calc_zone = zone[0] if isinstance(zone, list) else zone
        if calc_zone and isinstance(calc_zone, str) and calc_zone in paces:
            pace = paces[calc_zone]
            # Для R/F справочник хранит темп на 200 м.
            if calc_zone in ('R', 'F'):
                pace *= 5
            km = (time_min * 60) / pace
        else:
            km = time_min / 5.0
        km *= adjustment_factor

    # Блок-заметка (race, constraint, long) — 0 км

    if km > 0:
        block['total_km'] = round(km, 2)
    else:
        block.pop('total_km', None)

    return km


def format_plan_summary(plan: Dict[str, Any]) -> str:
    """Краткая сводка по плану для консольной отладки."""
    lines = []
    lines.append(f"VDOT: {plan.get('vdot')}")
    lines.append(f"Adjustment: {plan.get('adjustment_factor')}")
    lines.append('')

    for phase in plan.get('phases', []):
        lines.append(f"=== Фаза {phase['phase']}: {phase['name']} ===")
        for week in phase.get('weeks', []):
            if 'trainings' not in week:
                continue
            lines.append(f"  Неделя {week['week']}:")
            for tr in week['trainings']:
                km = tr.get('total_km')
                km_str = f"{km} км" if km is not None else "(описание)"
                lines.append(f"    {tr['day']} ({tr['type']}): {km_str}")
                if 'pace_formatted' in tr:
                    lines.append(f"      темп: {tr['pace_formatted']}")
                if 'description' in tr:
                    lines.append(f"      {tr['description'][:100]}...")
                for b in tr.get('blocks', []):
                    if 'pace_formatted' in b:
                        km_b = b.get('total_km', 0)
                        lines.append(f"      - {b['type']} zone={b.get('zone')}: {b['pace_formatted']}, {km_b} км")
    return '\n'.join(lines)