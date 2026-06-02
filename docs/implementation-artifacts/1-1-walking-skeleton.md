# Story 1.1: Вход магазина и кабинет доставок на проде (walking skeleton)

Status: ready-for-dev

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a владелец магазина,
I want войти в Javi и увидеть свой экран доставок,
so that у меня есть рабочее место для доставок, доступное в проде.

**Бизнес-суть (одно предложение):** магазин входит и видит свой (пустой) экран доставок на `javi.serbito.rs`.

## Acceptance Criteria

1. **Given** инициализированный greenfield Django 6 проект (uv) с зарегистрированными apps (accounts, deliveries, notifications, integrations, tracking, tasks, common) и моделью `Shop` (1:1 с пользователем), **when** проект запущен локально, **then** `manage.py check` и `pytest` проходят, `ruff` чист.
2. **Given** пользователь-магазин существует, **when** он входит по **email + паролю** под ролью «магазин», **then** он попадает на мобайл-first экран «Dostave» (Доставки), пока пустой, в светлой теме кабинета, с постоянной кнопкой **«＋ Nova dostava»**.
3. **Given** неавторизованный пользователь, **when** он открывает `/app/` (кабинет), **then** он редиректится на страницу входа.
4. **Given** два разных магазина, **when** каждый смотрит свой экран доставок, **then** он видит только свои доставки (изоляция по `Shop`); сейчас у обоих пусто (empty-state).
5. **Given** существующий живой лендинг Этапа 0, **when** задеплоена эта история, **then** маркетинговый лендинг **остаётся доступен** на `https://javi.serbito.rs/` (сбор заявок Formspree не сломан), а кабинет живёт под `/app/`.
6. **Given** тег `v*.*.*`, **when** срабатывает существующий CI/CD, **then** Django-образ (gunicorn+whitenoise) собирается и деплоится в Cloud Run (serbito, europe-west1), приложение поднимается, вход работает на проде с персистентной БД (Cloud SQL Postgres).

## Tasks / Subtasks

