# Javi: лендинг в прод — пошаговый план (Этап 0)

Jira: реализуют SERBITO-278, 285, 306, 321, 352, 356 · follow-up SERBITO-317, SERBITO-438 · осталось: [SERBITO-474](https://serbito.atlassian.net/browse/SERBITO-474) (конверсия GA4, платный тест), [SERBITO-484](https://serbito.atlassian.net/browse/SERBITO-484) (итог гейта)

Практический чек-лист: как довести **статичный** лендинг Javi до продакшена и
запустить Этап 0 (валидация спроса через рекламу).

**Что уже готово** (не входит в этот план, проверено):
- Лендинг `landing/index.html` — статика, sr/en/ru, форма заявки с UTM-полями.
- CI/CD: `Dockerfile` (nginx:1.27-alpine), `nginx.conf`, `.dockerignore`,
  `.github/workflows/deploy.yaml` (Cloud Run, деплой ТОЛЬКО по тегу `v*.*.*`,
  WIF keyless, проект `serbito`, service `javi`, region `europe-west1`),
  `.pre-commit-config.yaml`, `scripts/release_minor.sh`, `pyproject.toml`.
- Docker-образ собирается локально и отдаёт лендинг на `:8080` (HTTP 200 подтверждён).

**Решения этой фазы:**
- Django на Этапе 0 **не используется** — лендинг чисто статический.
- Сбор заявок — бесплатный инструмент (Google Forms или альтернатива). Конкретный
  выбор делается **отдельным шагом** (см. фазу 1, плейсхолдер).
- Бюджет рекламы Этапа 0: **€50–100**. Гейт-цель: **5–10 заявок**.
- Каналы: Google Ads + ads.telegram.org. **UTM-атрибуция критична.**

> Детали команд по GCP / DNS — в [`SETUP_CICD.md`](../../SETUP_CICD.md).
> Здесь они **не дублируются**, а даются ссылками на нужные разделы.

---

## 0. Предусловия (один раз)

- [x] Доступ к GCP-проекту `serbito`, `gcloud` залогинен и проект выбран.
      *Проверка:* `gcloud config get-value project` → `serbito`;
      `gcloud auth list` показывает активный аккаунт.
      *(Наличие `docker` и `gcloud` уже подтверждено — образ собирался локально.)*
- [x] `docker` установлен и запускается.
      *Проверка:* `docker version` отвечает без ошибок (подтверждено).
- [x] Доступ к DNS-зоне `serbito.rs` (тот же регистратор/DNS-провайдер, где
      заводилась запись для `poker.serbito.rs`).
      *Проверка:* можешь зайти в панель DNS и видишь существующую запись `poker`.

---

## 1. Сбор заявок (lead capture)

- [x] **[ПЛЕЙСХОЛДЕР — решается отдельным шагом]** Выбрать инструмент сбора заявок
      (Google Forms / Tally / Formspree / иное бесплатное). Создать форму или
      endpoint, получить URL для атрибута `action` (или ID формы).
      *Проверка:* есть рабочий URL, на который форма может слать POST/GET.
- [x] Заменить в `landing/index.html` плейсхолдер action формы
      (`YOUR_FORM_ID` / `action="..."`) на реальный URL выбранного инструмента.
      Убедиться, что **скрытые UTM-поля сохранены** и попадают в submit.
      *Проверка:* `grep -n "action" landing/index.html` — больше нет плейсхолдера;
      в форме присутствуют поля `utm_source`, `utm_medium`, `utm_campaign`.
- [x] Локально проверить отправку формы: открыть `landing/index.html`, добавить в
      URL тестовые UTM (`?utm_source=test&utm_medium=test&utm_campaign=test`),
      заполнить и отправить форму.
      *Проверка:* заявка пришла в выбранный инструмент **вместе с UTM-значениями**
      (а не пустыми) и контактными данными.
- [x] **Privacy (обязательно для рекламы):** добавить короткую страницу или блок
      политики конфиденциальности (сбор контактов → требование Google Ads и
      сербского ZZPL / GDPR). Достаточно отдельного блока/секции в лендинге или
      `privacy.html` с текстом: какие данные собираем, зачем, как связаться.
      *Проверка:* на лендинге есть видимая ссылка «Политика конфиденциальности»,
      она открывается; текст покрывает цель сбора и контакт для запросов.

> Без privacy-страницы Google Ads, скорее всего, **не пропустит** объявления, а
> сбор контактов будет некорректен юридически. Сделать **до** фазы 6.

---

## 2. Аналитика

- [x] Подключить лёгкую веб-аналитику для воронки «визит → заявка».
      Варианты (от простого к гибкому):
      - **GA4** — бесплатно, нативно дружит с Google Ads (импорт конверсий,
        ремаркетинг). Минус: куки-баннер/сложнее настройка.
      - **Plausible / умилёгкие cookieless** — проще, без куки-баннера, но
        Plausible платный (есть self-host). Для Этапа 0 — опционально.
      - **Cloudflare Web Analytics** — бесплатно, cookieless, простой счётчик.
      *Рекомендация для Этапа 0:* **GA4** (бесплатно + связка с Google Ads даёт
      конверсии по UTM из коробки). Cloudflare — если важна простота/без куки.
- [x] Добавить счётчик (snippet) в `landing/index.html` (в `<head>`).
- [ ] Настроить событие-конверсию «отправка формы» (submit / переход на
      thank-you). **Не сделано** — [SERBITO-474](https://serbito.atlassian.net/browse/SERBITO-474).
      *Проверка:* в реалтайме аналитики виден твой тестовый визит; тестовая
      отправка формы фиксируется как конверсионное событие.

---

## 3. GCP / Cloud Run setup (один раз)

Полные команды — в [`SETUP_CICD.md`, раздел 3 «GCP one-time setup»](../../SETUP_CICD.md#3-gcp-one-time-setup).
Кратко, что нужно сделать:

- [x] Включить API: `run`, `artifactregistry`, `iam`, `iamcredentials`
      (раздел 3.1). *Многое уже включено под poker.*
- [x] Создать Artifact Registry репозиторий `javi` в `europe-west1` (раздел 3.2).
      *Проверка:* `gcloud artifacts repositories list --location=europe-west1 --project=serbito`
      содержит `javi` (или ошибка `ALREADY_EXISTS`).
- [x] Создать deployer service account `javi-deployer@serbito.iam.gserviceaccount.com`
      и выдать роли `run.admin`, `artifactregistry.writer`,
      `iam.serviceAccountUser`, `storage.admin` (раздел 3.3).
- [x] WIF: привязать репозиторий `alxndr-bnd/transport_site` к существующему
      pool `github-pool` через `workloadIdentityUser` (раздел 3.4).
      *(Pool и provider уже созданы под poker — переиспользуем, не создаём заново.)*
- [x] **КРИТИЧНО — подтвердить значения, скопированные из poker:**
      - Номер проекта = `488744139718`:
        `gcloud projects describe serbito --format='value(projectNumber)'`
      - Pool/provider существуют (см. команды в конце раздела 3.4).
      *Проверка:* номер совпадает с `WIF_PROVIDER` в `deploy.yaml`; describe
      pool/provider не возвращает `NOT_FOUND`. Если расходится — поправить
      `WIF_PROVIDER` в `.github/workflows/deploy.yaml`.

> GitHub Secrets **не нужны** — авторизация keyless через WIF
> ([`SETUP_CICD.md`, раздел 4](../../SETUP_CICD.md#4-github-secrets)).

---

## 4. Первый деплой

- [x] Локально собрать и проверить образ (уже делалось, повторить после правок
      формы/аналитики):
      ```bash
      docker build -t javi-local .
      docker run --rm -p 8080:8080 javi-local
      # в другом терминале:
      curl -I http://localhost:8080   # ожидаем HTTP/1.1 200
      ```
      *Проверка:* `curl` возвращает `200`, отдаётся обновлённый лендинг.
- [x] Установить pre-commit (если ещё не стоит):
      ```bash
      pip install pre-commit && pre-commit install
      ```
      *Проверка:* `pre-commit run --all-files` проходит зелёным
      ([`SETUP_CICD.md`, раздел 2](../../SETUP_CICD.md#2-local-setup-uv-and-pre-commit)).
- [x] Выпустить релиз (создаёт тег `v0.1.0`, пушит → триггерит workflow):
      ```bash
      bash scripts/release_minor.sh "first deploy"
      ```
      *Проверка:* в GitHub → **Actions** workflow «Deploy to Cloud Run»
      отработал зелёным (jobs `verify` → `deploy`).
- [x] Проверить `*.run.app` URL:
      ```bash
      gcloud run services describe javi --region=europe-west1 \
        --project=serbito --format='value(status.url)'
      ```
      затем `curl -I <url>` → `200`
      ([`SETUP_CICD.md`, раздел 6](../../SETUP_CICD.md#6-first-deploy)).
      *Проверка:* URL `https://javi-...run.app` отвечает `200`, лендинг открывается.

---

## 5. Домен javi.serbito.rs

Команды — [`SETUP_CICD.md`, раздел 5 «DNS / поддомен»](../../SETUP_CICD.md#5-dns-javiserbitors).
Делается **после** первого деплоя (domain mapping требует существующий сервис).

- [x] Создать domain mapping в Cloud Run (`javi.serbito.rs` → service `javi`)
      (раздел 5.1).
- [x] Прописать выданную DNS-запись (обычно CNAME `javi → ghs.googlehosted.com.`)
      в зону `serbito.rs` (раздел 5.2).
      *Проверка:* `dig javi.serbito.rs` показывает ожидаемую CNAME/запись.
- [x] Дождаться TLS (15–60 мин), проверить статус (раздел 5.3:
      `gcloud run domain-mappings describe ...` → все `status.conditions` = `True`).
- [x] Финальная проверка:
      `curl -I https://javi.serbito.rs` → `200`; открыть в браузере, **отправить
      тестовую заявку с UTM** — должна дойти в инструмент сбора (фаза 1) и
      зафиксироваться в аналитике (фаза 2). *(Визит — да; событие-конверсия — SERBITO-474.)*
      *Проверка:* https-замок валиден, заявка + UTM доходят end-to-end.

---

## 6. Реклама / запуск Этапа 0

- [ ] Собрать UTM-ссылки на лендинг:
      - Google Ads:
        `https://javi.serbito.rs/?utm_source=google&utm_medium=cpc&utm_campaign=stage0`
      - Telegram Ads:
        `https://javi.serbito.rs/?utm_source=telegram&utm_medium=ads&utm_campaign=stage0`
      *Проверка:* по каждой ссылке лендинг открывается, и при отправке формы в
      заявке/аналитике видны именно эти `utm_source/medium/campaign`.
- [ ] Запустить кампании в Google Ads и на ads.telegram.org (не запускались — SERBITO-474), общий бюджет
      **€50–100**. Перед стартом убедиться, что privacy-страница (фаза 1) на месте
      — иначе модерация Google завернёт.
      *Проверка:* объявления прошли модерацию и показываются; клики идут на
      UTM-ссылки.
- [ ] Мониторинг ежедневно: число заявок (цель-гейт **5–10**) и распределение по
      UTM (какой канал приносит лиды дешевле).
      *Проверка:* есть простая сводка «заявки за день + источник»; считаешь
      cost-per-lead по каждому каналу.

---

## 7. Гейт решения

- [ ] Подвести итог по окончании бюджета/срока кампании. *Гейт пройден не был: MVP построен 2026-06-03…06-07 без кампании. Зафиксировать итог или «пропущен» — SERBITO-484.*
      - **≥ 5 заявок** → спрос подтверждён → переходим к **Этапу 1**: оживляем
        Django, строим MVP
        ([`SETUP_CICD.md`, раздел 8](../../SETUP_CICD.md#8-runtime-cloud-sql-secrets-env)).
      - **< 5 заявок** → пересмотр: оффер, текст лендинга, канал, таргетинг.
        Возможно повторить Этап 0 с правками.
      *Проверка:* решение зафиксировано (идём в MVP / итерируем), с цифрами по
      заявкам и cost-per-lead по каналам.

---

## Что требует РУЧНЫХ действий пользователя

| # | Действие | Где / как | Блокирует |
|---|----------|-----------|-----------|
| 1 | Выбрать и создать инструмент сбора заявок, получить URL | Внешний сервис (Google Forms / Tally / Formspree) — **решается отдельно** | Фазу 1, форму |
| 2 | Заменить `action`/`YOUR_FORM_ID` в `landing/index.html` | Локально, правка файла | Сбор заявок |
| 3 | Добавить страницу/блок политики конфиденциальности | `landing/` | Запуск Google Ads (фаза 6) |
| 4 | Подключить аналитику (snippet в `index.html`) | GA4 / Cloudflare | Метрики воронки |
| 5 | **Проверить project number `488744139718`** и наличие `github-pool` | `gcloud ...` (фаза 3) | Деплой через WIF |
| 6 | GCP one-time: AR `javi`, deployer SA, WIF binding | `gcloud` по SETUP_CICD §3 | Первый деплой |
| 7 | Прописать DNS-запись `javi` в зоне `serbito.rs` | Панель DNS-провайдера | Домен `javi.serbito.rs` |
| 8 | Создать и запустить рекламные кампании (€50–100) | Google Ads + ads.telegram.org | Этап 0 |
| 9 | Мониторить заявки и UTM, принять гейт-решение | Инструмент заявок + аналитика | Переход к MVP |

## Прогресс (сверка 2026-10-05)

- ✅ §0–§4 — лендинг на Cloud Run, деплой по тегу. _b7f53ba, релиз `v0.1.0`._
- ✅ §1 — форма заявки → Formspree со скрытыми UTM-полями. _b7f53ba, `v0.1.0`._ Privacy-страница `/privacy.html`. _62af6ab, `v0.2.0`._
- ✅ §2 — GA4. _02357d4, `v0.44.0`._ Consent Mode v2. _1bfaa95, `v0.61.0` (SERBITO-321)._
- ✅ §5 — домен `javi.serbito.rs` отвечает 200.
- ⬜ §2 — событие-конверсия при отправке формы — [SERBITO-474](https://serbito.atlassian.net/browse/SERBITO-474).
- ⬜ §6 — платный тест Google Ads + Telegram Ads, заявки и CPL по каналам — [SERBITO-474](https://serbito.atlassian.net/browse/SERBITO-474).
- ⬜ §7 — итог гейта (или «пропущен») — [SERBITO-484](https://serbito.atlassian.net/browse/SERBITO-484).
