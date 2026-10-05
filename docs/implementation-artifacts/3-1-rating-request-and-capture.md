---
baseline_commit: b592298
---

# Story 3.1: Запрос оценки через ETA+30 и оценка 1–5

Status: done

## Story

As a получатель,
I want оценить доставку после получения,
so that магазин понимает качество, а я влияю на сервис.

**Бизнес-суть (одно предложение):** через полчаса после ожидаемого прибытия покупатель получает запрос и ставит оценку доставке, а магазин видит звёзды.

## Acceptance Criteria

1. **Given** доставка с расчётным ETA, **when** магазин жмёт «Dostava je počela» (старт), **then** планируется отложенная задача отправки запроса оценки на `clamp(ETA + 30 мин, окно 08:00–22:00 Europe/Belgrade)` — вне окна сдвиг на ближайшее открытие (FR-16, AR-4).
2. **Given** наступило запланированное время, **when** срабатывает защищённый колбэк задачи, **then** получателю уходит `Kako je prošla dostava iz {prodavnica}? Ocenite: {link}` (sr-латиница) и создаётся `Notification(kind=rating_request)`; идемпотентно (один rating_request на доставку).
3. **Given** колбэк задачи, **then** он защищён (секрет/OIDC); без валидной аутентификации — 403.
4. **Given** получатель на странице статуса (после доставки/в пути), **when** он касается звезды 1–5, **then** оценка сохраняется (Rating, 1:1 с доставкой) без логина, одним касанием (без отдельной кнопки), затем видна «Hvala!».
5. **Given** повторная оценка, **when** получатель ставит снова, **then** дубли не плодятся (оценка обновляется, не создаётся вторая).
6. **Given** магазин в кабинете, **then** он видит оценку доставки (звёзды/число).
7. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные; тесты без реальной сети/Cloud Tasks (планировщик и мессенджинг — фейки).

## Tasks / Subtasks

