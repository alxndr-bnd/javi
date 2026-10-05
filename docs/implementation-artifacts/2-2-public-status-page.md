---
baseline_commit: 2e32268
---

# Story 2.2: Публичная страница статуса по ссылке

Status: done

Jira: SERBITO-362 (лимиты трекинга ужесточены, Closed), SERBITO-352 (доступность страницы статуса, Closed) — follow-up

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a получатель,
I want открыть ссылку из сообщения и увидеть статус и время,
so that я понимаю, когда будет курьер, и спокоен.

**Бизнес-суть (одно предложение):** покупатель открывает ссылку и видит магазин, статус «в пути» и время прибытия — без приложения и логина.

## Acceptance Criteria

1. **Given** отправленное уведомление с трекинг-ссылкой, **when** получатель открывает `/t/<token>`, **then** он видит **брендовую** страницу (градиент-шапка): магазин, степпер (Primljeno · U dostavi · Isporučeno) с подсветкой текущего шага, крупный ETA «do HH:MM», город/район назначения.
2. **Given** разные статусы доставки, **when** страница открыта, **then** степпер подсвечивает соответствующий шаг: `created`→Primljeno, `on_the_way`→U dostavi (+ крупный ETA), `delivered`→Isporučeno.
3. **Given** приватность (NFR-3/FR-18), **then** на странице НЕ показываются телефон и полный адрес получателя (только город/район); токен остаётся непредсказуемым.
4. **Given** срок жизни ссылки (FR-20), **when** токен истёк, **then** страница отдаёт 410 без раскрытия данных; срок проставляется при создании токена (TTL из настроек, дефолт 7 дней).
5. **Given** rate limit (FR-20/NFR-6), **when** к странице идёт слишком много запросов с одного IP, **then** сверх лимита возвращается 429 (без раскрытия данных).
6. **Given** прогрессивное улучшение (UX-DR9), **then** страница читается полностью **без JS** (степпер/ETA — серверный рендер, статус не только цветом — есть текст).
7. **Given** локальный прогон, **then** `manage.py check`, `pytest`, `ruff check` зелёные; тесты без реальной сети.

## Tasks / Subtasks

