# Javi Public API — План (интеграция для магазинов/компаний)

_Создано: 2026-06-07. Статус: план (до реализации)._

## Цель

Сделать Javi простой системой информирования покупателей о текущей доставке, в которую магазины/компании **интегрируются за минуты**: сами регистрируются, генерируют API-ключ и через API ведут весь флоу доставки (создать → отправить → статус → оценка). **UI и API консистентны** — обе поверхности вызывают одни и те же доменные сервисы.

### Север-звезда (зафиксировано заказчиком, 2026-06-07)
**Любое действие, доступное в UI, должно быть доступно и через API**, с **индустриально-стандартными действиями и статусами**.

**Паритет действий UI ↔ API:**
| UI-действие | API |
|---|---|
| Создать заказ | `POST /api/v1/deliveries` |
| Označi spremno (new→ready) | `POST /api/v1/deliveries/{id}/ready` |
| Dostava je počela (dispatch) | `POST /api/v1/deliveries/{id}/start` (alias `/dispatch`) |
| Označi isporučeno | `POST /api/v1/deliveries/{id}/delivered` |
| Pošalji ponovo | `POST /api/v1/deliveries/{id}/notifications/resend` |
| Obriši / Vrati | `DELETE /api/v1/deliveries/{id}` / `POST .../restore` |
| Статус/детали | `GET /api/v1/deliveries/{id}`, `GET /api/v1/deliveries` |
| Редактировать магазин / вебхуки | `GET`/`PATCH /api/v1/shop` |

**Индустриально-стандартные статусы (маппинг на внутренние):** ориентир — AfterShip 7-статусная модель.
| Внутренний | API (industry-standard) |
|---|---|
| new | `pending` (info received) |
| created (Spremno) | `ready_for_pickup` |
| on_the_way | `out_for_delivery` |
| delivered | `delivered` |
| (notification failed) | sub-state `notification.failed` |

API отдаёт стандартный `status` + (опц.) внутренний код. Receipt-статусы уведомления (`delivered`/`read`/`failed`) — отдельное поле `notification`.

## Что мы и что НЕ мы

- **Мы:** слой уведомления о доставке своим курьером + публичная страница статуса + ETA + оценка. Магазин сам везёт; Javi считает ETA и информирует покупателя.
- **НЕ мы:** не диспетчеризация курьеров, не маркетплейс, не мультикарьерный трекинг. (В отличие от DoorDash Drive/Uber Direct, которые ещё и поставляют курьера.)

## Ресёрч: индустриальные паттерны (на чём основан дизайн)

| Система | Auth | Флоу | Статусы наружу |
|---|---|---|---|
| DoorDash Drive | JWT | POST create delivery → tracking URL; webhooks (driver_assigned/picked_up/delivered) | webhooks |
| Uber Direct | OAuth2 | quote → create → track; webhooks (delivery_status) | webhooks |
| AfterShip | **API key в заголовке** | create tracking → стандартизованные статусы (7) → webhook c **HMAC-SHA256** подписью | webhooks (подписанные) |
| Shippo/EasyPost | API key | create → tracking events, единый schema, ретраи вебхуков | webhooks |

**Выводы для Javi (минимальная сложность интеграции):**
1. **Auth = API-ключ в заголовке** (`Authorization: Bearer <key>` или `X-Api-Key`). Не OAuth — проще для self-service.
2. **REST/JSON**, версия в пути (`/api/v1/`).
3. **Idempotency-Key** на создание (как Stripe) — повторный POST не плодит доставки.
4. На создании возвращаем **tracking_url** (как DoorDash) — у нас это `/t/<token>`.
5. **Исходящие вебхуки** мерчанту на смену статуса с **HMAC-подписью** (как AfterShip) + ретраи.
6. **Стандартизованные статусы** доставки и уведомления в ответах.
7. Нет единого открытого стандарта last-mile нотификаций — берём общий REST+webhook паттерн, проверенный этими игроками.

Источники: DoorDash Drive API, Uber Direct API, AfterShip Tracking API, Shippo/EasyPost docs.

## Дизайн API (предложение)

