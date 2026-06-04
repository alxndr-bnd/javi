---
baseline_commit: 211659b47ee1ef3d874a5db838e5f26c6b63e506
---

# Story 1.3: Магазин заводит доставку и видит её в списке

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a владелец магазина/курьер,
I want быстро завести доставку с адресом и телефоном получателя,
so that она готова к отправке и видна в списке дня.

**Бизнес-суть (одно предложение):** магазин добавляет доставку дня (адрес + телефон получателя), и она появляется в списке «готово к старту».

## Acceptance Criteria

1. **Given** магазин с заданным origin, **when** он открывает «＋ Nova dostava», **then** видит мобайл-first форму: имя получателя, телефон, полный адрес (+ описание опц.) со светлой темой кабинета.
2. **Given** магазин без заданного origin, **when** он открывает форму создания доставки, **then** перенаправляется в «Prodavnica» с подсказкой сперва задать адрес магазина (origin — точка отсчёта ETA).
3. **Given** валидный сербский мобильный телефон, **when** форма сохраняется, **then** телефон нормализуется к E.164 (`+381…`) и сохраняется.
4. **Given** невалидный (непарсящийся) телефон, **when** магазин сохраняет, **then** форма блокирует сохранение с инлайн-ошибкой и примером формата (`npr. 064 123 4567`).
5. **Given** валидный, но немобильный или иностранный (не `+381`) номер, **when** магазин сохраняет, **then** доставка создаётся (без блока), номер помечается флагом риска (`phone_risk`), показывается предупреждение.
6. **Given** заполненная форма, **when** она сохраняется, **then** адрес получателя геокодируется (`MapsProvider`); при успехе сохраняются `dest_lat/lng` + `formatted_address`; при неудаче доставка всё равно создаётся (координаты пустые) с предупреждением «proverite adresu» — поток не блокируется (FR-5/FR-9 философия).
7. **Given** созданная доставка, **then** она появляется в списке кабинета в группе «Spremno» карточкой (имя получателя + адрес + чип «Spremno»); кнопка «＋ Nova dostava» теперь активна и ведёт на форму.
8. **Given** два разных магазина, **when** каждый смотрит список и создаёт доставки, **then** видит и заводит только свои (изоляция по `request.user.shop`); аноним на форме/списке редиректится на вход.
9. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные; тесты не ходят в реальный Google (провайдер — фейк), телефоны парсятся реальной `phonenumbers`.

## Tasks / Subtasks

