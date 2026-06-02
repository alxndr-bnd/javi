---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-06-02'
inputDocuments:
  - docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md
  - docs/planning-artifacts/briefs/brief-javi-2026-06-01/brief.md
  - docs/planning-artifacts/use-cases-javi.md
workflowType: 'architecture'
project_name: 'Javi'
user_name: 'Alexander'
date: '2026-06-01'
greenfield: true
notes: 'Greenfield — существующий Django orders/ игнорируется (можно удалить). Инфраструктура Cloud Run + CI/CD (SETUP_CICD.md) сохраняется как данность.'
---

# Architecture Decision Document — Javi

_Документ собирается пошагово в коллаборации. Разделы добавляются по мере проработки решений._

_Подход: **greenfield**. Старый код `orders/` (биржа перевозок) не учитывается. Инфраструктура деплоя (GCP Cloud Run, проект `serbito`, регион `europe-west1`, CI/CD по тегу через GitHub Actions) — сохраняется._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:** 26 FR в 7 фичах — настройка/профиль(+origin), приём доставки (гибрид), старт+расчёт ETA, уведомление+каналы, страница статуса+оценка, запрос оценки, статусы магазину. Архитектурно ядро — не CRUD, а оркестрация двух внешних интеграций и фоновых задач вокруг сущности «Доставка».

**Non-Functional Requirements:**
- Производительность: расчёт ETA + отправка < 5 c (синхронный путь при «доставка началась»).
- Надёжность доставки сообщений: фиксация статусов, no-deliver-without-confirmation, идемпотентность.
- Приватность/ПДн (Сербия): минимизация данных на публичной странице, непредсказуемый токен, согласие через договор магазина.
- Локализация: sr (латиница) по умолчанию.
- Мобайл-first для вида магазина/курьера; изоляция арендаторов + rate limit.

**Scale & Complexity:**
- Primary domain: full-stack web (backend-heavy + лёгкий мобильный фронт + публичная страница)
- Complexity level: medium
- Оценочные компоненты: веб-приложение (authed), публичная страница, слой провайдеров (карты, сообщения), планировщик/очередь задач, webhook-приёмник, БД.

### Technical Constraints & Dependencies
- Greenfield: старый Django `orders/` не учитывается (удаляется).
- Инфра задана: GCP Cloud Run (serbito, europe-west1), CI/CD по тегу. Cloud Run scale-to-zero → внешний планировщик для отложенных задач.
- Внешние зависимости: провайдер карт/маршрутов (геокод+ETA+трафик, Сербия); провайдер Viber/SMS (receipts, STOP).

### Cross-Cutting Concerns Identified
- Надёжность внешних провайдеров + fallback (Viber→SMS; маршрут→ручной ETA).
- Асинхронное планирование: ETA+30 для оценки, окно 08:00–22:00 (откладывание).
- Идемпотентность отправок (logical_message_id), дедуп.
- Мульти-арендность и изоляция данных; ПДн/приватность; локализация; юнит-стоимость на доставку.

## Starter Template Evaluation

### Primary Technology Domain
Full-stack web на Django (серверный рендер + лёгкий JS). Бэкенд-тяжёлый сервис с внешними интеграциями и фоновыми задачами на GCP Cloud Run.

### Starter Options Considered
- **cookiecutter-django** (2026.x) — production-ready, но из коробки Celery + Redis + Traefik + docker-compose. На Cloud Run (scale-to-zero) Celery/Redis — анти-паттерн (нужен постоянно живой воркер+брокер); Traefik/compose не нужны (есть Cloud Run + свой Dockerfile + CI/CD). Отклонён: больше выпиливать, чем использовать.
- **Минимальный `django-admin startproject`** — чистая база, добавляем только нужное под serverless. **Выбран.**

### Selected Starter: минимальный Django-проект (greenfield)

