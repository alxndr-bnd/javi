---
baseline_commit: b53cc91e082092e31f438683faad62bc936e1814
---

# Story 2.1: «Доставка началась» → получатель получает сообщение с ETA

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a владелец магазина/курьер,
I want отметить «Доставка началась» и чтобы покупатель сразу узнал время прибытия,
so that покупатель готов принять, а я не отвечаю на «где заказ?».

**Бизнес-суть (одно предложение):** магазин жмёт «началась» — покупатель получает сообщение, что заказ выехал и ориентировочно к какому времени будет.

## Acceptance Criteria

1. **Given** доставка в группе «Spremno» с геокодированным адресом и магазин с заданным origin, **when** магазин жмёт «Dostava je počela», **then** система рассчитывает ETA = сейчас + время в пути origin→получатель (Google **Routes API**, `TRAFFIC_AWARE`) и сохраняет его на доставке (`eta_at`, `eta_source="auto"`).
2. **Given** рассчитанный ETA, **then** он показывается магазину как «ориентировочно к HH:MM» (верхняя граница, Europe/Belgrade) и получателю в сообщении.
3. **Given** старт доставки, **then** получателю уходит сообщение `Vaša porudžbina iz {prodavnica} je u dostavi. Stiže okvirno do {vreme}. Pratite: {link}` (sr-латиница) через Infobip, и создаётся `Notification(kind=on_the_way)` c `logical_message_id`.
4. **Given** идемпотентность, **when** магазин жмёт «началась» повторно (или ретрай), **then** второе сообщение НЕ отправляется (дедуп по доставке/`logical_message_id`); статус не дублируется.
5. **Given** сбой маршрута/геокода (Routes недоступен, нет координат назначения), **when** магазин жмёт «началась», **then** поток НЕ рвётся: показывается форма ручного ввода ETA (`eta_source="manual"`), и после ввода сообщение уходит (FR-9).
6. **Given** успешный старт, **then** доставка переходит в статус `on_the_way`, её карточка переезжает в группу «U dostavi», магазину показывается подтверждение `Kupac obavešten · stiže do {vreme}`.
7. **Given** отправленное сообщение, **then** оно содержит ссылку на публичную страницу статуса `/t/<token>` (непредсказуемый токен); сама страница — минимальная рабочая (магазин + статус + ETA), брендовая версия со степпером — Story 2.2.
8. **Given** изоляция, **then** стартовать можно только свою доставку (`request.user.shop`); аноним — на вход. Тесты не ходят в реальные Google/Infobip (провайдеры — фейки).
9. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные.

## Tasks / Subtasks