### Аутентификация
- Модель `ApiKey(shop, prefix, key_hash, created_at, last_used_at, revoked_at)`. Ключ показывается **один раз** при генерации; хранится только хэш (sha256). Формат: `javi_live_<random>`; `prefix` (первые ~8 симв.) для идентификации в UI/логах.
- Заголовок `Authorization: Bearer javi_live_…`. DRF `BaseAuthentication` → находит shop по ключу, скоупит всё по нему (та же изоляция, что в UI).

### Ресурсы и эндпоинты (v1)
```
POST   /api/v1/deliveries                 # создать доставку (geocode внутри)
GET    /api/v1/deliveries                 # список (фильтры: status, date)
GET    /api/v1/deliveries/{id}            # получить доставку + статус уведомления + tracking_url
POST   /api/v1/deliveries/{id}/start      # «доставка началась»: ETA + уведомление; body: {eta?: ISO}
POST   /api/v1/deliveries/{id}/delivered  # отметить доставленной (опц.)
DELETE /api/v1/deliveries/{id}            # soft delete
```
- `POST /deliveries` body: `{recipient_name, recipient_phone, address, description?, external_id?}`; заголовок `Idempotency-Key`. Ответ `201`: `{id, status, tracking_url, recipient:{...}, dest_city, created_at}`.
- `POST /start` ответ: `{id, status:"on_the_way", eta:"…", tracking_url, notification:{channel,status}}`. При недоступном маршруте — `422` с просьбой передать `eta`, или принять `eta` в body (консистентно с ручным ETA в UI).
- Все ответы — единый JSON-конверт ошибок: `{error:{code,message,details?}}`, корректные HTTP-коды (400/401/404/409/422/429).

### Исходящие вебхуки (Javi → мерчант)
- Настройка `webhook_url` + `webhook_secret` на магазине (в профиле/через API).
- События: `delivery.started`, `notification.delivered`, `notification.read`, `notification.failed`, `delivery.delivered`, `rating.created`.
- Подпись: заголовок `Javi-Signature: sha256=<hmac(secret, body)>` (паттерн AfterShip). Ретраи с бэкоффом (Cloud Tasks — уже есть инфраструктура).
- Доставка вебхуков через существующий `tasks`-механизм (Cloud Tasks), идемпотентно.

### Консистентность UI ↔ API
- Оба слоя зовут **одни и те же сервисы**: `create_delivery`, `start_delivery`, `resend_on_the_way`, soft-delete. API = тонкий DRF-слой над services (как views — тонкие). Никакой дубль-логики.
- `Delivery.source` уже различает `manual|api`.

### Технологии (готовые библиотеки — НЕ писать с нуля; решение заказчика 2026-06-07)
- **Django REST Framework** — сериализаторы, аутентификация по ключу, throttling (rate limit на ключ), единый формат ошибок.
- **drf-spectacular** — авто-генерация **OpenAPI 3** схемы из кода.
- **Документация ОБЯЗАТЕЛЬНА и публикуется:** Swagger UI / Redoc на `/api/docs/` + схема `/api/schema/` (drf-spectacular-sidecar). Каждый эндпоинт описан (поля/коды/примеры). `/app/api` ссылается на доки + quick-start (curl).
- Первый срез (commit `см. ниже`) сделан на «голом» Django JSON для скорости; **волна 2 мигрирует на DRF + drf-spectacular** (тот же контракт, логика через services).

## Самостоятельный онбординг (self-service)
Сейчас регистрация — только management-команда `create_shop`. Нужно:
1. **Регистрация** (sign-up): email+пароль → создаётся User+Shop. Экран регистрации + (позже) подтверждение email.
2. **Профиль → API-ключи:** генерация/просмотр(prefix)/отзыв ключей; настройка `webhook_url`/`webhook_secret`.
3. Страница **/app/api** (сейчас заглушка) → реальная документация + «быстрый старт» (curl-примеры).

## Стандартный флоу (последовательность)
```
1. Магазин: POST /api/v1/deliveries {recipient, address}  → 201 {id, tracking_url}
2. Магазин: POST /api/v1/deliveries/{id}/start            → 200 {status:on_the_way, eta}
   Javi: geocode (на шаге 1) → Routes ETA → Infobip уведомление покупателю + tracking_url
3. Javi → мерчант webhook: notification.delivered / .read   (HMAC-подписано)
4. Покупатель: открывает tracking_url → статус/ETA → (после) оценка 1–5
5. Javi → мерчант webhook: delivery.delivered, rating.created
```