**Rationale:** точное соответствие serverless-деплою (Cloud Run scale-to-zero), без баггажа Celery/Redis/Traefik. Async — через Cloud Tasks/Scheduler (HTTP), а не Celery. Переиспользуем уже настроенные Dockerfile + Cloud Run + GitHub Actions.

**Initialization Command:**
```bash
# Python 3.12+; зависимости через uv (или pip + requirements)
uv init javi && cd javi
uv add "Django>=6.0,<6.1" gunicorn "psycopg[binary]" whitenoise
uv run django-admin startproject config .
uv run python manage.py startapp deliveries
```

**Архитектурные решения, заданные базой:**
- **Language & Runtime:** Python 3.12+, **Django 6.0** (выбор заказчика — самый свежий стабильный, май 2026).
- **Frontend:** Django templates (server-rendered) + лёгкий JS; кандидаты прогрессивного UX — HTMX/Alpine (решим в decisions/UX).
- **Build/Serve:** gunicorn; статика через whitenoise; контейнер на базе существующего Dockerfile (nginx-лендинг → Python+gunicorn образ).
- **DB:** PostgreSQL (Cloud SQL) — финализируется в decisions.
- **Async/Schedule:** Cloud Tasks/Cloud Scheduler → защищённые HTTP-эндпоинты (отложенная оценка ETA+30, окно 08:00–22:00) — НЕ Celery.
- **Testing:** pytest-django (предложу в decisions).
- **Code Organization:** `config/` (проект) + доменные apps (`deliveries`, `notifications`, …) — детализируем в decisions.

**Note:** инициализация проекта этой командой — первая story реализации.

## Core Architectural Decisions

### Decision Priority Analysis
- **Critical (блокируют реализацию):** БД, провайдер карт, провайдер сообщений, механизм async, модель данных, auth.
- **Important:** кэш геокодинга, секреты, безопасность вебхуков, порядок каналов.
- **Deferred (post-MVP):** публичный ingest-API (DRF), живой GPS-трекинг, мульти-курьерская диспетчеризация.

### Data Architecture
- **БД:** Cloud SQL for PostgreSQL (минимальный тариф). Django ORM + миграции. Подключение из Cloud Run через Cloud SQL connector.
- **Модель данных (сущности):**
  - **Shop** — owner(User), name, origin_address, origin_lat/lng (геокод), timezone=Europe/Belgrade.
  - **Delivery** — shop, recipient_name, recipient_phone(E.164), dest_address, dest_lat/lng, description?, source(manual|api), status(created|on_the_way|delivered?), eta_at, eta_source(auto|manual), started_at.
  - **Notification** — delivery, kind(on_the_way|rating_request), channel(viber|sms), provider_message_id, logical_message_id (идемпотентность), status(queued|sent|delivered|read|failed), scheduled_for, sent_at.
  - **TrackingToken** — delivery, token (unguessable, `secrets.token_urlsafe`), expires_at.
  - **Rating** — delivery (1:1), value(1–5).
  - **OptOut** — phone(E.164), scope(number|shop) — зеркалит блоклист Infobip, проверяется перед отправкой.
- **Валидация:** телефон через `phonenumbers` (libphonenumber, регион RS); адрес — Geocoding (храним координаты + formatted).
- **Кэш:** результаты геокодинга по нормализованному адресу (срезает стоимость Maps).

### Authentication & Security
- **Магазин:** встроенный Django auth (сессии), email+пароль. Курьер в MVP — общий вход магазина.
- **Публичная страница:** без логина; доступ по unguessable-токену; минимум данных (FR-18); rate-limit; срок жизни токена.
- **Вебхуки Infobip** (receipts/opt-out): проверка подписи/секрета.
- **Колбэки Cloud Tasks:** OIDC-аутентификация (Cloud Tasks → Cloud Run сервис-аккаунтом).
- **Секреты:** Secret Manager (ключи Google Maps, Infobip, Django SECRET_KEY, креды БД) → Cloud Run `--update-secrets`.
- **Изоляция арендаторов:** каждый запрос скоупится по магазину.

