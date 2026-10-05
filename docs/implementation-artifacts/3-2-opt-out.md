---
baseline_commit: a76b56e
---

# Story 3.2: Отписка получателя

Status: done

## Story

As a получатель,
I want отписаться от сообщений,
so that меня не беспокоят, если я не хочу.

**Бизнес-суть (одно предложение):** покупатель может отписаться и больше не получать не-срочные сообщения.

## Acceptance Criteria

1. **Given** полученное сообщение со ссылкой отписки, **when** получатель открывает ссылку отписки на публичной странице, **then** его номер (E.164) попадает в блоклист (`OptOut`), показывается подтверждение «Odjavljeni ste».
2. **Given** нативный STOP в SMS, **when** Infobip присылает opt-out вебхук, **then** номер зеркалится в `OptOut` (идемпотентно, защищено секретом).
3. **Given** номер в блоклисте, **when** планируется/шлётся не-критичное сообщение (запрос оценки), **then** оно НЕ отправляется этому номеру.
4. **Given** отписанный получатель, **when** магазин смотрит доставку в кабинете, **then** видит статус «primalac otkazao obaveštenja».
5. **Given** идемпотентность, **then** повторная отписка не плодит записи; неизвестный/чужой ввод не раскрывает данные.
6. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные; тесты без реальной сети.

## Tasks / Subtasks

