---
baseline_commit: bb948cb
---

# Story 2.4: Магазин видит статус уведомления и чинит сбой

Status: review

## Story

As a владелец магазина,
I want видеть, дошло ли и прочитано ли уведомление, и переотправить при сбое,
so that ни один покупатель не остаётся без уведомления.

**Бизнес-суть (одно предложение):** магазин видит, что покупатель получил/прочитал сообщение, а при сбое исправляет номер и шлёт повторно.

## Acceptance Criteria

1. **Given** отправленные уведомления и вебхуки Infobip (delivery/seen receipts), **when** провайдер присылает статус по `messageId`, **then** соответствующий `Notification.status` обновляется (delivered/read/failed) — без «доставлено» без подтверждения провайдера (NFR-2).
2. **Given** входящий вебхук, **then** он защищён (секрет/подпись); неизвестный `messageId` игнорируется без ошибки; обработчик идемпотентен (повторный колбэк не ломает статус).
3. **Given** статус уведомления, **when** магазин смотрит доставку в кабинете, **then** видит чип: `Pročitano` (read) / `Isporučeno` (delivered) / `Nije dostavljeno` (failed) — цвет + текст (a11y, UX-DR3/7).
4. **Given** `Nije dostavljeno`, **when** магазин исправляет телефон и жмёт «Pošalji ponovo» (явное подтверждаемое действие), **then** уведомление переотправляется (тем же текстом/ссылкой), статус сбрасывается в queued→sent/failed; идемпотентность по доставке сохраняется (один on_the_way-Notification).
5. **Given** доставка в пути, **when** магазин (опц.) жмёт «Označi isporučeno», **then** `Delivery.status=delivered` (FR-26); система от этого не зависит.
6. **Given** изоляция, **then** правка/переотправка/отметка — только по своей доставке (`request.user.shop`); вебхук — без логина, по секрету.
7. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные; тесты без реальной сети.

## Tasks / Subtasks