### API & Communication Patterns
- **MVP:** серверный рендер Django (публичного REST API нет).
- **Входящие вебхуки:** Infobip delivery/seen + opt-out → обновляют Notification/OptOut.
- **Колбэки Cloud Tasks:** защищённые HTTP-эндпоинты для отложенной отправки (запрос оценки).
- **Абстракции провайдеров:** интерфейсы `MapsProvider` и `MessagingProvider` (Google/Infobip — реализации, легко заменить).
- **Обработка сбоев:** маршрут недоступен → ручной ETA (FR-9); сбой отправки → нативный Viber→SMS failover Infobip (FR-12); логируем + показываем магазину (FR-24/25).
- **Deferred:** DRF ingest-API для Delivery (FR-6).

### Frontend Architecture
- Серверный рендер Django templates; мобайл-first вид магазина/курьера; публичная страница статуса.
- Лёгкий JS; кандидаты HTMX/Alpine для «доставка началась»/оценки без полной перезагрузки (финал — в patterns/UX).
- Статика — whitenoise. i18n — Django i18n, sr (латиница) по умолчанию.

### Infrastructure & Deployment
- GCP Cloud Run (serbito, europe-west1); контейнер на базе существующего Dockerfile (nginx-лендинг → Python+gunicorn); CI/CD по тегу (существующий GitHub Actions).
- **Async = Cloud Tasks** с `scheduleTime`: задача ставится на время отправки (оценка = ETA+30; если вне окна 08:00–22:00 — сдвиг на ближайшее открытие окна). Один механизм закрывает и ETA+30 (FR-21), и окно рассылки (FR-16). Без Celery/Redis.
- Логи — Cloud Logging; Sentry — опционально позже.

### Decision Impact Analysis
- **Последовательность:** init проекта → модель данных + auth → Maps (геокод при создании, ETA при старте) → Infobip (отправка «в пути») → страница статуса → Cloud Tasks (оценка + окно) → вебхуки (receipts/opt-out) → вид статусов магазину.
- **Связи:** Cloud Tasks `scheduleTime` решает разом ETA+30 и окно рассылки; нативный failover Infobip закрывает FR-12; нативный opt-out Infobip покрывает большую часть FR-23 (зеркалим блоклист); кэш геокодинга снижает стоимость Maps; интерфейсы провайдеров изолируют вендоров.

## Implementation Patterns & Consistency Rules

_Стек Django/Python опинионирован — паттерны = идиоматичные Django-дефолты + проектные правила для интеграций и async._

### Naming Patterns
- **Python:** PEP8 — модули `snake_case`, классы `PascalCase`, функции/переменные `snake_case`. Модели в единственном числе: `Shop`, `Delivery`, `Notification`, `TrackingToken`, `Rating`, `OptOut`.
- **БД:** дефолты Django — таблицы `app_model`, колонки `snake_case`, FK `<model>_id`, PK `id` (BigAutoField). Не переопределять `db_table` без причины.
- **URL:** пути lowercase/kebab, именованные `app:view_name`; параметры `<int:pk>`, публичный токен `<str:token>`.
- **Templates:** `app/templates/app/name.html`; партиалы с префиксом `_`.

### Structure Patterns
- **Проект:** `config/` (settings, urls, wsgi/asgi). Доменные apps:
  - `accounts` — пользователи магазина, auth.
  - `deliveries` — `Shop`, `Delivery`, `TrackingToken`; вид магазина/курьера.
  - `notifications` — `Notification`, `OptOut`, отправка, вебхуки.
  - `integrations` — клиенты провайдеров: `base.py` (интерфейсы `MapsProvider`/`MessagingProvider`) + `google_maps.py`, `infobip.py`.
  - `tracking` — публичная страница статуса + оценка.
  - `tasks` — защищённые HTTP-эндпоинты колбэков Cloud Tasks.
