# RunBro

Веб-приложение для построения персонального плана беговых тренировок по
системе Джека Дэниелса. Пользователь выбирает дистанцию и целевое время,
приложение рассчитывает VDOT, подставляет темпы в шаблон плана и сохраняет
персональный план.

## Возможности

- регистрация, вход и выход, смена и восстановление пароля;
- расчёт VDOT по результату на дистанции;
- генерация плана на основе шаблонов для 1000 м, 3000 м, 5 км, 10 км,
  полумарафона и марафона;
- темпы E/M/T/I/R/F, разбивка тренировок на блоки, разминка/заминка,
  серии, интервалы и фартлек;
- расчёт объёма тренировок, в том числе по описаниям в шаблонах;
- отметки о выполнении и прогресс по плану;
- корректировка нагрузки по обратной связи («легко» / «устал») с сохранением
  уже выполненных пунктов;
- печать плана и экспорт в PDF средствами браузера;
- светлая и тёмная тема с сохранением выбора в браузере;
- русская локализация и московский часовой пояс по умолчанию.

## Быстрый старт (Windows / PowerShell)

Требования: Python 3.12+.

```powershell
cd D:\Python\PetProject\RunBro
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_reference_data
python manage.py createsuperuser
python manage.py runserver
```

Приложение будет доступно по адресу <http://127.0.0.1:8000/>.
Админка: <http://127.0.0.1:8000/admin/>.

Для локальной разработки `.env` не обязателен: используются SQLite и
безопасный dev-секрет. Перед production обязательно задайте собственные
значения в `.env` (см. `.env.example`).

## Справочники и шаблоны

В репозитории уже лежат:

- `data/reference/racetypes.json` — дистанции;
- `data/reference/vdot_reference.json` — таблица VDOT;
- `data/templates/*.json` — шаблоны планов.

Команда

```powershell
python manage.py seed_reference_data
```

загружает справочники и импортирует шаблоны. Команда идемпотентна, её можно
запускать повторно. Если нужно обновить только справочники:

```powershell
python manage.py seed_reference_data --skip-templates
```

Исходные Excel-файлы из `data/raw/*.xlsx` не входят в git из-за лицензионных
ограничений. Если они есть локально, можно пересобрать данные командой:

```powershell
python manage.py import_vdot
python manage.py import_plan_templates
```

## Тесты и проверка

```powershell
python manage.py check
python manage.py test
```

## Production

```powershell
$env:DJANGO_ENV = "prod"
$env:DJANGO_SECRET_KEY = "<длинный случайный ключ>"
$env:DJANGO_ALLOWED_HOSTS = "example.com,www.example.com"
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://example.com,https://www.example.com"
$env:DJANGO_DEBUG = "False"

pip install -r requirements-prod.txt
python manage.py migrate
python manage.py seed_reference_data
python manage.py collectstatic --noinput
```

При `DJANGO_ENV=prod` приложение требует явные `DJANGO_SECRET_KEY` и
`DJANGO_ALLOWED_HOSTS`, включает HTTPS-редирект, HSTS и secure-cookies.
Для PostgreSQL задайте `DB_ENGINE=postgresql` и параметры `POSTGRES_*`.
Перед приложением обычно нужен reverse proxy (nginx/Caddy), который передаёт
`X-Forwarded-Proto: https`.

## Структура проекта

```text
apps/
  accounts/   — регистрация и аутентификация
  plans/      — модели, формы, представления и генератор планов
  core/       — общие модели
config/
  settings/   — base/dev/prod-настройки
data/
  reference/  — справочники в JSON (в git)
  templates/  — шаблоны планов (в git)
  raw/        — исходные Excel-файлы (не в git)
static/       — CSS и статические файлы
templates/    — HTML-шаблоны
```

## Объём тренировок

Если в шаблоне указано только описание (например, «2 × 10 мин И + 3 мин
трусцой»), объём рассчитывается по описанию и помечается как оценочный.
Если для длительной тренировки задан только процент недельного километража,
а базы недели недостаточно для правдоподобного расчёта, объём остаётся
неизвестным и не прибавляется к итогу. В интерфейсе такие тренировки
помечаются как «объём не рассчитан», чтобы не показывать вводящие в
заблуждение нули.