- [ ] **Task 1: Greenfield-скелет проекта (удалить старый Django, сохранить лендинг)** (AC: #1)
  - [ ] Удалить старый Django: `orders/`, проект `transport_site/`, `manage.py` старый, `db.sqlite3` (greenfield — подтверждено заказчиком). **Сохранить** `landing/`, `.github/workflows/deploy.yaml`, `SETUP_CICD.md`, `scripts/`.
  - [ ] `uv init` + `pyproject.toml`; зависимости: `uv add "Django>=6.0,<6.1" gunicorn "psycopg[binary]" whitenoise django-environ`; dev: `uv add --dev pytest-django ruff`.
  - [ ] `uv run django-admin startproject config .` (проект `config/`).
  - [ ] `config/settings.py` env-driven (django-environ): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASES` (Postgres из env; локально — Postgres или env-переключатель), `USE_TZ=True`, `TIME_ZONE="Europe/Belgrade"`, `LANGUAGE_CODE="sr-latn"`, статика через whitenoise, `STATIC_ROOT`. `.env.example`.
  - [ ] `ruff`-конфиг в `pyproject.toml`; обновить `.pre-commit-config.yaml` под Python/ruff; `pytest.ini`/`pyproject` секция pytest-django (`DJANGO_SETTINGS_MODULE=config.settings`).
- [ ] **Task 2: Скелет доменных apps** (AC: #1)
  - [ ] Создать apps: `accounts`, `deliveries`, `notifications`, `integrations`, `tracking`, `tasks`, `common` (`uv run python manage.py startapp <name>` или каталоги). Зарегистрировать в `INSTALLED_APPS`. В 1.1 содержательны только `accounts` и `deliveries`; остальные — пустые скелеты с `apps.py`.
  - [ ] `common/` — заготовки `phone.py`, `timewindow.py`, `logging.py` (пустые/TODO, наполнятся в Epic 2/3).
- [ ] **Task 3: Модель пользователя и Shop + изоляция** (AC: #1, #4)
  - [ ] `accounts`: кастомный `User` (email как логин, без username) ИЛИ email-бэкенд аутентификации; `AUTH_USER_MODEL`.
  - [ ] `deliveries.models.Shop` (1:1 `User`): `name`, поля origin-адреса как заглушки на будущее (origin наполняется в 1.2). Миграции.
  - [ ] Хелпер получения текущего `Shop` по `request.user`; базовый queryset-скоупинг доставок по `shop` (модель Delivery ещё не создаётся — это 1.3; пока экран показывает пустой список, скоупленный по shop).
  - [ ] Минимальный способ завести магазин: management-команда `create_shop` (email, пароль, name) ИЛИ простая регистрация. Для скелета достаточно команды + Django admin.
- [ ] **Task 4: Аутентификация (email+пароль)** (AC: #2, #3)
  - [ ] Вход/выход (Django auth: `LoginView`/`LogoutView` с email-формой), `LOGIN_URL`, `LOGIN_REDIRECT_URL=/app/`.
  - [ ] Экран входа — мобайл-first, светлая тема, бренд Javi.
- [ ] **Task 5: Экран кабинета «Dostave» (пустой) + лейаут** (AC: #2, #4)
  - [ ] `deliveries` view `DeliveryListView` (login_required) под `/app/`: показывает группы (U dostavi / Spremno / Završeno) — сейчас пусто → empty-state «Nema dostava danas».
  - [ ] Постоянная кнопка **«＋ Nova dostava»** (в 1.1 ведёт на заглушку/disabled — форма создаётся в 1.3).
  - [ ] `templates/base.html` (мобайл-first, светлая тема), CSS-переменные из DESIGN.md (bg #f4f6fb, surface #fff, ink #161b29, brand #4f7cff…), system-ui, статика через whitenoise. Строки на сербском (латиница) по EXPERIENCE.md.
- [ ] **Task 6: Маршрутизация + сохранение лендинга** (AC: #5)
  - [ ] `config/urls.py`: `/` → отдаёт существующий лендинг Этапа 0 (TemplateView/`landing/index.html` или static), `/app/` → кабинет (login_required), `/accounts/login|logout/`. `/static/` (whitenoise). Не сломать Formspree-форму лендинга.
  - [ ] Лендинг-ассеты (`landing/og.png`, privacy.html, robots.txt, sitemap.xml) продолжают отдаваться по тем же путям.
- [ ] **Task 7: Контейнер и деплой** (AC: #6)
  - [ ] Заменить `Dockerfile` (nginx Этапа 0 → python:3.12-slim + uv/pip install + gunicorn `config.wsgi` + whitenoise + `collectstatic` + миграции на старте/в entrypoint). Обновить `.dockerignore`.
  - [ ] **БД: переиспользовать существующий инстанс `serbitodb`** (POSTGRES_17, europe-west1, проект serbito) — создать на нём **отдельную базу `javi` + выделенного пользователя `javi`** с правами только на эту базу (изоляция от данных serbito; нулевая доп. стоимость). Подключить Cloud Run `javi` через Cloud SQL connector (instance `serbito:europe-west1:serbitodb`). Креды/`SECRET_KEY` — в Secret Manager, проброс в Cloud Run.
  - [ ] Деплой по тегу через существующий workflow; smoke-check на проде: `https://javi.serbito.rs/` = лендинг, `/app/` = редирект на вход → вход работает.
- [ ] **Task 8: Тесты (pytest-django)** (AC: #1–#4)
  - [ ] Анонимный → `/app/` редиректит на вход (AC#3).
  - [ ] Магазин-A видит свой пустой список; не видит данные магазина-B (AC#4).
  - [ ] Вход по email+паролю успешен; `Shop` создаётся командой/фикстурой.
  - [ ] `manage.py check`, `pytest`, `ruff check` — зелёные (AC#1).

## Dev Notes

- **Greenfield, подтверждено заказчиком:** старый Django (`orders/`, `transport_site/`) удаляется. **Лендинг `landing/` критичен и живой** (Этап 0, собирает заявки Formspree) — не ломать; Django отдаёт его на `/`.
- **Стек (архитектура):** Python 3.12+, **Django 6.0** (актуальный стабильный, май 2026), uv, gunicorn, whitenoise, Cloud SQL Postgres, env-config (django-environ), Secret Manager. НЕ cookiecutter-django, НЕ Celery/Redis. [Source: docs/planning-artifacts/architecture.md#Starter Template Evaluation, #Core Architectural Decisions]
- **Apps и границы:** `config/` + accounts/deliveries/notifications/integrations/tracking/tasks/common; тонкие views + логика в `services.py`; провайдеры только через `integrations` (в 1.1 не задействованы). [Source: architecture.md#Project Structure & Boundaries]
- **Паттерны:** snake_case Python/БД; модели в ед.числе; UTC-хранение (`USE_TZ=True`), показ Europe/Belgrade; email-логин. [Source: architecture.md#Implementation Patterns]
- **UX:** мобайл-first светлая тема «Clean» (токены — DESIGN.md frontmatter); экран «Dostave» с группами и постоянной «＋ Nova dostava»; empty-state; строки sr-латиница. [Source: ux-designs/ux-Javi-2026-06-02/DESIGN.md, EXPERIENCE.md#Information Architecture, #State Patterns]
- **Деплой:** существующий CI/CD (`.github/workflows/deploy.yaml`, тег `v*.*.*` → Cloud Run `javi`, serbito/europe-west1). Меняем только Dockerfile + добавляем Cloud SQL/секреты. [Source: SETUP_CICD.md, architecture.md#Infrastructure & Deployment]
- **Изоляция арендаторов (NFR-6):** любой queryset доставок скоупится по `request.user.shop`.

### Project Structure Notes
- Целевое дерево — см. architecture.md#Complete Project Directory Structure. В 1.1 создаём скелет целиком, наполняем только accounts/deliveries. Delivery-модель и форма — в 1.3 (не здесь).
- Конфликт/вариация: в репо сейчас старый Django-проект + лендинг; 1.1 сносит старый проект, лендинг переносится под отдачу Django (`/`).

### References
- [Source: docs/planning-artifacts/epics.md#Story 1.1] — история, AC.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.1] — FR-1 (вход, изоляция).
- [Source: docs/planning-artifacts/architecture.md] — стек, apps, паттерны, деплой.
- [Source: docs/planning-artifacts/ux-designs/ux-Javi-2026-06-02/DESIGN.md, EXPERIENCE.md] — тема, IA, состояния, микрокопирайт.

### Решения заказчика (зафиксированы 2026-06-03)
1. **БД:** переиспользуем существующий Cloud SQL `serbitodb` (POSTGRES_17, europe-west1) — новая база `javi` + выделенный пользователь, доступ только к ней. Нулевая доп. стоимость, изоляция от serbito. _(Instance connection name: `serbito:europe-west1:serbitodb`.)_
2. **Лендинг + кабинет:** один сервис — Django отдаёт лендинг на `/`, кабинет под `/app/`. Лендинг Этапа 0 (Formspree) не ломать.
3. **Регистрация:** в 1.1 — management-команда `create_shop` (+ admin); полноценная регистрация — отдельная история позже.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed — comprehensive developer guide created.

### File List