- [x] **Task 1: RoutesProvider — ETA через Google Routes API** (AC: #1, #5, #8)
  - [x] `integrations/base.py`: `RoutesProvider.route_duration_seconds(origin, dest) -> int | None`.
  - [x] `integrations/google_maps.py`: `GoogleRoutesProvider` (computeRoutes, `X-Goog-FieldMask: routes.duration`, DRIVE/TRAFFIC_AWARE, парсинг «845s»→int; ошибки/пусто → None+лог).
  - [x] Фабрика `get_routes_provider()` в `integrations/providers.py`.
- [x] **Task 2: MessagingProvider — отправка через Infobip** (AC: #3, #4, #8)
  - [x] `integrations/base.py`: `SendResult(ok, provider_message_id)`; `MessagingProvider.send_text`.
  - [x] `integrations/infobip.py`: `InfobipProvider` (Viber `/viber/2/messages` или SMS `/sms/2/text/advanced` по `INFOBIP_CHANNEL`, `Authorization: App`, to без «+», парсинг messageId; ошибки → ok=False+лог).
  - [x] Фабрика `get_messaging_provider()`.
- [x] **Task 3: Модель `Notification` + поля ETA на `Delivery`** (AC: #1, #3, #4)
  - [x] `notifications/models.py`: `Notification` (+ UniqueConstraint kind=on_the_way на доставку — гарантия идемпотентности).
  - [x] `deliveries/models.py`: `eta_at`/`eta_source`/`started_at`. Миграции `notifications/0001`, `deliveries/0003`.
  - [x] `Notification` в admin.
- [x] **Task 4: TrackingToken + минимальная публичная страница** (AC: #7)
  - [x] `deliveries/models.py`: `TrackingToken` (1:1, token=`secrets.token_urlsafe(24)`, expires_at).
  - [x] `tracking/views.py` `status(request, token)` — магазин+статус+ETA, без телефона/адреса; 404 неизвестный, 410 протухший; без JS.
  - [x] `tracking/urls.py` + `/t/<token>/` в `config/urls.py`; шаблон `status.html` (мин. брендовый).
- [x] **Task 5: Сервис старта `start_delivery`** (AC: #1–#6)
  - [x] `deliveries/services.py`: `start_delivery(delivery, *, manual_eta=None) -> StartResult` — ETA через Routes (или manual), идемпотентность (статус/Notification), TrackingToken, Notification, отправка через `get_messaging_provider()`, обновление статуса; ссылка через `PUBLIC_BASE_URL` + reverse.
  - [x] `common/timewindow.py`: `format_eta` (Europe/Belgrade «HH:MM»).
- [x] **Task 6: View/URL старта + ручной ETA + список** (AC: #2, #5, #6, #8)
  - [x] `DeliveryStartView` (POST, скоуп по shop; ветка ручного ETA через `ManualEtaForm`); success-тост `Kupac obavešten · stiže do {vreme}`, warning при сбое отправки.
  - [x] `deliveries/urls.py`: `start` → `/app/dostava/<pk>/start/`.
  - [x] `_delivery_card.html`: кнопка «Dostava je počela» (с confirm) в «Spremno», ETA «do HH:MM» в «U dostavi»; шаблон `delivery_manual_eta.html`.
- [x] **Task 7: Конфиг + прод-секреты** (AC: #3)
  - [x] `config/settings.py`: `ROUTES_PROVIDER`, `MESSAGING_PROVIDER`, `INFOBIP_BASE_URL/API_KEY/SENDER/CHANNEL`, `PUBLIC_BASE_URL`.
  - [x] `.env.example`: Infobip-переменные.
  - [x] `deploy.yaml`: `INFOBIP_API_KEY=javi-infobip-key:latest` в `--set-secrets`. Провижн (секрет + Routes API + расширенный ключ) выполнен. **Деплой — отдельный шаг (платная реальная отправка), ждёт go.**
- [x] **Task 8: Тесты (pytest-django, без реальной сети)** (AC: #1–#9)
  - [x] Фейки в `integrations/testing.py`: `FakeRoutesProvider`/`FailingRoutesProvider`, `FakeMessagingProvider`/`FailingMessagingProvider`.
  - [x] `start_delivery`: успех (ETA, on_the_way, Notification sent, токен, текст со ссылкой); идемпотентность (1 отправка); маршрут None → manual-eta-сигнал; manual_eta → отправка; сбой отправки → Notification=failed.
  - [x] View: аноним → 302; чужая доставка → 404; успех → карточка в «U dostavi».
  - [x] `tracking`: валидный токен → 200 (без телефона/адреса), неизвестный → 404, протухший → 410.
  - [x] `manage.py check`, `pytest` (43 passed), `ruff check` — зелёные.

## Dev Notes

### Архитектура и границы (обязательно)

- **Провайдеры только через `integrations`.** ETA — `RoutesProvider`, отправка — `MessagingProvider`; домен (`deliveries.services.start_delivery`) зовёт их через фабрики. Никаких прямых вызовов Google/Infobip из views/models. [Source: architecture.md#API & Communication Patterns, #Architectural Boundaries]
- **Идемпотентность по `logical_message_id`** (UUID на намерение отправки); повторный клик/ретрай не плодит сообщений. [Source: architecture.md#Format Patterns, #Communication & Process Patterns; FR-13]
- **Деградация:** Routes недоступен/нет координат → ручной ETA, поток не рвётся (FR-9). Сбой отправки → Notification=failed, логируем, магазину — мягко (нативный Viber→SMS failover — Story 2.3). [Source: architecture.md#Communication & Process Patterns; prd.md#4.3 FR-9]
- **Время:** хранить UTC (`USE_TZ=True`), показывать Europe/Belgrade; ETA — верхняя граница «do HH:MM». [Source: architecture.md#Format Patterns; prd.md#4.3 FR-10]
- **Приватность публичной страницы:** непредсказуемый токен (`secrets.token_urlsafe`), без телефона/полного адреса (NFR-3, FR-18). [Source: architecture.md#Authentication & Security]
- **NFR-1 (<5 c):** путь старта = 1 вызов Routes + 1 отправка; геокод уже сделан при создании (1.3). [Source: architecture.md#Architecture Validation; prd.md NFR]
- **Изоляция:** старт/доступ к доставке — по `request.user.shop`. [Source: story 1.1–1.3]

### Что уже есть (читать перед правкой)

- **`integrations/`** — `MapsProvider`/`GoogleMapsProvider`/`get_maps_provider` + `GeocodeCache` + кэш (1.2); `testing.py` с фейками. **Добавляем** Routes/Messaging провайдеры и их фабрики рядом. Ключ `GOOGLE_MAPS_API_KEY` уже в settings и теперь разрешает Routes API. [Source: integrations/*; 1.2]
- **`deliveries/models.py`** — `Shop` (origin), `Delivery` (status created/on_the_way/delivered, dest_lat/lng, phone_risk и т.д. из 1.3). **Добавляем** eta_at/eta_source/started_at + `TrackingToken`. [Source: deliveries/models.py; 1.3]
- **`deliveries/services.py`** — `set_shop_origin`, `create_delivery` (паттерн вызова провайдеров). `start_delivery` дописываем. [Source: deliveries/services.py]
- **`deliveries/views.py`** — `DeliveryListView` (группы spremno/u_dostavi/zavrseno), `DeliveryCreateView`, `ShopProfileView`. **Добавляем** `DeliveryStartView`. [Source: deliveries/views.py; 1.3]
- **`_delivery_card.html`** — карточка (имя+адрес+чип). **Добавляем** кнопку старта в «Spremno» и ETA в «U dostavi». [Source: 1.3]
- **`notifications/`, `tracking/`** — пустые скелеты apps (1.1). Наполняем `notifications/models.py` (Notification) и `tracking/` (views/urls/templates). [Source: 1.1 File List]
- **`common/timewindow.py`** — заглушка; можно положить хелпер форматирования ETA (окно 08:00–22:00 нужно для 3.1, не здесь). [Source: common/timewindow.py]
- **`config/urls.py`** — подключить `tracking` на `/t/<token>/`. [Source: architecture.md#Architectural Boundaries]

### Google Routes API — детали

- `POST https://routes.googleapis.com/directions/v2:computeRoutes`
- Headers: `Content-Type: application/json`, `X-Goog-Api-Key: <key>`, `X-Goog-FieldMask: routes.duration` (минимальная маска — дешевле/быстрее).
- Body: `{"origin":{"location":{"latLng":{"latitude":LAT,"longitude":LNG}}},"destination":{...},"travelMode":"DRIVE","routingPreference":"TRAFFIC_AWARE"}`. (departureTime опционально; без него — «сейчас».)
- Ответ: `{"routes":[{"duration":"845s"}]}` — `duration` строка с суффиксом `s` → парсить в int секунд.
- Ключ ограничен Geocoding+Routes (провижн сделан). Биллинг включён.

### Infobip — детали (см. память javi-infobip)

- Base URL аккаунта: `m9dw19.api.infobip.com`. Auth: `Authorization: App <API_KEY>`.
- Viber send: `POST /viber/2/messages`, body `{"messages":[{"sender":"IBSelfServe","destinations":[{"to":"381..."}],"content":{"text":"...","type":"TEXT"}}]}` (to — E.164 без «+»).
- `IBSelfServe` — общий ТЕСТОВЫЙ Viber-sender; прод-Viber требует регистрации (lead-time). Флаг `INFOBIP_CHANNEL` позволяет стартовать на SMS. Полный Viber→SMS failover — Story 2.3.
- Ключ — только из Secret Manager (`javi-infobip-key`), НЕ в коде. Тестовый получатель: `381637740092` (для ручной прод-проверки).

### UX / микрокопирайт (sr-латиница)

- **start action** (UX-DR8): тап «Dostava je počela» шлёт РЕАЛЬНОЕ сообщение → лёгкое подтверждение перед фиксацией (избегаем случайного тапа). Оптимистичный HTMX-отклик — не обязателен в 2.1 (1.x на чистом server-render); достаточно POST → редирект с тостом `Kupac obavešten · stiže do {vreme}`. [Source: EXPERIENCE.md#Component Patterns, #Interaction Primitives]
- **status_chip** «U dostavi» (есть CSS из 1.3: `.chip-on_the_way`). Карточка в «U dostavi» показывает ETA «do HH:MM». [Source: 1.3; DESIGN.md]
- **Сообщение:** `Vaša porudžbina iz {prodavnica} je u dostavi. Stiže okvirno do {vreme}. Pratite: {link}`. [Source: EXPERIENCE.md#Voice and Tone]
- **Публичная страница (мин.):** «Vaša porudžbina je u dostavi», «Stiže okvirno do HH:MM», магазин; без телефона/адреса. Брендовая со степпером — 2.2. [Source: EXPERIENCE.md#Information Architecture; prd FR-18]

### Project Structure Notes

- Соответствует architecture.md#Complete Project Directory Structure: `integrations/{base,google_maps,infobip,providers}.py`, `notifications/models.py`, `tracking/{views,urls,templates}`, `deliveries/{models,services,views,urls}.py`, `common/timewindow.py`.
- Вариация: `TrackingToken` по архитектуре принадлежит `deliveries` (владение Shop/Delivery/TrackingToken). Публичная view — в `tracking`. Меж-апповый доступ — через ORM-связи, без reach-in.
- **Решение по слайсу:** минимальная рабочая страница `/t/<token>/` входит в 2.1 (чтобы ссылка в сообщении не была мёртвой); брендовый вид + степпер + rate-limit/срок ссылки — Story 2.2/FR-20.

### References

- [Source: docs/planning-artifacts/epics.md#Story 2.1] — история, AC, FR-7..15.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.3, #4.4] — FR-7/8/9/10/11/13/15.
- [Source: docs/planning-artifacts/architecture.md] — провайдеры, Notification/TrackingToken, идемпотентность, время, изоляция, NFR-1.
- [Source: docs/planning-artifacts/use-cases-javi.md#Якорный use case] — поток старт→ETA→сообщение, дедуп повторного клика.
- [Source: docs/planning-artifacts/ux-designs/ux-Javi-2026-06-02/EXPERIENCE.md, DESIGN.md] — start action, чип, сообщение, мин. публичная.
- [Source: docs/implementation-artifacts/1-2-shop-origin.md, 1-3-create-delivery.md] — паттерны провайдеров/сервисов/изоляции для переиспользования.

### Решения для разработчика (зафиксировать)

1. **Канал отправки:** старт на `INFOBIP_CHANNEL=viber` (тестовый sender IBSelfServe); флаг позволяет переключить на SMS. Нативный Viber→SMS failover — отдельная Story 2.3 (не дублировать здесь).
2. **Идемпотентность:** дедуп по существованию on_the_way-`Notification` у доставки И/ИЛИ статусу `on_the_way`. Повторный старт — no-op.
3. **Ручной ETA (fallback):** при сбое Routes/нет координат — форма ввода времени прибытия; после ввода — та же отправка. `eta_source` фиксирует auto/manual.
4. **Мин. публичная страница** входит в 2.1 (живая ссылка); брендинг/степпер/срок ссылки — 2.2.
5. **Реальная прод-проверка** шлёт настоящее сообщение (стоит денег) на тест-номер `381637740092` — делать осознанно, после ротации ключа.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Провайдеры в тестах подменяются через `override_settings(ROUTES_PROVIDER/MESSAGING_PROVIDER/MAPS_PROVIDER=...)` фейками из `integrations/testing.py` — без реальных Google/Infobip.
- `FakeMessagingProvider.sent` — класс-уровневый список отправок; тесты сбрасывают его перед прогоном (БД откатывается между тестами).
- Идемпотентность старта — на двух уровнях: проверка в сервисе (статус/Notification) + БД-constraint `uniq_on_the_way_per_delivery`.

### Completion Notes List

- Реализован срез старта доставки: «Dostava je počela» → ETA (Routes API за `RoutesProvider`) → сообщение получателю (Infobip за `MessagingProvider`) + ссылка `/t/<token>` → карточка в «U dostavi». AC#1–#9 ✅ (локально).
- Провайдеры за интерфейсами в `integrations` (Routes/Messaging), фабрики; домен (`start_delivery`) не зовёт вендоров напрямую.
- Идемпотентность по on_the_way-Notification (+ БД-constraint); повторный старт — no-op.
- Мягкая деградация: маршрут недоступен/нет координат → форма ручного ETA (`eta_source=manual`), поток не рвётся (FR-9). Сбой отправки → Notification=failed, статус всё равно on_the_way.
- Мин. публичная страница `/t/<token>` (магазин + статус + ETA, без телефона/адреса; 404/410) — чтобы ссылка в сообщении была живой; брендовый степпер/rate-limit/срок — Story 2.2.
- `Notification`/`TrackingToken` модели + миграции; время UTC, показ Europe/Belgrade («do HH:MM»).
- Проверки: `manage.py check`, `pytest` (43 passed), `ruff check` — зелёные. Тесты без сети.
- **НЕ задеплоено и реальные сообщения НЕ слались** — деплой v0.x шлёт платный Viber/SMS на реальные номера; отдельный gated-шаг (после ротации ключа Infobip). `deploy.yaml` подготовлен (`INFOBIP_API_KEY` секрет). Status → review.

### File List

**Новые:**
- integrations/infobip.py
- notifications/models.py (Notification), notifications/admin.py, notifications/migrations/0001_initial.py, notifications/tests.py(—)
- deliveries/migrations/0003_delivery_eta_at_delivery_eta_source_and_more.py
- deliveries/templates/deliveries/delivery_manual_eta.html
- tracking/views.py, tracking/urls.py, tracking/templates/tracking/status.html, tracking/tests.py

**Изменены:**
- integrations/base.py (RoutesProvider, MessagingProvider, SendResult), integrations/google_maps.py (GoogleRoutesProvider), integrations/providers.py (фабрики), integrations/testing.py (фейки Routes/Messaging), integrations/tests.py(—)
- deliveries/models.py (eta_*/started_at, TrackingToken, _new_tracking_token), deliveries/services.py (start_delivery + StartResult), deliveries/forms.py (ManualEtaForm), deliveries/views.py (DeliveryStartView), deliveries/urls.py (start), deliveries/templates/deliveries/_delivery_card.html, deliveries/tests.py
- common/timewindow.py (format_eta, BELGRADE)
- config/settings.py (ROUTES/MESSAGING/INFOBIP/PUBLIC_BASE_URL), config/urls.py (/t/)
- static/css/app.css (.track*, .card-eta/.card-action)
- .env.example (Infobip), .github/workflows/deploy.yaml (INFOBIP_API_KEY secret)

### Change Log

- 2026-06-04: Story 2.1 реализована локально — старт доставки, расчёт ETA (Routes), уведомление (Infobip), мин. публичная страница статуса, идемпотентность, ручной ETA fallback. 43 теста зелёные. Не задеплоено (реальная платная отправка — отдельный go). Status → review.