- **Бизнес-логика — в `services.py`** каждого app; **views тонкие**; модели = данные + простые методы. Никакой логики провайдеров в views/models — только через `integrations`.
- **Тесты:** `pytest-django`, пакет `tests/` в каждом app (`test_*.py`).
- **Config:** 12-factor, всё из env; секреты — только из Secret Manager, не в коде.

### Format Patterns
- **Дата/время:** хранить в UTC (`USE_TZ=True`), показывать в Europe/Belgrade; в JSON — ISO 8601.
- **Телефон:** хранить в E.164.
- **JSON (вебхуки/таски):** `snake_case`.
- **Идентификатор сообщения:** `logical_message_id` = UUID на каждое намерение отправки (ключ идемпотентности).

### Communication & Process Patterns
- **Идемпотентность:** отправка дедупится по `logical_message_id`; повторный колбэк/клик не плодит сообщений.
- **Внешние вызовы:** таймауты + малые ретраи (только идемпотентные); деградация на fallback (maps→ручной ETA; send→нативный Viber→SMS Infobip).
- **Ошибки:** провайдерские вызовы обёрнуты; пользователю — через Django messages, без утечки внутренностей; в лог — structured (JSON в stdout → Cloud Logging), уровни INFO/ERROR, с корреляцией `delivery_id`.
- **Колбэки Cloud Tasks/вебхуки:** проверка OIDC/подписи; обработчики идемпотентны.
- **Миграции:** по одной на изменение, ревью перед мержем.

### Enforcement Guidelines
**Все агенты ОБЯЗАНЫ:**
- `snake_case` в Python/БД; модели в единственном числе.
- Тонкие views + логика в `services.py`; доступ к провайдерам ТОЛЬКО через `integrations`-интерфейсы.
- Секреты — из env/Secret Manager; хранить время в UTC; телефоны в E.164.
- Идемпотентность отправок через `logical_message_id`.
- Линт/формат — `ruff` (через pre-commit, уже в репо).

### Anti-Patterns (избегать)
- Вызовы Google/Infobip напрямую из views/templates.
- Celery/Redis/долгоживущие воркеры (не для Cloud Run scale-to-zero).
- Хранение локального времени в БД; передача телефона не в E.164.
- Бизнес-логика в моделях/вьюхах вместо services.

## Project Structure & Boundaries

### Complete Project Directory Structure
```
javi/
├── README.md
├── pyproject.toml                      # uv: зависимости + конфиг ruff
├── uv.lock
├── manage.py
├── Dockerfile                          # Python+gunicorn (заменяет nginx-образ Этапа 0)
├── .dockerignore
├── .env.example
├── .pre-commit-config.yaml             # ruff (lint+format)
├── .github/workflows/deploy.yaml       # существующий, деплой по тегу → Cloud Run
├── config/                             # проект
│   ├── settings.py                     # env-driven (django-environ); USE_TZ=True; i18n sr
│   ├── urls.py
│   ├── wsgi.py / asgi.py
├── accounts/                           # пользователи магазина, auth
│   ├── models.py                       # CustomUser (если нужен) / профиль
│   ├── views.py · services.py · urls.py
│   ├── templates/accounts/ · tests/
├── deliveries/                         # ядро: магазин и доставки
│   ├── models.py                       # Shop, Delivery, TrackingToken
│   ├── services.py                     # create_delivery, start_delivery(геокод+ETA), resend
│   ├── views.py · forms.py · urls.py   # мобильный вид магазина/курьера
│   ├── templates/deliveries/ · migrations/ · tests/
├── notifications/                      # сообщения и согласия
│   ├── models.py                       # Notification, OptOut
│   ├── services.py                     # send_on_the_way, schedule_rating_request, send_rating_request
│   ├── webhooks.py                     # Infobip: delivery/seen + opt-out
│   ├── urls.py · tests/
├── integrations/                       # внешние провайдеры (изоляция вендоров)
│   ├── base.py                         # интерфейсы MapsProvider, MessagingProvider
│   ├── google_maps.py                  # geocode, eta (Routes API)
│   ├── infobip.py                      # send viber/sms, receipts, blocklist
│   ├── cache.py                        # кэш геокодинга · tests/
├── tracking/                           # публичная страница (без логина)
│   ├── views.py                        # статус + захват оценки 1–5
│   ├── urls.py · templates/tracking/ · tests/
├── tasks/                              # отложенные задачи Cloud Tasks
│   ├── client.py                       # enqueue с scheduleTime (clamp в окно 08:00–22:00)
│   ├── views.py                        # защищённые OIDC колбэки (отправка rating_request)
│   ├── urls.py · tests/
├── common/                             # кросс-каттинг
│   ├── phone.py                        # E.164 (phonenumbers, RS)
│   ├── timewindow.py                   # окно 08:00–22:00, Europe/Belgrade
│   ├── logging.py                      # structured logging
├── landing/                            # лендинг Этапа 0 — остаётся (whitenoise/отдельный путь)
├── static/ · templates/base.html
```