- [x] **Task 1: Входящий вебхук Infobip (receipts)** (AC: #1, #2, #6)
  - [x] `notifications/webhooks.py`: `csrf_exempt` `infobip_reports` — секрет (query/заголовок, fail-closed), парсинг `results[]`, матч по `provider_message_id`, маппинг DELIVERED→delivered/seen→read/UNDELIVERABLE|REJECTED|EXPIRED→failed; no-downgrade (`_apply`); неизвестный id — тихо.
  - [x] `notifications/urls.py` + `/webhooks/infobip/reports/` в `config/urls.py`.
  - [x] `config/settings.py`: `INFOBIP_WEBHOOK_SECRET`.
- [x] **Task 2: Сервис переотправки** (AC: #4)
  - [x] `deliveries/services.py`: `resend_on_the_way(delivery, new_phone=None)` — правит номер, переиспользует on_the_way-Notification (новый `logical_message_id`, queued→sent/failed), один Notification. Рефактор: `_on_the_way_text`/`_send_and_record` общие со start.
- [x] **Task 3: Кабинет — чип статуса уведомления + действия** (AC: #3, #4, #5)
  - [x] `DeliveryResendView` (форма `RecipientPhoneForm`), `DeliveryMarkDeliveredView`; скоуп по shop.
  - [x] `deliveries/urls.py`: `resend`, `mark_delivered`.
  - [x] `_delivery_card.html`: nchip (Pročitano/Isporučeno/Nije dostavljeno); при failed — поле номера + «Pošalji ponovo» (confirm); в «U dostavi» — «Označi isporučeno».
  - [x] `app.css`: `.nchip-read/.nchip-delivered/.nchip-failed`.
  - [x] `DeliveryListView`: `prefetch_related("notifications")` + `on_the_way_notif` без N+1.
- [x] **Task 4: Тесты** (AC: #1–#7)
  - [x] Вебхук: DELIVERED→delivered; seen→read; UNDELIVERABLE→failed; неверный секрет→403; неизвестный id→200; no-downgrade read.
  - [x] `resend_on_the_way`: номер сохраняется, один Notification, channel/sent.
  - [x] View: чужая доставка resend/mark→404; resend success; mark-delivered→delivered.
  - [x] `manage.py check`, `pytest` (62 passed), `ruff check` — зелёные.

## Dev Notes

### Что уже есть (читать перед правкой)

- `notifications/models.py` (2.1): `Notification` (status queued/sent/delivered/read/failed, `provider_message_id`, `logical_message_id`, kind on_the_way, constraint один on_the_way/доставку). [Source: notifications/models.py]
- `integrations/infobip.py` (2.3): `InfobipProvider.send_text` Viber→SMS, `SendResult.channel`. Переиспользуем для resend. [Source: integrations/infobip.py]
- `deliveries/services.py` (2.1/2.3): `start_delivery` пишет Notification + provider_message_id + channel. Resend — рядом или в `notifications/services.py`. [Source: deliveries/services.py]
- `deliveries/views.py`/`urls.py`: `DeliveryStartView`, список с группами. Добавляем resend/mark. [Source: deliveries/views.py]
- `_delivery_card.html`: имя+адрес+чип статуса доставки, кнопка старта/ETA. Добавляем чип уведомления + действия. [Source: 2.1/2.2]
- `common/phone.py`: `normalize_phone`/`PhoneResult`/`InvalidPhone` — для правки номера при resend. [Source: 1.3]
- `notifications/webhooks.py` — по architecture именно тут вебхуки. [Source: architecture.md#Project Structure]

### Архитектура

- Вебхуки Infobip (delivery/seen + opt-out) → обновление Notification/OptOut (AR-7). Здесь — delivery/seen receipts; opt-out — Story 3.2. [Source: architecture.md#API & Communication Patterns]
- Безопасность вебхука: проверка секрета/подписи; обработчик идемпотентен; без логина. [Source: architecture.md#Authentication & Security, #Communication & Process Patterns; NFR-6]
- NFR-2: статус «доставлено» только по подтверждению провайдера — не выставляем сами. [Source: architecture.md#Reliability]
- Resend — явное подтверждаемое действие (не авто-ретрай); идемпотентность доставки (один on_the_way-Notification) сохраняется, меняется logical_message_id. [Source: FR-25, FR-13]
- Логика — в services; вьюхи тонкие; провайдер только через integrations. [Source: architecture.md#Structure Patterns]

### Infobip delivery reports — формат (для парсинга)

- Push delivery reports: `{"results":[{"messageId":"...","status":{"groupName":"DELIVERED|PENDING|UNDELIVERABLE|EXPIRED|REJECTED",...}, ...}]}`.
- Viber «seen»/read — отдельное событие (признак seen / status group). Маппинг: DELIVERED→`delivered`; seen/read→`read`; UNDELIVERABLE/REJECTED/EXPIRED→`failed`; PENDING — без изменения.
- Матчинг по `messageId` ↔ `Notification.provider_message_id`. Регистрация URL вебхука в консоли Infobip — внешний шаг (как ключ); тут — endpoint + секрет.

### UX / микрокопирайт (sr-латиница)

- Чип уведомления (UX-DR3/7): `Pročitano` (read, `--read`), `Isporučeno` (delivered, `--delivered`), `Nije dostavljeno` (failed, `--failed`) — цвет + текст. [Source: DESIGN.md status_chip; EXPERIENCE.md State Patterns]
- При `Nije dostavljeno`: поле телефона + «Pošalji ponovo» (confirm перед реальной отправкой). [Source: EXPERIENCE.md#State Patterns «Недоставлено»]
- «Označi isporučeno» — вторичное действие. [Source: FR-26]

### References

- [Source: docs/planning-artifacts/epics.md#Story 2.4] — AC, FR-14/24/25/26, AR-7.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.7] — FR-24/25/26; #4.4 FR-14.
- [Source: docs/planning-artifacts/architecture.md] — вебхуки, безопасность, NFR-2, services.
- [Source: docs/implementation-artifacts/2-1-start-eta-notify.md, 2-3-viber-sms-fallback.md] — Notification, send, channel.

### Решения для разработчика

1. **Секрет вебхука** — общий секрет в query/заголовке (`INFOBIP_WEBHOOK_SECRET`); полноценная подпись — если Infobip её даёт для нашего канала.
2. **Resend** — обновляет существующий on_the_way-Notification (новый logical_message_id), не плодит записи; правка номера — опциональна.
3. **read vs delivered** — read только если канал подтвердил seen (Viber); SMS обычно только delivered.
4. **Mark delivered** — простое действие, статус доставки; уведомление-receipts независимы.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Вебхук тестируется как обычный POST (`content_type=application/json`, `?secret=`); провайдеры не нужны.
- No-downgrade: тест `read`→`DELIVERED` оставляет `read` (порядок `_ORDER`).

### Completion Notes List

- Реализован замыкающий срез Epic 2: вебхук Infobip receipts → `Notification.status` (delivered/read/failed), чип статуса в кабинете, правка номера + переотправка, ручная отметка «Доставлено». AC#1–#7 ✅ (локально).
- Вебхук fail-closed: без `INFOBIP_WEBHOOK_SECRET` или при неверном секрете → 403. Идемпотентность + no-downgrade статусов. NFR-2: «доставлено/прочитано» только из колбэка провайдера.
- Resend — явное действие: переиспользует единственный on_the_way-Notification (новый `logical_message_id`), без дублей; опц. правка номера (E.164).
- Рефактор: `_on_the_way_text`/`_send_and_record` общие для start и resend.
- Проверки: `manage.py check`, `pytest` (62 passed), `ruff check` — зелёные. Миграций не требуется.
- **НЕ задеплоено.** Для работы вебхука в проде нужно: (1) провижн секрета `javi-infobip-webhook-secret` + проброс в `deploy.yaml`; (2) регистрация URL `https://javi.serbito.rs/webhooks/infobip/reports/?secret=…` в консоли Infobip (внешний шаг). Status → review.

### File List

**Новые:**
- notifications/webhooks.py, notifications/urls.py, notifications/tests.py

**Изменены:**
- config/settings.py (INFOBIP_WEBHOOK_SECRET), config/urls.py (/webhooks/)
- deliveries/services.py (resend_on_the_way + _on_the_way_text/_send_and_record рефактор), deliveries/forms.py (RecipientPhoneForm), deliveries/views.py (DeliveryResendView, DeliveryMarkDeliveredView, чип в списке), deliveries/urls.py (resend/mark_delivered), deliveries/templates/deliveries/_delivery_card.html, deliveries/tests.py
- static/css/app.css (.nchip*)
- .env.example (INFOBIP_WEBHOOK_SECRET)

### Change Log

- 2026-06-04: Story 2.4 реализована локально — вебхук receipts, статус уведомления у магазина, правка номера + переотправка, ручная отметка. 62 теста зелёные. Status → review. (Прод: секрет вебхука + регистрация URL в Infobip — отдельный шаг.)