- [x] **Task 1: Нормализация телефона (`common/phone.py`)** (AC: #3, #4, #5, #9)
  - [x] `phonenumbers` добавлен (`uv add phonenumbers` → 9.0.31).
  - [x] `common/phone.py`: `PhoneResult(e164, is_mobile, is_rs)` + `is_risky` property; `InvalidPhone`; `normalize_phone(raw, region="RS")` (parse+is_valid_number→InvalidPhone; E.164; mobile по number_type; is_rs по country_code 381).
- [x] **Task 2: Модель `Delivery`** (AC: #3, #6, #7, #8)
  - [x] `deliveries/models.py`: `Delivery` (shop FK `related_name="deliveries"`, recipient_name/phone, `phone_risk`, dest_address+lat/lng, description, `source`, `status` TextChoices created/on_the_way/delivered, created_at, `Meta.ordering`). ETA/started отложены до 2.1.
  - [x] Миграция `0002_delivery`.
  - [x] `Delivery` зарегистрирован в `deliveries/admin.py`.
- [x] **Task 3: Сервис `create_delivery`** (AC: #5, #6)
  - [x] `deliveries/services.py`: `create_delivery(shop, *, recipient_name, phone, dest_address, description="") -> (Delivery, geocoded_ok)` — геокод через `get_maps_provider()`, `phone_risk = phone.is_risky`, miss → null-координаты + адрес как есть.
- [x] **Task 4: Форма создания доставки** (AC: #1, #4, #5)
  - [x] `deliveries/forms.py`: `DeliveryForm`; `clean_recipient_phone` → `InvalidPhone` маппится в `ValidationError("Neispravan broj. Npr. 064 123 4567")`, валидный кладёт `phone_result` в cleaned_data, поле = E.164.
- [x] **Task 5: View создания + URL** (AC: #1, #2, #5, #6, #7, #8)
  - [x] `DeliveryCreateView` — `_require_origin` (нет origin → info + redirect в profile); POST → `create_delivery`, success + warning (рисковый телефон / не геокодилось), redirect на список. Скоуп по `request.user.shop`.
  - [x] `deliveries/urls.py`: `create` → `/app/dostava/nova/`.
- [x] **Task 6: Список с группировкой + карточки** (AC: #7, #8)
  - [x] `DeliveryListView` — выборка `shop.deliveries.all()`, группы `u_dostavi`/`spremno`/`zavrseno`; защита при `shop is None`.
  - [x] `delivery_list.html` — рендер групп (U dostavi → Spremno → Završeno), активная «＋ Nova dostava» → `deliveries:create`.
  - [x] Партиал `_delivery_card.html` (имя + адрес + `status_chip`); CSS `.card-name/.card-addr/.card-meta`, `.chip`/`.chip-created`/`.chip-on_the_way`/`.chip-delivered` (текст в чипе — a11y).
- [x] **Task 7: Шаблон формы** (AC: #1)
  - [x] `delivery_form.html` (extends `base.html`): поля по `.field`, кнопка «Sačuvaj» full-width, ошибки формы, «← Dostave».
- [x] **Task 8: Тесты (pytest-django, без реальной сети)** (AC: #3–#9)
  - [x] `common/tests.py`: RS-мобильный → `+381…` не рисковый; RS-стационарный → риск (немобильный); иностранный `+49…` → риск (не RS); мусор → `InvalidPhone`.
  - [x] `create_delivery`: геокод-успех сохраняет координаты+formatted; miss → null + `geocoded_ok=False`; иностранный → `phone_risk=True`.
  - [x] View: аноним → 302; без origin → redirect в profile; валидная форма → доставка в БД и в группе «Spremno»; невалидный телефон → ошибка, доставки нет; изоляция (A не видит доставки B).
  - [x] `manage.py check`, `pytest` (32 passed), `ruff check` — зелёные.

## Dev Notes

### Архитектура и границы (обязательно)

- **Тонкие views + логика в `services.py`.** `create_delivery` — в `deliveries/services.py` (рядом с `set_shop_origin` из 1.2). View только валидирует форму и зовёт сервис. [Source: architecture.md#Structure Patterns, #Enforcement Guidelines]
- **Геокод — только через `integrations`.** Переиспользовать `integrations.providers.get_maps_provider()` (уже есть из 1.2; кэш `GeocodeCache` подключается автоматически). Никаких прямых вызовов Google. [Source: architecture.md#Architectural Boundaries; story 1.2]
- **Телефон в E.164** через `phonenumbers` (libphonenumber), регион RS. Хранение строго E.164. [Source: architecture.md#Data Architecture, #Format Patterns]
- **Изоляция арендаторов:** любой queryset/создание Delivery скоупится по `request.user.shop`. [Source: architecture.md#Authentication & Security; story 1.1/1.2]
- **Мягкая деградация геокода:** сбой не рвёт поток (FR-5/FR-9) — доставка создаётся без координат + предупреждение. [Source: prd.md#4.2 FR-5, #4.3 FR-9; architecture.md#Communication & Process Patterns]
- **FR-6 (API-приём) отложен**, но модель `Delivery` уже совместима: поле `source` (manual|api). [Source: prd.md#4.2 FR-6; epics.md]

### Что уже есть (читать перед правкой)

- **`deliveries/models.py`** — `Shop` (с origin из 1.2). `Delivery` ДОБАВЛЯЕМ сюда. [Source: deliveries/models.py]
- **`deliveries/services.py`** — `set_shop_origin` (паттерн вызова `get_maps_provider`). `create_delivery` дописываем рядом. [Source: deliveries/services.py]
- **`deliveries/forms.py`** — `ShopOriginForm`. `DeliveryForm` добавляем. [Source: deliveries/forms.py]
- **`deliveries/views.py`** — `DeliveryListView` (TemplateView, сейчас `deliveries=[]` — заменить на реальную выборку; беречь `getattr(user,"shop",None)`-защиту), `ShopProfileView`. [Source: deliveries/views.py]
- **`deliveries/urls.py`** — `list`, `profile`. Добавить `create`. [Source: deliveries/urls.py]
- **`delivery_list.html`** — сейчас: topbar (ссылки Prodavnica/Odjava), `{% if deliveries %}` плоский цикл, `.fab` с `aria-disabled` заглушкой «＋ Nova dostava». **Заменить:** группировка + карточки; активировать кнопку (убрать `aria-disabled`, дать `href`). НЕ ломать topbar/empty-state. [Source: deliveries/templates/deliveries/delivery_list.html]
- **`integrations/`** — `MapsProvider`/`get_maps_provider`/`GeocodeCache`/`testing.FakeMapsProvider`/`FailingMapsProvider` готовы (1.2), переиспользовать as-is. [Source: integrations/*]
- **`common/phone.py`** — сейчас заглушка-докстринг; наполняем здесь. [Source: common/phone.py]

### `phonenumbers` — детали

- `parse(raw, "RS")` → при ошибке `NumberParseException` (мапим в `InvalidPhone`). `is_valid_number(num)` — отсев несуществующих. `format_number(num, PhoneNumberFormat.E164)` → `+381…`. `number_type(num)` ∈ {`MOBILE`, `FIXED_LINE_OR_MOBILE`, `FIXED_LINE`, …}. Иностранный номер с явным `+CC` парсится с правильным `country_code` даже при `region="RS"` → не блок, а флаг риска (`is_rs == False`).
- Зрелая стабильная библиотека (порт Google libphonenumber); без сетевых вызовов.

### UX / микрокопирайт (sr-латиница)

- **delivery_card:** surface + бордер `--line`, паддинг card_pad; имя (body bold) + адрес (small muted) + строка статуса с `status_chip`. В 1.3 карточка статична (тап-в-деталь и кнопка старта — Story 2.1). [Source: DESIGN.md#Components; EXPERIENCE.md#Component Patterns]
- **status_chip:** pill, chip-размер bold, светлый тинт фон + насыщенный текст; статус не только цветом (текст в чипе) — a11y. Для 1.3 нужен «Spremno» (готово к старту); задел чипов для on_the_way/delivered. [Source: DESIGN.md#Components; EXPERIENCE.md#Accessibility Floor]
- **Группы списка:** U dostavi → Spremno → Završeno (заголовки `.h`). [Source: EXPERIENCE.md#Information Architecture]
- **Микрокопирайт:** «Nova dostava», поля «Ime», «Telefon», «Adresa», «Opis (opciono)», кнопка «Sačuvaj»; success «Dostava je dodata»; ошибка телефона «Neispravan broj. Npr. 064 123 4567»; warning иностранного «Broj nije srpski mobilni — proverite»; warning геокода «Adresu nismo prepoznali — proverite je kasnije». Тон: служебно, коротко. [Source: EXPERIENCE.md#Voice and Tone]
- Тач-цели ≥48px, поле ≥16px, главная кнопка full-width внизу. [Source: EXPERIENCE.md#Interaction Primitives]

### Project Structure Notes

- Соответствует architecture.md#Complete Project Directory Structure: `deliveries/{models,services,forms,views,urls}.py`, `common/phone.py`, шаблоны `deliveries/templates/deliveries/` (партиал с префиксом `_`). Без отклонений.
- Тесты: `common/tests.py` и `deliveries/tests.py` (единообразно с 1.1/1.2; `pyproject` ловит `tests.py`).

### References

- [Source: docs/planning-artifacts/epics.md#Story 1.3] — история, AC, FR-3/4/5, UX-DR2/4.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.2] — FR-3 (создание), FR-4 (телефон: блок/предупреждение), FR-5 (геокод/fallback).
- [Source: docs/planning-artifacts/architecture.md] — модель `Delivery`, `phonenumbers`, services/integrations, изоляция, E.164.
- [Source: docs/planning-artifacts/ux-designs/ux-Javi-2026-06-02/DESIGN.md, EXPERIENCE.md] — delivery_card, status_chip, группы, микрокопирайт.
- [Source: docs/implementation-artifacts/1-2-shop-origin.md] — паттерн провайдера/сервиса/формы/изоляции для переиспользования.

### Решения для разработчика (зафиксировать)

1. **Геокод-miss при создании:** доставку всё равно создаём (координаты null) + warning — поток не блокируется (FR-5/9). Точку-на-карте/ручной ETA НЕ реализуем здесь (later). Создание без origin — блокируем (redirect в профиль), т.к. origin нужен для будущего ETA.
2. **Поля ETA/started Delivery** — отложены до 2.1 (отдельная миграция там), чтобы не тащить мёртвые поля.
3. **`status` значения** — `created` отображается как группа «Spremno» (готово к старту); смена на `on_the_way` — в Story 2.1.
4. **`phone_risk`** хранится на Delivery (пометка флагом риска по FR-4) — пригодится для предупреждений магазину позже.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Тестовые номера сверены с реальной `phonenumbers`: `064 123 4567`→`+381641234567` (mobile, RS); `011 3033100` (RS fixed, немобильный → риск); `+49 1512 3456789` (валидный, не RS → риск); `abc`/`12` → `InvalidPhone`.
- Геокод в тестах подменяется через `override_settings(MAPS_PROVIDER=...)` фейками из `integrations/testing.py` (без сети).

### Completion Notes List

- Реализован вертикальный срез создания доставки: форма «Nova dostava» (`/app/dostava/nova/`) → нормализация телефона E.164 + геокод адреса → `Delivery` в группе «Spremno» списка. AC#1–#9 ✅.
- Телефон (`common/phone.py`, `phonenumbers`): невалидный — блок с примером; немобильный/иностранный — `phone_risk` + warning, без блока (FR-4).
- Геокод адреса переиспользует слой `integrations` из 1.2 (с кэшем). Сбой геокода не рвёт поток — доставка создаётся без координат + warning (FR-5/9).
- Создание без origin блокируется (redirect в «Prodavnica» с подсказкой) — origin нужен для будущего ETA.
- Список перестроен: группы U dostavi → Spremno → Završeno, карточка (имя + адрес + чип статуса), активная «＋ Nova dostava». Изоляция по `request.user.shop`.
- Модель `Delivery` совместима с будущим API-приёмом (`source`); поля ETA/started отложены до 2.1.
- Проверки: `manage.py check`, `pytest` (32 passed), `ruff check` — зелёные. Status → review.
- **Прод-зависимость:** реальный геокодинг в проде требует ключа Google Maps (открытый прод-секрет из Story 1.2). Локально/в тестах — через `.env`-ключ или фейк.

### File List

**Новые:**
- deliveries/migrations/0002_delivery.py
- deliveries/templates/deliveries/_delivery_card.html
- deliveries/templates/deliveries/delivery_form.html

**Изменены:**
- common/phone.py (normalize_phone + PhoneResult + InvalidPhone), common/tests.py (тесты телефона)
- deliveries/models.py (Delivery), deliveries/admin.py (DeliveryAdmin)
- deliveries/services.py (create_delivery), deliveries/forms.py (DeliveryForm)
- deliveries/views.py (DeliveryCreateView + список с группами), deliveries/urls.py (create)
- deliveries/templates/deliveries/delivery_list.html (группы + активная кнопка)
- deliveries/tests.py (тесты create_delivery + view)
- static/css/app.css (.card-name/.card-addr/.card-meta, .chip*)
- pyproject.toml, uv.lock (phonenumbers)

### Change Log

- 2026-06-04: Story 1.3 реализована — создание доставки (телефон E.164 через phonenumbers + геокод адреса), список с группами и карточками. 32 теста зелёные. Status → review.