### Architectural Boundaries
- **API:** публичного REST в MVP нет. Внешние эндпоинты: `/webhooks/infobip/` (подпись), `/tasks/send-rating/` (OIDC), публичный `/t/<token>/` (трекинг). Внутри: views → services → integrations/models.
- **Data:** `deliveries` владеет Shop/Delivery/TrackingToken; `notifications` — Notification/OptOut. Меж-апповый доступ через services, не reach-in в чужие модели.
- **Integration:** любые вызовы Google/Infobip — только через `integrations`-интерфейсы (свап вендора без правок домена).
- **Auth:** `accounts` — сессии магазина; `tracking`/`webhooks`/`tasks` — без сессии, защищены токеном/подписью/OIDC.

### Requirements → Structure Mapping
- **Настройка/origin (FR-1,2)** → `accounts` + `deliveries.Shop`.
- **Приём доставки (FR-3–6)** → `deliveries.services.create_delivery` + `integrations.google_maps`(geocode) + `common.phone`.
- **Старт+ETA (FR-7–10)** → `deliveries.services.start_delivery` + `integrations.google_maps`(eta).
- **Уведомление+каналы+окно (FR-11–16)** → `notifications.services` + `integrations.infobip` + `tasks`(окно).
- **Страница статуса (FR-17–20)** → `tracking`.
- **Запрос+оценка+opt-out (FR-21–23)** → `notifications`(request/opt-out) + `tracking`(capture) + `tasks`(schedule).
- **Статусы магазину (FR-24–26)** → `deliveries.views` + `notifications`(status).

### Data Flow
1. **Создание:** геокод адреса (кэш) → сохранение Delivery.
2. **«Доставка началась»:** ETA через Routes API → сохранить → отправить «в пути» (Infobip) → Notification(`logical_message_id`) → поставить Cloud Task на `clamp(ETA+30, окно)`.
3. **Вебхук Infobip:** обновить статус Notification (delivered/read) / OptOut.
4. **Cloud Task сработал:** `tasks.views` → отправить rating_request (если не отписан и в окне) → Notification.
5. **Получатель** открывает `/t/<token>` → статус; после доставки ставит оценку → Rating; магазин видит статусы+оценку.

### Development & Deployment
- Локально: `uv run python manage.py runserver`; Postgres локально/Docker; `.env` из `.env.example`.
- Сборка: Dockerfile (gunicorn + whitenoise); CI/CD по тегу → Cloud Run; миграции на деплое.
- Cloud SQL через connector; секреты из Secret Manager.

## Architecture Validation Results