- [x] **Task 1: Окно рассылки (clamp 08:00–22:00)** (AC: #1, #7)
  - [x] `common/timewindow.py`: `clamp_to_window` + `rating_send_time` (ETA+30, прижато к окну).
- [x] **Task 2: Планировщик задач (абстракция + Cloud Tasks)** (AC: #1, #3)
  - [x] `tasks/scheduler.py`: `TaskScheduler`/`NoopTaskScheduler`(дефолт)/`CloudTasksScheduler`(lazy google-cloud-tasks) + `get_task_scheduler()`.
  - [x] settings: `TASK_SCHEDULER`/`TASKS_SECRET`/`CLOUD_TASKS_*`.
  - [x] Зависимость `google-cloud-tasks` (lazy; Noop локально без неё).
- [x] **Task 3: Колбэк отправки запроса оценки** (AC: #2, #3)
  - [x] `tasks/views.py` `send_rating` — fail-closed по `TASKS_SECRET`, идемпотентно; `tasks/urls.py` + `/tasks/`.
  - [x] `deliveries/services.send_rating_request` — текст + Notification(rating_request) + дедуп.
- [x] **Task 4: Планирование при старте** (AC: #1)
  - [x] `start_delivery` → `get_task_scheduler().schedule_rating_request(id, rating_send_time(eta))`.
- [x] **Task 5: Модель Rating + захват на странице статуса** (AC: #4, #5)
  - [x] `deliveries/models.py`: `Rating` (1:1, 1–5) + миграция `0005`.
  - [x] `tracking/views.py` `rate` (update_or_create, без дублей, PRG); звёзды (5 submit, без JS, aria-label) когда on_the_way/delivered и нет оценки → «Hvala!».
  - [x] `tracking/urls.py`: `rate` → `/t/<token>/oceni/`; CSS `.stars/.star/.rate-done`.
- [x] **Task 6: Оценка в кабинете** (AC: #6)
  - [x] `_delivery_card.html`: `card-rating` (звёзды); `DeliveryListView` `select_related("rating")`.
- [x] **Task 7: Тесты** (AC: #1–#7)
  - [x] timewindow clamp/rating_send_time; start планирует rating (фейк-scheduler); колбэк 403/идемпотентность; захват 1–5 + обновление без дублей + невалид отклонён + «Hvala!»; кабинет показывает оценку (через card-rating).
  - [x] `manage.py check`, `pytest` (72 passed), `ruff check` — зелёные.

## Dev Notes

### Что уже есть (читать перед правкой)

- `common/timewindow.py`: `format_eta`, `BELGRADE`. **Добавляем** `clamp_to_window`/`rating_send_time`. [Source: common/timewindow.py]
- `deliveries/services.py` `start_delivery`: считает ETA, шлёт on_the_way, создаёт TrackingToken. **Добавляем** планирование rating. [Source: deliveries/services.py]
- `notifications/models.py` `Notification`: kind уже включает `rating_request`. Constraint уникальности — только on_the_way; для rating_request дедуп в колбэке. [Source: notifications/models.py]
- `tracking/views.py` `status`: рендерит брендовую страницу. **Добавляем** блок оценки + `rate`. [Source: tracking/views.py]
- `integrations/providers.py` `get_messaging_provider`: переиспользуем для отправки запроса. [Source: integrations/providers.py]
- `tasks/` — пустой скелет app (1.1). Наполняем scheduler/views/urls. [Source: architecture.md#Project Structure]
- `_delivery_card.html` — добавляем показ оценки. [Source: 2.4]

### Архитектура

- **Async = Cloud Tasks `scheduleTime`** (НЕ Celery): один механизм на ETA+30 и окно рассылки (clamp). Колбэк — защищённый HTTP-эндпоинт. [Source: architecture.md#Infrastructure & Deployment, #API & Communication Patterns; AR-4]
- Абстракция планировщика за интерфейсом (как maps/messaging): `NoopTaskScheduler` локально (без реальных задач), `CloudTasksScheduler` в проде по флагу. Тесты — фейк. [Source: architecture.md#Architectural Boundaries]
- Колбэк идемпотентен + защищён (секрет/OIDC); опт-аут (не слать отписанным) — Story 3.2 (здесь задел: проверка opt-out можно добавить позже). [Source: architecture.md#Authentication & Security; FR-21/23]
- Окно 08:00–22:00 Europe/Belgrade — `common/timewindow`. [Source: architecture.md; FR-16]
- Оценка без логина на публичной странице, идемпотентно (1:1), минимум данных. [Source: prd FR-19/22; NFR-3]
- Логика — в services/scheduler; вьюхи тонкие; провайдеры — через integrations. [Source: architecture.md#Structure Patterns]

### UX / микрокопирайт (sr-латиница)

- **rating_stars** (UX-DR5): тап по звезде = отправка (без отдельной кнопки), затем «Hvala!». Без JS — каждая звезда submit-кнопка; aria-label «Ocena {n} od 5»; тач-цель ≥48px; цвет `--rating`. [Source: DESIGN.md rating_stars; EXPERIENCE.md#Component Patterns, #Accessibility Floor]
- Сообщение запроса: `Kako je prošla dostava iz {prodavnica}? Ocenite: {link}`. [Source: EXPERIENCE.md#Voice and Tone]
- После оценки: «Hvala!». [Source: EXPERIENCE.md]

### Cloud Tasks — детали (для CloudTasksScheduler/прод)

- HTTP-задача: `CreateTask` в очередь (location europe-west1), `http_request` POST на `{SERVICE_URL}/tasks/send-rating/<id>/?secret=…`, `schedule_time` = `run_at` (UTC). Прод-грейд аутентификация — OIDC (SA), в MVP — общий секрет (документировать). Очередь + права SA — провижн (внешний/gated шаг, как секреты).

### References

- [Source: docs/planning-artifacts/epics.md#Story 3.1] — AC, FR-19/21/22/24-rating/16, AR-4, UX-DR5.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.5, #4.6] — FR-19/21/22; окно FR-16.
- [Source: docs/planning-artifacts/architecture.md] — Cloud Tasks, окно, идемпотентность, Rating, границы.
- [Source: docs/implementation-artifacts/2-1-start-eta-notify.md, 2-2-public-status-page.md, 2-4-notification-status-resend.md] — start, страница, Notification, секрет-защита эндпоинта.

### Решения для разработчика

1. **Планировщик** — абстракция; дефолт Noop (локально/тесты ничего не шлют). Реальный Cloud Tasks — по флагу `TASK_SCHEDULER` + провижн очереди/SA (gated).
2. **Защита колбэка** — общий секрет `TASKS_SECRET` (MVP); OIDC — апгрейд позже.
3. **rating_request идемпотентность** — дедуп по наличию rating_request-Notification у доставки.
4. **Показ блока оценки** — когда статус on_the_way/delivered и оценки ещё нет; opt-аут (3.2) позже исключит отписанных из рассылки.
5. **Опт-аут (3.2)** не в скоупе; колбэк пока шлёт всем (задел на проверку OptOut оставить TODO).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Планировщик/мессенджинг в тестах — фейки через `override_settings(TASK_SCHEDULER/MESSAGING_PROVIDER=...)`; `RecordingTaskScheduler.scheduled` собирает запланированные задачи.
- google-cloud-tasks подключён lazy внутри `CloudTasksScheduler` — локально/в тестах не импортируется (дефолт Noop).

### Completion Notes List

- Реализован срез оценки: при старте планируется запрос оценки на `clamp(ETA+30, 08:00–22:00)`; колбэк по секрету шлёт `Kako je prošla dostava…`; получатель ставит 1–5 одним касанием на странице статуса (без JS, без логина), видит «Hvala!»; магазин видит оценку в кабинете. AC#1–#7 ✅ (локально).
- Планировщик за абстракцией: `NoopTaskScheduler` (дефолт, безопасно локально), `CloudTasksScheduler` (прод). Колбэк fail-closed по `TASKS_SECRET`, идемпотентный (один rating_request).
- Окно 08:00–22:00 (Europe/Belgrade) — `clamp_to_window`; вне окна сдвиг на ближайшее открытие.
- Оценка 1:1, `update_or_create` — повтор не плодит дубли; невалидное значение игнорируется.
- Opt-out (3.2) пока не учитывается — TODO в `send_rating_request` (не слать отписанным).
- Проверки: `manage.py check`, `pytest` (72 passed), `ruff check` — зелёные. Без сети/Cloud Tasks.
- **НЕ задеплоено.** Для авто-рассылки оценки в проде нужно (gated): создать очередь Cloud Tasks `javi-rating` (europe-west1), провижн `javi-tasks-secret`, выставить `TASK_SCHEDULER=…CloudTasksScheduler` + env/секрет в `deploy.yaml`, права SA (cloudtasks.enqueuer + при OIDC — actAs). Захват оценки на странице работает и без этого. Status → review.

### File List

**Новые:**
- tasks/scheduler.py, tasks/views.py, tasks/urls.py, tasks/testing.py, tasks/tests.py
- deliveries/migrations/0005_rating.py

**Изменены:**
- common/timewindow.py (clamp_to_window, rating_send_time), common/tests.py (тесты окна)
- deliveries/models.py (Rating), deliveries/services.py (send_rating_request + планирование при старте), deliveries/views.py (select_related rating), deliveries/templates/deliveries/_delivery_card.html (card-rating)
- config/settings.py (TASK_SCHEDULER/TASKS_SECRET/CLOUD_TASKS_*), config/urls.py (/tasks/)
- tracking/views.py (rate + блок оценки в status), tracking/urls.py (rate), tracking/templates/tracking/status.html (звёзды/Hvala), tracking/tests.py (тесты оценки)
- static/css/app.css (.stars/.star/.rate-done/.card-rating)
- pyproject.toml, uv.lock (google-cloud-tasks)

### Change Log

- 2026-06-04: Story 3.1 реализована локально — запрос оценки (ETA+30, Cloud Tasks абстракция + окно), захват 1–5 на странице, оценка в кабинете. 72 теста зелёные. Status → review. (Прод-рассылка: очередь Cloud Tasks + секрет — отдельный шаг.)
- 2026-10-05: Сверка документов: история выпущена в v0.9.0 (a76b56e); прод-рассылка через Cloud Tasks — v0.11.0 (6816d9f). Status → done.
