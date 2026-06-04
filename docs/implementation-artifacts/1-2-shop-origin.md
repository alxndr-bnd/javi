---
baseline_commit: a37dfe0a17362f1b18822fe7d4523035354d349c
---

# Story 1.2: Магазин задаёт адрес своего магазина (origin)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a владелец магазина,
I want указать адрес моего магазина в профиле,
so that система знает, откуда стартует доставка для расчёта ETA.

**Бизнес-суть (одно предложение):** магазин один раз сохраняет свой адрес — точку отсчёта для будущих расчётов времени.

## Acceptance Criteria

1. **Given** авторизованный магазин в кабинете, **when** он открывает экран «Prodavnica» (профиль магазина), **then** видит мобайл-first форму со светлой темой кабинета с полем «Adresa prodavnice» и кнопкой «Sačuvaj»; если origin уже задан — поле предзаполнено текущим адресом.
2. **Given** магазин ввёл корректный адрес, **when** он сохраняет форму, **then** адрес геокодируется через `MapsProvider` (Google Geocoding, регион RS), и `Shop.origin_address` + `origin_lat` + `origin_lng` сохраняются (адрес — нормализованный `formatted_address` от провайдера), показывается подтверждение «Adresa je sačuvana».
3. **Given** адрес не распознан (ZERO_RESULTS) или провайдер недоступен (сбой/таймаут), **when** магазин сохраняет форму, **then** координаты НЕ перезаписываются, форма остаётся с введённым значением и показывается подсказка «Nismo prepoznali adresu. Proverite i pokušajte ponovo.»; поток не падает с 500.
4. **Given** origin ранее задан, **when** магазин снова открывает «Prodavnica», **then** он видит текущий адрес и может его отредактировать и пересохранить (повторный геокод).
5. **Given** два разных магазина, **when** каждый редактирует свой профиль, **then** каждый меняет только свой `Shop` (изоляция по `request.user.shop`); неавторизованный на экране профиля редиректится на вход.
6. **Given** повторный одинаковый адрес, **when** он геокодируется, **then** результат берётся из кэша геокодинга (AR-6), без повторного обращения к провайдеру (срезает стоимость Maps).
7. **Given** локальный прогон, **then** `manage.py check`, `pytest` и `ruff check` зелёные; тесты НЕ ходят в реальный Google (провайдер замокан/подменён фейком).

## Tasks / Subtasks