- [x] **Task 1: Город назначения (`dest_city`)** (AC: #1, #3)
  - [x] `integrations/base.py`: `GeocodeResult.city: str = ""`.
  - [x] `integrations/google_maps.py`: `_extract_city` из `address_components` (locality → postal_town → administrative_area_level_2).
  - [x] `integrations/testing.py`: `FakeMapsProvider` city="Beograd".
  - [x] `deliveries/models.py`: `Delivery.dest_city` + миграция `0004`.
  - [x] `create_delivery`: сохраняет `dest_city`. **Также: `GeocodeCache` + кэш-обёртка дополнены полем city** (баг найден тестом — из кэша терялся город; миграция `integrations/0002`).
- [x] **Task 2: Брендовая страница + степпер** (AC: #1, #2, #6)
  - [x] `tracking/views.py`: контекст `steps` (done/active/future), `dest_city`, `eta`, `status`.
  - [x] `status.html`: градиент-шапка, `status_stepper` (3 шага, текст + точка), крупный ETA, город. Без JS.
  - [x] `app.css`: `.stepper/.step/.step--active/.step--done`, `.track-city`, `.track-card--plain`.
- [x] **Task 3: Срок жизни ссылки** (AC: #4)
  - [x] `start_delivery`: `TrackingToken.expires_at = now + TRACKING_TOKEN_TTL_DAYS`; settings `TRACKING_TOKEN_TTL_DAYS` (7). 410 на истёкший — работает.
- [x] **Task 4: Rate limit** (AC: #5)
  - [x] `tracking/views.py`: cache-лимитер по IP (`track_rl:<ip>`, окно 60 c), `TRACKING_RATE_LIMIT` (60) → 429.
- [x] **Task 5: Тесты** (AC: #1–#7)
  - [x] Степпер created/on_the_way(+ETA)/delivered; приватность (нет телефона/полного адреса, есть город); 410 истёкший; 429 rate limit (override лимита, autouse-очистка cache); `dest_city` в create_delivery.
  - [x] `manage.py check`, `pytest` (46 passed), `ruff check` — зелёные.

## Dev Notes

### Что уже есть (2.1) — апгрейдим, не ломаем

- `tracking/views.py` `status(request, token)` — находит `TrackingToken`, 404/410, рендерит `status.html` с `shop_name/status/eta`. **Расширяем** контекст (город, степпер) + rate limit. [Source: tracking/views.py; 2.1]
- `tracking/templates/tracking/status.html` — минимальная брендовая карточка (есть `.track*` CSS). **Переписываем** в полноценную брендовую со степпером. [Source: 2.1]
- `TrackingToken` (deliveries) — `token`/`expires_at`/`created_at`. 410 на истёкший уже есть. **Добавляем** проставление `expires_at` при создании. [Source: deliveries/models.py; 2.1]
- `Delivery` — `dest_address`, `status` (created/on_the_way/delivered), `eta_at`. **Добавляем** `dest_city`. [Source: deliveries/models.py]
- `GeocodeResult`/`GoogleMapsProvider`/`FakeMapsProvider` — **расширяем** city. `set_shop_origin` city игнорирует (origin город не нужен). [Source: integrations/*]
- `common.timewindow.format_eta` — переиспользуем. [Source: 2.1]

### Архитектура и границы

- Публичная страница без логина, минимум данных (NFR-3, FR-18): только магазин/статус/ETA/город. Токен непредсказуем (`secrets.token_urlsafe`, есть). [Source: architecture.md#Authentication & Security]
- Rate limit + срок ссылки — FR-20/NFR-6. Лимитер — на Django cache (LocMemCache по умолчанию; для прод-многоинстансовости позже можно вынести в общий кэш, но Cloud Run `max-instances=1` — приемлемо сейчас). [Source: architecture.md#Authentication & Security; prd FR-20]
- Без логики провайдеров во вьюхе; city берётся из уже сохранённого `dest_city` (геокод сделан в 1.3). [Source: architecture.md#Structure Patterns]
- Читаемость без JS (UX-DR9): степпер — чистый CSS/HTML, статус с текстом (не только цвет). [Source: EXPERIENCE.md#Accessibility Floor]

### UX / микрокопирайт (sr-латиница)

- **brand_header:** градиент `--brand`→`--accent`, `--on-brand` текст: магазин + «Vaša porudžbina je u dostavi». [Source: DESIGN.md#Components brand_header; EXPERIENCE.md]
- **status_stepper:** Primljeno · U dostavi · Isporučeno; активный `--brand`, будущие `--line`; текст под каждым шагом. [Source: DESIGN.md#Components status_stepper; UX-DR6]
- **ETA:** крупный (`size_display` 30px) «Stiže okvirno do HH:MM». [Source: EXPERIENCE.md#Information Architecture]
- Город: «{grad}» под ETA или в шапке. Без телефона/адреса.

### Project Structure Notes

- В границах architecture.md: публичная вью/шаблоны в `tracking`, владение токеном — `deliveries`. Без отклонений. Блок оценки 1–5 на этой же странице — Story 3.1 (не здесь).

### References

- [Source: docs/planning-artifacts/epics.md#Story 2.2] — AC, FR-17/18/20.
- [Source: docs/planning-artifacts/prds/prd-javi-2026-06-01/prd.md#4.5] — FR-17/18/20.
- [Source: docs/planning-artifacts/architecture.md] — приватность, токен, rate limit, границы.
- [Source: docs/planning-artifacts/ux-designs/ux-Javi-2026-06-02/DESIGN.md, EXPERIENCE.md] — brand_header, status_stepper, крупный ETA, a11y.
- [Source: docs/implementation-artifacts/2-1-start-eta-notify.md] — минимальная страница, TrackingToken, format_eta.

### Решения для разработчика

1. **Город** хранится на `Delivery` (`dest_city`) из геокода — стабильнее, чем парсить адрес во вьюхе. Старые доставки без города — fallback на пусто (город просто не показываем).
2. **Срок ссылки** — TTL от создания (дефолт 7 дней); более тонкая логика «истечь через N после доставки» — не нужна для MVP.
3. **Rate limit** — простой cache-лимитер по IP; достаточно при `max-instances=1`. Вынос в Redis/общий кэш — если масштабируемся.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (1M context)

### Debug Log References

- Баг кэша геокодинга: `GeocodeCache`/`CachingMapsProvider` не хранили `city` → из кэша результат возвращался без города (упал `test_cache_prevents_second_provider_call`). Исправлено: добавлено поле `city` в модель кэша + чтение/запись (миграция `integrations/0002`).
- Rate-limit тест: autouse-фикстура `cache.clear()` + уникальный `REMOTE_ADDR` — изоляция от накопления счётчика между тестами.

### Completion Notes List

- Публичная страница `/t/<token>` доведена до брендовой: градиент-шапка магазина, `status_stepper` (Primljeno · U dostavi · Isporučeno, текущий подсвечен, статус с текстом — a11y), крупный ETA «do HH:MM», город назначения. Читается без JS. AC#1–#7 ✅.
- Приватность (NFR-3/FR-18): только магазин/статус/ETA/город — без телефона и полного адреса.
- Срок жизни ссылки (FR-20): `TrackingToken.expires_at = создание + 7 дней` (настраивается), 410 на истёкший.
- Rate limit (FR-20/NFR-6): cache-лимитер по IP (60/мин), 429 сверх лимита.
- Город назначения: `dest_city` извлекается из `address_components` геокода и сохраняется при создании доставки; кэш геокодинга тоже хранит город.
- Проверки: `manage.py check`, `pytest` (46 passed), `ruff check` — зелёные. Без сети.
- НЕ задеплоено (Epic 2 деплой — отдельным куском/по go). Status → review.

### File List

**Изменены:**
- integrations/base.py (GeocodeResult.city), integrations/google_maps.py (_extract_city), integrations/cache.py (city), integrations/models.py (GeocodeCache.city), integrations/migrations/0002_geocodecache_city.py (новый), integrations/testing.py (fake city)
- deliveries/models.py (Delivery.dest_city), deliveries/migrations/0004_delivery_dest_city.py (новый), deliveries/services.py (dest_city + token expires_at), deliveries/tests.py (assert city)
- config/settings.py (TRACKING_TOKEN_TTL_DAYS, TRACKING_RATE_LIMIT)
- tracking/views.py (степпер + rate limit + город), tracking/templates/tracking/status.html (брендовая + степпер), tracking/tests.py (2.2 тесты)
- static/css/app.css (.stepper/.step*, .track-city, .track-card--plain)

### Change Log

- 2026-06-04: Story 2.2 реализована локально — брендовая публичная страница статуса (степпер, крупный ETA, город), срок ссылки + rate limit, приватность. Найден/исправлен баг кэша (терялся город). 46 тестов зелёные. Status → review.
- 2026-10-05: Сверка документов: история выпущена в v0.6.0 (1f91ac2). Status → done.
