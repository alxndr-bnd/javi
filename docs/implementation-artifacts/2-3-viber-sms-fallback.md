---
baseline_commit: 1f91ac2
---

# Story 2.3: Viber-first с авто-fallback на SMS

Status: review

## Story

As a получатель,
I want получать уведомление в Viber (а если недоступен — в SMS),
so that сообщение точно дойдёт удобным каналом.

**Бизнес-суть (одно предложение):** сообщение идёт в Viber, а если не дошло — автоматически в SMS, без дублей.

## Acceptance Criteria

1. **Given** интеграция Infobip (Viber + SMS) и канал по умолчанию `viber`, **when** отправляется уведомление, **then** первая попытка — Viber.
2. **Given** сбой/недоставка Viber (HTTP-ошибка/таймаут/не-ok ответ), **when** Viber не прошёл, **then** авто-fallback на SMS тем же текстом и ссылкой; результат отражает фактический канал (`channel`).
3. **Given** успешный Viber, **then** SMS НЕ отправляется (без дублей по каналам); `Notification.channel = viber`.
4. **Given** `INFOBIP_CHANNEL=sms` (Viber Business ещё не подключён), **when** отправляется уведомление, **then** сразу SMS, без попытки Viber (FR-12/AR-3).
5. **Given** флаг `INFOBIP_SMS_FALLBACK=False`, **when** Viber не прошёл, **then** fallback НЕ выполняется (остаётся failed) — управляемо конфигом.
6. **Given** идемпотентность, **then** одно событие старта = один `Notification` (канал — фактический), повторов по каналам нет.
7. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные; тесты без реальной сети (мок `requests`).

## Tasks / Subtasks

- [x] **Task 1: Failover в InfobipProvider** (AC: #1–#5, #7)
  - [x] `integrations/base.py`: `SendResult.channel`.
  - [x] `integrations/infobip.py`: `_send_viber`/`_send_sms`/`_post`; `send_text` — sms-канал прямой; иначе Viber → при сбое и `sms_fallback` → SMS; `SendResult(ok, message_id, channel)`.
  - [x] `config/settings.py`: `INFOBIP_SMS_FALLBACK` (default True).
- [x] **Task 2: Запись фактического канала** (AC: #2, #3, #6)
  - [x] `start_delivery`: `Notification.channel = result.channel`; один Notification (идемпотентность сохранена).
  - [x] `FakeMessagingProvider` возвращает `channel="viber"`.
- [x] **Task 3: Тесты** (AC: #1–#7)
  - [x] InfobipProvider (мок requests): Viber ok → 1 вызов, channel viber; Viber падает → SMS, channel sms; `channel=sms` → сразу SMS; `sms_fallback=False`+сбой → ok=False, 1 вызов; без ключа → ok=False.
  - [x] `manage.py check`, `pytest` (51 passed), `ruff check` — зелёные.

## Dev Notes

### Что уже есть (читать перед правкой)

- `integrations/infobip.py` (2.1): `InfobipProvider.send_text(to, text)` — один канал по `INFOBIP_CHANNEL` (viber `/viber/2/messages` или sms `/sms/2/text/advanced`), `Authorization: App`, to без «+», парсинг messageId. **Рефакторим** в Viber-first + SMS-fallback. [Source: integrations/infobip.py]
- `integrations/base.py`: `SendResult(ok, provider_message_id)`. **Добавляем** `channel`. [Source: integrations/base.py]
- `deliveries/services.py` `start_delivery`: создаёт `Notification(channel=settings.INFOBIP_CHANNEL)`, шлёт, ставит sent/failed. **Меняем** на `channel=result.channel`. [Source: deliveries/services.py]
- `integrations/testing.py`: `FakeMessagingProvider` (ok=True), `FailingMessagingProvider`. **Дополняем** channel. [Source: integrations/testing.py]
- `Notification.channel` — поле уже есть (viber/sms). [Source: notifications/models.py]

### Архитектура

- Логика каналов — в `integrations` (вендор), не в домене: `start_delivery` просто зовёт `send_text` и пишет `result.channel`. [Source: architecture.md#Architectural Boundaries]
- AR-3/FR-12: Viber→SMS failover. Здесь — app-level fallback по сбою ОТПРАВКИ (HTTP/timeout/не-ok). Failover по delivery-receipt (Viber принял, но не доставил) — зависит от вебхуков (Story 2.4); в MVP достаточно send-time fallback + флаг канала. [Source: architecture.md#API & Communication Patterns; prd FR-12]
- Идемпотентность: один `Notification` на старт (constraint из 2.1); fallback не плодит вторую запись. [Source: 2.1; FR-13]
- Флаг `INFOBIP_CHANNEL=sms` — старт на SMS, пока Viber Business не подключён (lead-time). [Source: architecture.md gap «onboarding Viber»; [[javi-infobip]]]

### References

- [Source: docs/planning-artifacts/epics.md#Story 2.3] — AC, FR-12, AR-3.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.4] — FR-12.
- [Source: docs/implementation-artifacts/2-1-start-eta-notify.md] — InfobipProvider, start_delivery, Notification.

### Решения для разработчика

1. **Триггер fallback** — сбой ОТПРАВКИ (исключение/не-ok/таймаут Viber). Receipt-based (доставлено/не доставлено) — позже (вебхуки 2.4).
2. **Канал в результате** — `SendResult.channel` = фактический; `Notification.channel` пишем из него.
3. **Один Notification** — fallback меняет только канал/исход, не плодит записи.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Failover-логика юнит-тестится моком `integrations.infobip.requests.post` (без сети): проверяется число вызовов и какой endpoint дёргается.

### Completion Notes List

- `InfobipProvider` стал Viber-first с авто-fallback на SMS при сбое отправки (HTTP/таймаут/не-ok). Фактический канал — в `SendResult.channel` → пишется в `Notification.channel`. AC#1–#7 ✅.
- Флаг `INFOBIP_CHANNEL=sms` — старт сразу на SMS (Viber Business не подключён). Флаг `INFOBIP_SMS_FALLBACK` управляет fallback.
- Идемпотентность не нарушена: один `Notification` на старт (constraint), fallback меняет только канал/исход.
- Триггер fallback — сбой ОТПРАВКИ; receipt-based failover (Viber принял, но не доставил) — позже с вебхуками (2.4).
- Проверки: `manage.py check`, `pytest` (51 passed), `ruff check` — зелёные. Без сети. Миграций не требуется.
- НЕ задеплоено (Epic 2 деплой — по go). Status → review.

### File List

**Изменены:**
- integrations/base.py (SendResult.channel), integrations/infobip.py (Viber→SMS failover), integrations/testing.py (FakeMessagingProvider channel), integrations/tests.py (failover-тесты)
- deliveries/services.py (Notification.channel = result.channel)
- config/settings.py (INFOBIP_SMS_FALLBACK)

### Change Log

- 2026-06-04: Story 2.3 реализована локально — Viber-first + авто-fallback на SMS, фактический канал в Notification, флаги канала/fallback. 51 тест зелёный. Status → review.