- [x] **Task 1: Слой провайдера карт (`integrations`) — интерфейс + Google Geocoding** (AC: #2, #3, #7)
  - [x] `integrations/base.py`: `@dataclass GeocodeResult(lat, lng, formatted_address)`; абстрактный `MapsProvider.geocode(address) -> GeocodeResult | None`.
  - [x] `integrations/google_maps.py`: `GoogleMapsProvider` — Geocoding API (`region=rs`, `language=sr-Latn`), ключ из settings, таймаут 5 c; сетевые/HTTP-ошибки и не-`OK` статусы → `None` + ERROR-лог (без утечки ключа).
  - [x] `integrations/providers.py`: фабрика `get_maps_provider()` (по `settings.MAPS_PROVIDER`, обёрнута кэшем); подмена фейком в тестах через override.
  - [x] HTTP-клиент: `requests` добавлен в зависимости (`uv add requests` → 2.34.2).
- [x] **Task 2: Кэш геокодинга (AR-6)** (AC: #6, #7)
  - [x] Модель `GeocodeCache` (`integrations/models.py`, `normalized_address` unique + lat/lng/formatted/created_at) + миграция `0001_initial`.
  - [x] `integrations/cache.py`: `CachingMapsProvider` (cache-aside) + `normalize_address` (trim+collapse+lower); промахи не кэшируются.
- [x] **Task 3: Сервис origin в `deliveries`** (AC: #2, #3, #5)
  - [x] `deliveries/services.py`: `set_shop_origin(shop, raw_address) -> bool` — успех сохраняет formatted+координаты; `None` не трогает существующий origin, `return False`.
- [x] **Task 4: Форма + view + URL профиля** (AC: #1, #4, #5)
  - [x] `deliveries/forms.py`: `ShopOriginForm` (`address`, лейбл «Adresa prodavnice», maxlength 300).
  - [x] `deliveries/views.py`: `ShopProfileView(LoginRequiredMixin, View)` — GET предзаполняет из `request.user.shop.origin_address`; POST → `set_shop_origin`; успех PRG-redirect + `messages.success`, miss → `messages.error`. Скоуп по `request.user.shop`.
  - [x] `deliveries/urls.py`: `path("prodavnica/", ShopProfileView.as_view(), name="profile")` → `/app/prodavnica/`.
- [x] **Task 5: Шаблон профиля + навигация из кабинета** (AC: #1, #4)
  - [x] `deliveries/templates/deliveries/shop_profile.html` (extends `base.html`): форма по токенам `app.css`, текущий origin виден.
  - [x] Рендер Django `messages` на странице профиля + стили `.msg/.msg-success/.msg-error` в `app.css` (base не трогали — child переопределяет body).
  - [x] Ссылка «Prodavnica» в topbar кабинета (`delivery_list.html`).
- [~] **Task 6: Конфиг и секрет ключа Maps** (AC: #2)
  - [x] `config/settings.py`: `GOOGLE_MAPS_API_KEY` + `MAPS_PROVIDER` (env-driven).
  - [x] `.env.example`: добавлен `GOOGLE_MAPS_API_KEY=`.
  - [ ] **Прод (требует go заказчика + доступ к GCP):** секрет `javi-google-maps-key` в Secret Manager, роль `secretAccessor` runtime-SA, проброс в `deploy.yaml`, billing + ограничение ключа (Geocoding API). Деплой-подзадача — НЕ блокирует локальную разработку/тесты. **Открыта.**
- [x] **Task 7: Тесты (pytest-django, без реальной сети)** (AC: #2–#7)
  - [x] `integrations/testing.py`: `FakeMapsProvider` (успех, счётчик вызовов) + `FailingMapsProvider` (miss); инъекция через `override_settings(MAPS_PROVIDER=...)`.
  - [x] `set_shop_origin`: успех сохраняет formatted+coords; miss → False и не затирает прежние координаты.
  - [x] View: аноним → 302; предзаполнение; POST успех → coords + PRG; POST miss → подсказка, coords не тронуты; изоляция (A не меняет B).
  - [x] Кэш: второй одинаковый адрес не вызывает провайдер (`FakeMapsProvider.calls == 1`).
  - [x] `GoogleMapsProvider`: `OK` → `GeocodeResult`; `ZERO_RESULTS`/исключение сети/без ключа → `None` (мок `requests`).
  - [x] `manage.py check`, `pytest` (18 passed), `ruff check` — зелёные.

## Dev Notes

### Архитектура и границы (обязательно к соблюдению)

- **Провайдеры — только через `integrations`.** Никаких прямых вызовов Google из views/services/templates — домен (`deliveries.services`) зовёт `MapsProvider` через фабрику. Это прямое требование архитектуры (изоляция вендоров, свап без правок домена). [Source: architecture.md#API & Communication Patterns, #Architectural Boundaries, #Enforcement Guidelines]
- **Тонкие views + логика в `services.py`.** `set_shop_origin` живёт в `deliveries/services.py`; view только валидирует форму и зовёт сервис. [Source: architecture.md#Structure Patterns]
- **Секреты из env/Secret Manager**, ключ Maps НЕ в коде. [Source: architecture.md#Authentication & Security, #Enforcement Guidelines]
- **Кэш геокодинга по нормализованному адресу** — AR-6, снижает стоимость Maps; персистентный (Cloud SQL) переживает scale-to-zero Cloud Run (поэтому модель в БД, а не LocMemCache процесса). [Source: architecture.md#Data Architecture («Кэш»), epics.md#Story 1.2 (AR-6)]
- **Обработка сбоев провайдера:** обернуть вызов, не утекать внутренности пользователю (Django messages), в лог — ERROR; геокод-miss деградирует мягко (поток не рвётся) — рифмуется с FR-9 fallback-философией. [Source: architecture.md#Communication & Process Patterns]
- **Изоляция арендаторов:** любой доступ к Shop — через `request.user.shop`. [Source: architecture.md#Authentication & Security; story 1.1 NFR-6]

### Модель `Shop` — текущее состояние (читать перед правкой)

`deliveries/models.py` уже содержит поля под origin (заведены в 1.1, заполняются здесь):
```
origin_address = CharField("адрес магазина", max_length=300, blank=True)
origin_lat = FloatField(null=True, blank=True)
origin_lng = FloatField(null=True, blank=True)
```
**Новых миграций по `Shop` НЕ требуется** — поля уже есть. Миграция нужна только под новую модель `GeocodeCache` в `integrations`. `Shop` связан 1:1 с `accounts.User` через `related_name="shop"` (`request.user.shop`). [Source: deliveries/models.py]

### Google Geocoding API — актуальные детали

- **Endpoint:** `GET https://maps.googleapis.com/maps/api/geocode/json`
- **Параметры:** `address` (URL-энкод), `key`, `region=rs` (биас на Сербию), `language=sr-Latn`.
- **Успех:** `status == "OK"`, `results[0].geometry.location.lat/lng` (float), `results[0].formatted_address` (нормализованный адрес — его и сохраняем в `origin_address`).
- **Не-успех:** `status` ∈ `ZERO_RESULTS` (не распознан → None), `REQUEST_DENIED`/`OVER_QUERY_LIMIT`/`INVALID_REQUEST`/`UNKNOWN_ERROR` (ошибка конфигурации/квоты → None + ERROR-лог). Сетевой таймаут/исключение → None.
- API стабилен (legacy Geocoding API — рекомендованный путь для address→coords; не путать с Routes API, который понадобится в Epic 2 для ETA). Требует включённого billing и ключа с ограничением на Geocoding API.

### Размещение файлов (целевое дерево)

- `integrations/base.py`, `integrations/google_maps.py`, `integrations/cache.py`, `integrations/providers.py` (фабрика), `integrations/migrations/0001_initial.py` (GeocodeCache). [Source: architecture.md#Complete Project Directory Structure]
- `deliveries/services.py` (новый), `deliveries/forms.py` (новый), `deliveries/views.py` (+ ShopProfileView), `deliveries/urls.py` (+ profile), `deliveries/templates/deliveries/shop_profile.html` (новый).
- Тесты: рядом с кодом (`integrations/tests.py`, `deliveries/tests.py`) — текущий проект использует `tests.py` (см. `pyproject` `python_files = ["test_*.py", "tests.py"]`). Можно завести `tests/` пакет, но единообразнее с 1.1 — `tests.py`.

### UX / микрокопирайт (sr-латиница)

- Экран «Profil / Prodavnica» — **spine-only** простая форма по паттернам кабинета (DESIGN-токены уже в `app.css`: `.wrap`, `.field`, `.btn-primary`). [Source: EXPERIENCE.md#Information Architecture, #Mock Coverage]
- Строки: заголовок «Prodavnica», лейбл «Adresa prodavnice», кнопка «Sačuvaj», успех «Adresa je sačuvana», ошибка геокода «Nismo prepoznali adresu. Proverite i pokušajte ponovo.» (тон: служебно, коротко, по-доброму). [Source: EXPERIENCE.md#Voice and Tone, #State Patterns («Ошибка геокода»)]
- Тач-цели ≥48px, поле ≥16px шрифт (уже в `.field input`), кнопка на всю ширину. [Source: EXPERIENCE.md#Interaction Primitives, #Accessibility Floor]

### Project Structure Notes

- Соответствует architecture.md#Complete Project Directory Structure: `integrations/{base,google_maps,cache}.py`, `deliveries/{services,forms}.py`. Вариация: фабрика провайдера (`get_maps_provider`) в дереве явно не названа — добавляем как тонкую точку выбора реализации (согласуется с «интерфейсы провайдеров изолируют вендоров»).
- `base.html` сейчас не рендерит Django `messages` — добавляем минимальный блок вывода (нужен для success/error профиля). Не ломать существующие шаблоны (login, delivery_list).

### References

- [Source: docs/planning-artifacts/epics.md#Story 1.2] — история, AC, FR-2, AR-3/6.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.1] — FR-2 (origin в профиле).
- [Source: docs/planning-artifacts/architecture.md] — слой `integrations`, `MapsProvider`, кэш геокодинга, секреты, тонкие views/services, изоляция.
- [Source: docs/planning-artifacts/ux-designs/ux-Javi-2026-06-02/EXPERIENCE.md, DESIGN.md] — экран профиля, микрокопирайт, токены.
- [Source: docs/implementation-artifacts/1-1-walking-skeleton.md] — паттерны проекта, изоляция, деплой (Secret Manager/deploy.yaml аналогично для ключа Maps).

### Решения для разработчика (зафиксировать при реализации)

1. **HTTP-клиент:** рекомендуется `requests` (переиспользуется для Infobip в Epic 2); допустим stdlib `urllib`. Единый клиент предпочтительнее.
2. **Сохранение при сбое геокода:** origin без координат бесполезен для ETA → при miss НЕ сохраняем (ни адрес, ни координаты), просим исправить. Существующий валидный origin при неудачном пересохранении остаётся нетронутым.
3. **Кэш:** персистентная модель `GeocodeCache` в Cloud SQL (не процессный LocMemCache) — переживает scale-to-zero. Промахи не кэшируем.
4. **Прод-секрет ключа Maps** — отдельная деплой-подзадача (как Task 7 в 1.1), требует go заказчика; локально работает с ключом из `.env` или с фейк-провайдером.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Тесты не ходят в реальный Google: провайдер подменяется через `override_settings(MAPS_PROVIDER=...)` на фейки из `integrations/testing.py`; парсинг `GoogleMapsProvider` проверяется моком `integrations.google_maps.requests.get`.
- `FakeMapsProvider.calls` — счётчик уровня класса; cache-тест сбрасывает его перед прогоном (между тестами БД откатывается, так что `GeocodeCache` чист).

### Completion Notes List

- Реализован вертикальный срез origin: экран «Prodavnica» (`/app/prodavnica/`) → форма → `set_shop_origin` → геокод через `MapsProvider` → сохранение `origin_address/lat/lng`. AC#1–#6 ✅.
- Слой провайдера карт создан с нуля за интерфейсом (`integrations/base.py` `MapsProvider`/`GeocodeResult`, `google_maps.py` `GoogleMapsProvider`, `providers.py` фабрика). Домен зовёт только абстракцию — прямых вызовов Google из views/services нет (требование архитектуры).
- Кэш геокодинга (AR-6): персистентная модель `GeocodeCache` + `CachingMapsProvider` (cache-aside, промахи не кэшируются). Переживает scale-to-zero Cloud Run.
- Мягкая деградация при сбое/нераспознанном адресе: координаты не затираются, пользователю — подсказка «Nismo prepoznali adresu…», поток не падает (рифмуется с FR-9).
- Изоляция: профиль правит только `request.user.shop` (тест-кейс A не меняет B).
- Проверки зелёные: `manage.py check`, `pytest` (18 passed), `ruff check`.
- **AC по проду частично:** локально/в тестах origin работает (с реальным ключом в `.env` или фейком). **Task 6 прод-секрет ключа Maps НЕ закрыт** — ждёт go заказчика (Secret Manager `javi-google-maps-key` + роль SA + `deploy.yaml` + billing/ограничение ключа), как прод-деплой в Story 1.1. Статус истории — `review`.
- Зависимость: добавлен `requests` (2.34.2) — переиспользуется для Infobip в Epic 2.

### File List

**Новые:**
- integrations/base.py, integrations/google_maps.py, integrations/cache.py, integrations/providers.py, integrations/testing.py
- integrations/models.py (GeocodeCache), integrations/migrations/0001_initial.py
- deliveries/services.py, deliveries/forms.py
- deliveries/templates/deliveries/shop_profile.html

**Изменены:**
- config/settings.py (GOOGLE_MAPS_API_KEY, MAPS_PROVIDER)
- deliveries/views.py (ShopProfileView), deliveries/urls.py (profile)
- deliveries/templates/deliveries/delivery_list.html (ссылка «Prodavnica»)
- static/css/app.css (.msg/.msg-success/.msg-error; errorlist margin)
- deliveries/tests.py (тесты origin), integrations/tests.py (провайдер + кэш)
- .env.example (GOOGLE_MAPS_API_KEY)
- pyproject.toml, uv.lock (requests)

### Change Log

- 2026-06-04: Story 1.2 реализована — origin магазина с геокодингом (Google за интерфейсом + кэш AR-6), экран «Prodavnica». 18 тестов зелёные. Прод-секрет ключа Maps открыт (ждёт go). Status → review.