- [x] **Task 1: Модель OptOut + хелпер** (AC: #1–#3, #5)
  - [x] `notifications/models.py`: `OptOut` (phone unique, scope, created_at) + миграция `0002`.
  - [x] `notifications/services.py`: `opt_out` (idempotent), `is_opted_out`.
  - [x] `OptOut` в admin.
- [x] **Task 2: Публичная отписка по ссылке** (AC: #1, #5)
  - [x] `tracking/views.py` `unsubscribe(token)` → `opt_out(phone)` + `unsubscribed.html` «Odjavljeni ste».
  - [x] `tracking/urls.py`: `/t/<token>/odjava/`; ссылка «Odjavi se» на `status.html`.
- [x] **Task 3: Infobip opt-out вебхук** (AC: #2, #5)
  - [x] `notifications/webhooks.py` `infobip_optout` (общий `_check_secret`, fail-closed, парсинг `results[].to/phoneNumber/destination`, нормализация «+»).
  - [x] `notifications/urls.py`: `/webhooks/infobip/optout/`.
- [x] **Task 4: Гейт не-критичных сообщений** (AC: #3)
  - [x] `send_rating_request`: `is_opted_out` → no-op без Notification; on_the_way не гейтится.
- [x] **Task 5: Статус отписки в кабинете** (AC: #4)
  - [x] `DeliveryListView`: отписанные номера одним запросом → `d.opted_out`.
  - [x] `_delivery_card.html`: «primalac otkazao obaveštenja».
- [x] **Task 6: Тесты** (AC: #1–#6)
  - [x] opt_out/is_opted_out idempotent; гейт rating_request (нет Notification); публичная отписка → OptOut + «Odjavljeni ste»; opt-out вебхук номер→OptOut / 403; кабинет показывает статус.
  - [x] `manage.py check`, `pytest` (78 passed), `ruff check` — зелёные.

## Dev Notes

### Что уже есть

- `notifications/models.py`: `Notification`. **Добавляем** `OptOut`. [Source: notifications/models.py]
- `notifications/webhooks.py`: `infobip_reports` (секрет, парсинг results). **Добавляем** `infobip_optout` (тот же паттерн секрета). [Source: notifications/webhooks.py; 2.4]
- `deliveries/services.py` `send_rating_request`: есть TODO про opt-out — реализуем гейт. [Source: deliveries/services.py; 3.1]
- `tracking/views.py`: `status`/`rate` + `_active_token`. **Добавляем** `unsubscribe`. [Source: tracking/views.py; 3.1]
- `tracking/templates/tracking/status.html`: добавим ссылку «Odjavi se». [Source: 3.1]
- `_delivery_card.html`: добавим пометку отписки. [Source: 2.4/3.1]

### Архитектура

- `OptOut(phone, scope)` зеркалит блоклист Infobip; проверяется перед отправкой не-критичных (AR-8, FR-23). Нативный opt-out Infobip (STOP) — через вебхук. [Source: architecture.md#Data Architecture, #API & Communication Patterns]
- Вебхук защищён секретом, идемпотентен; логика — в services. [Source: architecture.md#Authentication & Security, #Structure Patterns]
- Не-критичные = запрос оценки (FR-21/23). Транзакционное «в пути» — продолжает слаться (сервисная необходимость). [Source: prd FR-23]
- Публичная отписка — по unguessable-токену, без логина, минимум данных. [Source: NFR-3]

### UX / микрокопирайт (sr-латиница)

- Ссылка на странице: «Odjavi se sa obaveštenja»; после — «Odjavljeni ste». [Source: EXPERIENCE.md#State Patterns «Получатель отписан»]
- Кабинет: «primalac otkazao obaveštenja». [Source: EXPERIENCE.md; FR-23]

### References

- [Source: docs/planning-artifacts/epics.md#Story 3.2] — AC, FR-23.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md] — FR-23.
- [Source: docs/planning-artifacts/architecture.md] — OptOut, вебхуки, блоклист.
- [Source: docs/implementation-artifacts/2-4-notification-status-resend.md, 3-1-rating-request-and-capture.md] — паттерн вебхука/секрета, send_rating_request, токен.
- [[javi-infobip]] — STOP/opt-out нативно у Infobip.

### Решения для разработчика

1. **Scope** — в MVP number-level блоклист (один номер). `scope` поле оставляем для будущего shop-level.
2. **Гейт** — только не-критичные (rating_request). on_the_way не гейтим.
3. **Opt-out вебхук** — тот же секрет, что reports; парсинг номеров гибкий (`results[].to`).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Гейт opt-out тестируется на `send_rating_request` напрямую (фейк-мессенджинг); вебхук — как обычный JSON-POST с `?secret=`.

### Completion Notes List

- Реализована отписка (последняя история MVP): публичная ссылка «Odjavi se» на странице статуса → номер в `OptOut`; нативный STOP Infobip зеркалится через opt-out вебхук; не-критичные (запрос оценки) отписанным не шлются; магазин видит «primalac otkazao obaveštenja». AC#1–#6 ✅ (локально).
- `OptOut` (phone unique, idempotent). Вебхук opt-out fail-closed по `INFOBIP_WEBHOOK_SECRET` (общий с reports).
- Гейт — только не-критичные (rating_request); транзакционное «в пути» продолжает слаться.
- Ссылка отписки — на странице статуса (не в теле сообщения) → риск prefetch-отписки минимален.
- Проверки: `manage.py check`, `pytest` (78 passed), `ruff check` — зелёные. Без сети.
- **НЕ задеплоено.** Прод: opt-out вебхук использует уже подключённый `INFOBIP_WEBHOOK_SECRET`; для приёма STOP — зарегистрировать URL `…/webhooks/infobip/optout/?secret=…` в Infobip. Status → review.

### File List

**Новые:**
- notifications/services.py, notifications/migrations/0002_optout.py
- tracking/templates/tracking/unsubscribed.html

**Изменены:**
- notifications/models.py (OptOut), notifications/admin.py (OptOutAdmin), notifications/webhooks.py (infobip_optout + _check_secret), notifications/urls.py (optout), notifications/tests.py
- deliveries/services.py (гейт opt-out в send_rating_request), deliveries/views.py (d.opted_out), deliveries/templates/deliveries/_delivery_card.html (card-optout), deliveries/tests.py
- tracking/views.py (unsubscribe), tracking/urls.py (unsubscribe), tracking/templates/tracking/status.html (ссылка), tracking/tests.py
- static/css/app.css (.track-unsub, .card-optout)

### Change Log

- 2026-06-04: Story 3.2 реализована локально — отписка (ссылка + opt-out вебхук), блоклист, гейт не-критичных, статус в кабинете. 78 тестов зелёные. Status → review. **Epic 3 и весь MVP-scope закрыты локально.**
- 2026-10-05: Сверка документов: история выпущена в v0.10.0 (7bad688). Status → done.
