"""
Импорт шаблонов планов из JSON-файлов.

Читает все *.json из data/templates/ и создает/обновляет
StandardPlanTemplate в БД.

Использование:
    python manage.py import_plan_templates
    python manage.py import_plan_templates --clear   # удалить старые шаблоны
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.plans.models import RaceType, StandardPlanTemplate


# Соответствие: ключ в JSON → имя RaceType в БД.
RACE_TYPE_MAPPING = {
    '1000m':    '1000 м',
    '3000m':    '3000 м',
    '5000m':    '5000 м',
    '5km':      '5000 м',
    '10km':     '10 км',
    '10 km':    '10 км',
    '10к':      '10 км',
    'half':     'Полумарафон',
    'half_marathon': 'Полумарафон',
    '21100m':   'Полумарафон',
    'marathon': 'Марафон',
    '42195m':   'Марафон',
}

# Дистанции для автоматического создания RaceType.
RACE_TYPE_DEFAULTS = {
    '1000 м': 1.0,
    '3000 м': 3.0,
    '5000 м': 5.0,
    '10 км': 10.0,
    'Полумарафон': 21.1,
    'Марафон': 42.195,
}


class Command(BaseCommand):
    help = 'Импорт шаблонов планов из data/templates/*.json'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dir',
            type=str,
            default='data/templates',
            help='Папка с JSON-шаблонами (относительно BASE_DIR)',
        )
        parser.add_argument(
            '--file',
            type=str,
            help='Импортировать один JSON-файл из папки --dir, например 3000m.json',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Удалить все StandardPlanTemplate перед импортом',
        )

    def handle(self, *args, **options):
        templates_dir = Path(options['dir'])
        if not templates_dir.is_absolute():
            templates_dir = Path(settings.BASE_DIR) / templates_dir
        if not templates_dir.exists():
            raise CommandError(f'Папка не найдена: {templates_dir}')

        selected_file = options.get('file')
        if selected_file and options['clear']:
            raise CommandError('Параметр --clear нельзя использовать вместе с --file.')
        if selected_file:
            json_path = templates_dir / selected_file
            if not json_path.is_file() or json_path.suffix.lower() != '.json':
                raise CommandError(f'JSON-файл не найден: {json_path}')
            json_files = [json_path]
        else:
            json_files = sorted(templates_dir.glob('*.json'))
        if not json_files:
            raise CommandError(f'В папке {templates_dir} нет *.json файлов')

        self.stdout.write(f'[dir] Папка: {templates_dir}')
        self.stdout.write(f'[files] Найдено файлов: {len(json_files)}\n')

        # --- Опционально: очистка ---
        if options['clear']:
            with transaction.atomic():
                deleted, _ = StandardPlanTemplate.objects.all().delete()
                self.stdout.write(f'[deleted] Удалено старых шаблонов: {deleted}\n')

        created_count = 0
        updated_count = 0
        errors = []

        for json_path in json_files:
            try:
                result = self._import_one(json_path)
                if result == 'created':
                    created_count += 1
                elif result == 'updated':
                    updated_count += 1
            except Exception as e:
                errors.append((json_path.name, str(e)))
                self.stdout.write(self.style.ERROR(
                    f'   [error] {json_path.name}: {e}'
                ))

        # --- Итог ---
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'[ok] Готово! Создано: {created_count}, обновлено: {updated_count}'
        ))
        if errors:
            self.stdout.write(self.style.WARNING(
                f'   [warn] Ошибок: {len(errors)}'
            ))
            for name, err in errors:
                self.stdout.write(f'     - {name}: {err}')

    def _import_one(self, json_path: Path) -> str:
        """Импорт одного JSON. Возвращает 'created' / 'updated' / 'skipped'."""
        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)

        race_key = data.get('race_type')
        if not race_key:
            raise ValueError('В JSON нет поля "race_type"')

        # Ищем RaceType по маппингу
        race_name = RACE_TYPE_MAPPING.get(race_key)
        if not race_name:
            raise ValueError(
                f'Нет маппинга для "{race_key}". '
                f'Добавь в RACE_TYPE_MAPPING.'
            )

        race_type, _ = RaceType.objects.update_or_create(
            name=race_name,
            defaults={
                'distance_km': RACE_TYPE_DEFAULTS.get(race_name, 0),
                'default_plan_weeks': 24,
            },
        )

        # Считаем количество недель из phases
        weeks_count = self._count_weeks(data)

        # Имя шаблона
        template_name = f'План {race_name} ({weeks_count} нед.)'

        # Если у дистанции уже был другой шаблон по умолчанию
        # (например, после изменения количества недель), снимаем с него флаг,
        # чтобы create_plan_for_user не выбрал устаревший вариант.
        StandardPlanTemplate.objects.filter(
            race_type=race_type,
            is_default=True,
        ).exclude(name=template_name).update(is_default=False)

        # Создаем/обновляем
        _, created = StandardPlanTemplate.objects.update_or_create(
            name=template_name,
            race_type=race_type,
            defaults={
                'weeks_count': weeks_count,
                'is_default': True,
                'description': data.get('description', ''),
                'structure': data,
            },
        )

        action = 'created' if created else 'updated'
        icon = '[new]' if created else '[upd]'
        self.stdout.write(
            f'   {icon} {json_path.name} → "{template_name}" '
            f'({action}, {weeks_count} нед.)'
        )
        return action

    def _count_weeks(self, data: dict) -> int:
        """
        Считает общее количество недель в плане.
        Учитывает, что недели могут быть как число (7), так и диапазон ("1-3").
        """
        total = 0
        for phase in data.get('phases', []):
            for week in phase.get('weeks', []):
                w = week.get('week')
                if isinstance(w, int):
                    total += 1
                    continue
                if not isinstance(w, str):
                    continue
                match = re.fullmatch(r'\s*(\d+)\s*[-–—]\s*(\d+)\s*', w)
                if match:
                    # "1-3" → 3 недели
                    start, end = (int(part) for part in match.groups())
                    total += max(0, end - start + 1)
                elif w.strip().isdigit():
                    total += 1
        return total