### Coherence Validation ✅
- **Совместимость решений:** Django 6.0 + Cloud Run + Cloud SQL Postgres + Cloud Tasks + Google Maps + Infobip — без конфликтов. Async через Cloud Tasks (не Celery) согласован со scale-to-zero.
- **Согласованность паттернов:** snake_case/services/integration-интерфейсы поддерживают принятые решения; вендоры изолированы.
- **Соответствие структуры:** apps (accounts/deliveries/notifications/integrations/tracking/tasks) поддерживают все решения; границы заданы.

### Requirements Coverage Validation
- **FR-1,2** → accounts + Shop ✅
- **FR-3–5** → deliveries + integrations(geocode) + common.phone ✅ · **FR-6** (API) — осознанно отложен ✅
- **FR-7–10** → deliveries.services + google_maps(ETA), ручной fallback ✅
- **FR-11–15** → notifications + infobip (нативный Viber→SMS, receipts) ✅
- **FR-16 (окно)** → tasks + common.timewindow ✅
- **FR-17–20** → tracking ✅
- **FR-21–23** → notifications + tasks(schedule) + tracking(capture); opt-out частично нативный Infobip ✅
- **FR-24–26** → deliveries.views + notifications(status), fix+resend ✅

**NFR:**
- Производительность <5 c: путь «старт» = 1 вызов Routes + enqueue + send (геокод сделан заранее при создании) → реалистично ✅
- Надёжность сообщений: статусы Notification + receipts Infobip ✅
- Приватность/ПДн: минимум на публичной странице, токен, согласие ✅ (срок хранения — открыт)
- Локализация sr ✅ · Мобайл-first ✅ · Безопасность (изоляция, rate-limit, OIDC/подпись) ✅

### Gap Analysis
- **Critical:** нет блокеров реализации.
- **Important (не блокируют старт стройки):** срок хранения ПДн не задан (решить до запуска); lead-time подключения Viber Business (митигейт: флаг «старт на SMS», Viber включить позже); юнит-экономика при €100/мес — бизнес-валидация.
- **Nice-to-have:** Sentry; выбор lib для rate-limit (django-ratelimit) и structured logging; детали Cloud SQL connector.

### Architecture Completeness Checklist
**Requirements Analysis**
- [x] Контекст проанализирован
- [x] Масштаб/сложность оценены
- [x] Тех-ограничения выявлены
- [x] Сквозные заботы картированы

**Architectural Decisions**
- [x] Критические решения с версиями (Django 6.0, провайдеры)
- [x] Стек полностью задан
- [x] Паттерны интеграции определены
- [x] Производительность учтена

**Implementation Patterns**
- [x] Нейминг
- [x] Структурные паттерны
- [x] Коммуникация (вебхуки/таски/идемпотентность)
- [x] Процессы (ошибки/логи/fallback)

**Project Structure**
- [x] Полное дерево
- [x] Границы компонентов
- [x] Точки интеграции
- [x] Маппинг требований на структуру

### Architecture Readiness Assessment
**Overall Status:** READY WITH MINOR GAPS (16/16 чеклиста, критических пробелов нет; открыты неблокирующие: срок хранения ПДн, onboarding Viber, юнит-экономика).
**Confidence Level:** high.
**Key Strengths:** изоляция вендоров за интерфейсами; один механизм (Cloud Tasks scheduleTime) на ETA+30 и окно; перенос failover/opt-out/receipts на Infobip; точное соответствие serverless-деплою.
**Areas for Future Enhancement:** авто-ETA уточнение в пути, мульти-стоп маршруты, публичный ingest-API, живой GPS-трекинг.

### Implementation Handoff
**AI Agent Guidelines:** следовать решениям и паттернам этого документа; провайдеры — только через `integrations`; время UTC; телефоны E.164; идемпотентность по `logical_message_id`.
**First Implementation Priority:** инициализация проекта (`uv init` + Django 6.0 + apps), затем модель данных + auth.