## План реализации (фазы → эпики/истории)

**Epic API-1: Self-service онбординг + API-ключи**
- Story: Регистрация магазина (sign-up email+пароль → User+Shop).
- Story: Модель `ApiKey` + генерация/отзыв в профиле (ключ показывается раз, хранится хэш).

**Epic API-2: REST API v1 (deliveries)**
- Story: DRF + auth по API-ключу + throttling; `POST/GET /deliveries`, `GET /deliveries/{id}` (поверх `create_delivery`).
- Story: `POST /deliveries/{id}/start` (поверх `start_delivery`, ETA/ручной ETA), `delivered`, `DELETE` (soft).
- Story: Idempotency-Key на создание; единый формат ошибок.

**Epic API-3: Исходящие вебхуки**
- Story: `webhook_url`/`secret` на магазине; диспетч событий через Cloud Tasks с HMAC-подписью и ретраями.

**Epic API-4: Документация**
- Story: OpenAPI (drf-spectacular) + страница `/app/api` с quick start (curl) — заменить заглушку.

## Открытые вопросы (решить до старта)
1. **Регистрация:** открытая (любой email) или по приглашению? (alpha → возможно по приглашению/модерации.)
2. **Тарификация/лимиты:** rate limit на ключ; квоты сообщений (стоимость Infobip).
3. **PII/GDPR (Сербия):** хранение телефонов/адресов через API — согласие со стороны мерчанта (договор), как и сейчас.
4. **`external_id`** мерчанта на доставке для сопоставления в их системе (рекоменд. добавить).
5. **Песочница** (test API key / dry-run) — полезно для интеграторов.

## Что уже готово (фундамент)
- Доменные сервисы (`create_delivery`/`start_delivery`/`resend`/soft-delete) — переиспользуем 1:1.
- Cloud Tasks (для исходящих вебхуков и ретраев) — уже подключён.
- Tracking URL `/t/<token>`, ETA (Routes), уведомления (Infobip Viber→SMS), оценка, opt-out — всё есть.
- `Delivery.source = api` — задел уже в модели.

## Прогресс (план → коммиты/релизы)

- ✅ **Epic API-1 (ключи) + Epic API-2 (срез: create/start/get)** — ApiKey-модель, key-auth, `POST /api/v1/deliveries` (idempotency), `POST /{id}/start`, `GET /{id}`, генерация/отзыв ключей в профиле. 26 API-тестов. _Реализовано субагентом (worktree), интегрировано в `main`; релиз — см. `v0.26.0`._
- ✅ **Epic API-2 (полный паритет) + DRF/drf-spectacular** — все эндпоинты на DRF; `list/ready/delivered/resend/DELETE/restore`; industry-статусы (`pending/ready_for_pickup/out_for_delivery/delivered` + `status_internal`); API-действия тоже шлют вебхуки (логика в services). _Субагент → merge (резолв конфликта) → релиз `v0.29.0`._
- ✅ **Epic API-3 (вебхуки мерчанту)** — `Shop.webhook_url/secret` (admin+профиль), события delivery.started/notification.delivered|read|failed/delivery.delivered/rating.created, HMAC `Javi-Signature`, доставка через Cloud Tasks (очередь javi-rating), failure-safe. _Субагент → интегрировано; релиз `v0.28.0`._
- ✅ **Epic API-1 (регистрация)** — self-service sign-up на `/accounts/register/` (User+Shop, авто-логин). _Субагент → интегрировано; релиз `v0.27.0`._
- ✅ **Epic API-4 (доки)** — OpenAPI `/api/schema/`, Swagger `/api/docs/`, ReDoc `/api/redoc/` (публично); `/app/api` со ссылками + curl quick-start. _Релиз `v0.29.0`._

- ✅ **Паритет завершён** — `GET/PATCH /api/v1/shop` (имя, адрес+геокод, webhook_url/secret). Все UI-действия жизненного цикла доставки + конфиг магазина доступны через API со стандартными статусами. _Релиз `v0.30.0`._

> Отмечаем по мере выполнения: статус + commit/release тег. Реализация — TDD (тесты → код → рефактор → следующий пункт), многозадачные части — субагентами параллельно.
