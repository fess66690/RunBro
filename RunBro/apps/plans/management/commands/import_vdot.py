"""
Импорт VDOT-справочника из Excel.
Читает: data/raw/VDOT.xlsx (прогнозы) + data/raw/TrainingTemp.xlsx (темпы).
"""
from datetime import time, timedelta
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.plans.models import VdotReference


def to_seconds(value) -> int:
    """
    Универсально конвертирует значение из Excel в секунды.
    Поддерживает: datetime.time, datetime.timedelta, int, float, str.
    """
    if value is None:
        return 0

    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second

    if isinstance(value, timedelta):
        return int(value.total_seconds())

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0
        parts = s.split(':')
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return 0
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        if len(nums) == 1:
            return nums[0]

    return 0


class Command(BaseCommand):
    help = 'Импорт VDOT-справочника из Excel (VDOT.xlsx + TrainingTemp.xlsx)'

    def add_arguments(self, parser):
        parser.add_argument('--vdot-file', type=str, default='data/raw/VDOT.xlsx')
        parser.add_argument('--temp-file', type=str, default='data/raw/TrainingTemp.xlsx')
        parser.add_argument('--clear', action='store_true', help='Удалить все записи перед импортом')

    def handle(self, *args, **options):
        vdot_path = Path(options['vdot_file'])
        temp_path = Path(options['temp_file'])

        if not vdot_path.exists():
            raise CommandError(f'Файл не найден: {vdot_path}')
        if not temp_path.exists():
            raise CommandError(f'Файл не найден: {temp_path}')

        self.stdout.write(f'📂 VDOT:         {vdot_path}')
        self.stdout.write(f'📂 TrainingTemp: {temp_path}\n')

        # --- 1. Парсим VDOT.xlsx (прогнозы) ---
        vdot_wb = openpyxl.load_workbook(vdot_path, data_only=True)
        vdot_ws = vdot_wb.active
        vdot_rows = list(vdot_ws.iter_rows(values_only=True))
        vdot_header = vdot_rows[0]
        self.stdout.write(f'   VDOT.xlsx колонки: {vdot_header}')

        vdot_data = {}
        for row in vdot_rows[1:]:
            if row[0] is None:
                continue
            try:
                vdot_value = float(row[0])
            except (TypeError, ValueError):
                continue
            vdot_data[vdot_value] = {
                'predicted_1000m_sec': to_seconds(row[1]),
                'predicted_1500m_sec': to_seconds(row[2]),
                'predicted_mile_sec': to_seconds(row[3]),
                'predicted_3000m_sec': to_seconds(row[4]),
                'predicted_2mile_sec': to_seconds(row[5]),
                'predicted_5k_sec': to_seconds(row[6]),
                'predicted_10k_sec': to_seconds(row[7]),
                'predicted_half_sec': to_seconds(row[8]),
                'predicted_marathon_sec': to_seconds(row[9]),
            }
        self.stdout.write(f'   ✅ Прогнозов: {len(vdot_data)}\n')

        # --- 2. Парсим TrainingTemp.xlsx (темпы) ---
        temp_wb = openpyxl.load_workbook(temp_path, data_only=True)
        temp_ws = temp_wb.active
        temp_rows = list(temp_ws.iter_rows(values_only=True))
        temp_header = temp_rows[0]
        self.stdout.write(f'   TrainingTemp.xlsx колонки: {temp_header}')

        temp_data = {}
        for row in temp_rows[1:]:
            if row[0] is None:
                continue
            try:
                vdot_value = float(row[0])
            except (TypeError, ValueError):
                continue
            temp_data[vdot_value] = {
                'easy_pace_sec': to_seconds(row[1]),
                'marathon_pace_sec': to_seconds(row[2]),
                'threshold_pace_sec': to_seconds(row[3]),
                'interval_pace_sec': to_seconds(row[4]),
                'repetition_pace_200m_sec': to_seconds(row[5]),
                'fast_reps_pace_200m_sec': to_seconds(row[6]),
            }
        self.stdout.write(f'   ✅ Темпов: {len(temp_data)}\n')

        # --- 3. Объединяем и сохраняем ---
        all_vdots = sorted(set(vdot_data.keys()) | set(temp_data.keys()))
        self.stdout.write(f'🔀 Объединяем: {len(all_vdots)} уникальных VDOT')

        with transaction.atomic():
            if options['clear']:
                deleted, _ = VdotReference.objects.all().delete()
                self.stdout.write(f'🗑  Удалено старых: {deleted}')

            created = updated = 0
            for vdot_value in all_vdots:
                data = {}
                data.update(vdot_data.get(vdot_value, {}))
                data.update(temp_data.get(vdot_value, {}))

                obj, is_created = VdotReference.objects.update_or_create(
                    vdot_value=vdot_value,
                    defaults=data,
                )
                if is_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n🎉 Готово! Создано: {created}, обновлено: {updated}'
        ))
        self.stdout.write(f'   Всего в БД: {VdotReference.objects.count()}')