# Настройка CI/CD и домена для проекта Javi

Пошаговый гайд: как поднять автоматический деплой (CI/CD) и подключить поддомен
`javi.serbito.rs` для проекта **Javi** (репозиторий `alxndr-bnd/transport_site`).

Деплой устроен так же, как уже работающий `poker.serbito.rs`: тот же GCP-проект
`serbito`, тот же регион `europe-west1`, тот же Workload Identity Pool `github-pool`.

## Оглавление

1. [Что уже сделано](#1-что-уже-сделано)
2. [Предварительно: установить pre-commit локально](#2-предварительно-установить-pre-commit-локально)
3. [GCP one-time setup](#3-gcp-one-time-setup)
4. [GitHub secrets](#4-github-secrets)
5. [DNS / поддомен javi.serbito.rs](#5-dns--поддомен-javiserbitors)
6. [Первый деплой](#6-первый-деплой)
7. [Как это работает дальше (ежедневно)](#7-как-это-работает-дальше-ежедневно)
8. [Этап 1 (на будущее): Django](#8-этап-1-на-будущее-django)

> **Перед началом подставьте свои значения там, где помечено `<...>`.**
> Команды `gcloud` предполагают, что у вас установлен и авторизован Google Cloud SDK
> (`gcloud auth login` и `gcloud config set project serbito`).

---

## 1. Что уже сделано

В репозитории уже лежит всё необходимое для CI/CD:

- **CI** `.github/workflows/ci.yaml` — гейт релиза (`ruff check`, `manage.py check`,
  `pytest`, парсинг лендинга) на каждый PR (включая Dependabot) и каждый пуш в `main`.
- **Пайплайн** `.github/workflows/deploy.yaml` — GitHub Actions, который при пуше
  тега вида `v*.*.*` сначала прогоняет job **`verify`** (тот же `ci.yaml` через
  `workflow_call`), затем собирает Docker-образ, пушит его в Artifact Registry и деплоит
  в Cloud Run. Авторизация — keyless через Workload Identity Federation (WIF),
  без ключей в секретах. Ключевые значения (из `env` пайплайна):
  - `PROJECT_ID=serbito`
  - `REGION=europe-west1`
  - `SERVICE=javi`
  - `AR_IMAGE=europe-west1-docker.pkg.dev/serbito/javi/javi`
  - `WIF_PROVIDER=projects/488744139718/locations/global/workloadIdentityPools/github-pool/providers/github`
  - `DEPLOYER_SA=javi-deployer@serbito.iam.gserviceaccount.com`
- **Dockerfile** — образ на базе `nginx:1.27-alpine`, копирует `nginx.conf` и
  каталог `landing/` и отдаёт статический лендинг (`landing/index.html`) на порту
  `8080` (требование Cloud Run).
- **pre-commit** — конфиг `.pre-commit-config.yaml`: `ruff` (lint, с `--fix`) и
  `ruff-format`; check-yaml, check-merge-conflict, end-of-file-fixer,
  trailing-whitespace; локальные хуки — проверка, что `landing/index.html`
  парсится, и `manage.py check` (Django system check). То есть в репозитории уже
  есть Django-приложение — но на Этапе 0 деплоится именно статический лендинг.
- **Release-скрипт** `scripts/release_minor.sh` — перед релизом гоняет гейт
  (`pytest`, `ruff check`, `manage.py check`, парсинг лендинга), коммитит
  изменения отслеживаемых файлов (`git add -u`; новые файлы — только перечисленные
  аргументами, о прочих неотслеживаемых печатает предупреждение), поднимает
  минорную версию (`vMAJOR.MINOR.0`), создаёт git-тег и пушит его (что и триггерит
  деплой). Версия начинается с `v0.1.0`, если тегов ещё нет.

Дальше нужно один раз настроить инфраструктуру в GCP и DNS.

---

## 2. Предварительно: установить pre-commit локально

Чтобы хуки гонялись перед каждым коммитом локально:

```bash
# из корня репозитория
pip install pre-commit
# либо, если используете виртуальное окружение:
# venv/bin/pip install pre-commit

pre-commit install
```

После `pre-commit install` хуки из `.pre-commit-config.yaml` будут автоматически
запускаться при каждом `git commit`. Если хук что-то поправил (например, ruff
переформатировал код или убрал лишние пробелы) — добавьте изменения
(`git add -A`) и закоммитьте ещё раз.

> Хук `django-check` выполняет `manage.py check`, поэтому в окружении должны быть
> установлены зависимости Django (см. `requirements*.txt` / `venv`). Если используете
> виртуальное окружение — активируйте его перед коммитом. Тот же гейт срабатывает
> и в `scripts/release_minor.sh` перед созданием тега.

Прогнать хуки по всем файлам вручную (полезно в первый раз):

```bash
pre-commit run --all-files
```

---

## 3. GCP one-time setup

Выполняется **один раз**. Поскольку проект `serbito` уже используется для
`poker.serbito.rs`, многое (включённые API, WIF-pool) уже на месте — лишние
команды просто завершатся без изменений. Команды можно выполнять повторно
безопасно.

### 3.1. Включить нужные API

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project=serbito
```

### 3.2. Создать Artifact Registry репозиторий `javi`

```bash
gcloud artifacts repositories create javi \
  --repository-format=docker \
  --location=europe-west1 \
  --project=serbito
```

> Если репозиторий уже существует — команда вернёт ошибку `ALREADY_EXISTS`, это ок.

### 3.3. Создать deployer service account и выдать роли

Создаём сервисный аккаунт, от имени которого GitHub Actions деплоит:

```bash
gcloud iam service-accounts create javi-deployer \
  --display-name="Javi GitHub Actions deployer" \
  --project=serbito
```

Выдаём ему роли на уровне проекта (управление Cloud Run, пуш образов, запуск
сервисных аккаунтов, доступ к storage для Artifact Registry):

```bash
PROJECT_ID=serbito
SA=javi-deployer@serbito.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/storage.admin"
```

> `roles/iam.serviceAccountUser` нужен, чтобы deployer мог деплоить сервис под
> runtime-аккаунтом Cloud Run. `roles/storage.admin` нужен для работы с
> базовым GCS-бакетом Artifact Registry. Если хотите минимизировать права,
> можно позже сузить `storage.admin` до доступа только к нужному бакету AR.

### 3.4. WIF: привязать репозиторий к существующему provider'у

Workload Identity Pool `github-pool` и provider `github` **уже существуют**
(их создали для poker). Мы их **переиспользуем** — создавать заново НЕ нужно.
Нужно лишь разрешить deployer-аккаунту имперсонацию из нашего репозитория
`alxndr-bnd/transport_site`.

```bash
PROJECT_NUMBER=488744139718
SA=javi-deployer@serbito.iam.gserviceaccount.com
POOL=github-pool
REPO=alxndr-bnd/transport_site

gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --project=serbito \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}"
```

> ⚠️ **Проверьте перед запуском:**
> - `PROJECT_NUMBER=488744139718` — это значение взято из `WIF_PROVIDER` в нашем
>   `deploy.yaml` (скопировано из poker). Убедитесь, что номер проекта `serbito`
>   именно такой:
>   ```bash
>   gcloud projects describe serbito --format='value(projectNumber)'
>   ```
> - Pool `github-pool` и provider `github` существуют:
>   ```bash
>   gcloud iam workload-identity-pools describe github-pool \
>     --location=global --project=serbito
>   gcloud iam workload-identity-pools providers describe github \
>     --location=global --workload-identity-pool=github-pool --project=serbito
>   ```
>   Если их нет (или provider называется иначе), значения в `deploy.yaml`
>   придётся поправить под фактическую настройку.

---

## 4. GitHub secrets

**Секреты для нашего workflow НЕ нужны.** Авторизация в GCP идёт через
Workload Identity Federation (keyless), а все параметры (`PROJECT_ID`, `REGION`,
`SERVICE`, `AR_IMAGE`, `WIF_PROVIDER`, `DEPLOYER_SA`) зашиты в `env` пайплайна.

> Примечание: в старом README poker упоминался секрет `GCP_SA_KEY` (JSON-ключ
> сервисного аккаунта). В **нашем** `deploy.yaml` его нет и он не нужен — мы не
> используем ключи, только WIF. Ничего в GitHub Secrets добавлять не требуется.

Единственный секрет понадобится **на будущее** (Этап 1, когда появится Django) —
`SECRET_KEY`, и его хранят не в GitHub Secrets, а в **Secret Manager** GCP
(см. раздел 8).

---

## 5. DNS / поддомен javi.serbito.rs

Отдельное доменное имя покупать не нужно — у вас уже есть домен `serbito.rs`.
Подключим поддомен `javi.serbito.rs` к Cloud Run.

> Domain mapping можно создавать только **после** того, как сервис `javi` хоть
> раз задеплоен (см. раздел 6). Так что этот шаг логично выполнять сразу после
> первого деплоя.

### 5.1. Создать domain mapping в Cloud Run

```bash
gcloud run domain-mappings create \
  --service=javi \
  --domain=javi.serbito.rs \
  --region=europe-west1 \
  --project=serbito
```

### 5.2. Прописать DNS-запись

Команда из 5.1 выведет DNS-запись, которую нужно добавить в зону `serbito.rs`.
Обычно это **CNAME** на `ghs.googlehosted.com.` (для поддомена), реже —
набор **A/AAAA** записей. Посмотреть запись повторно можно так:

```bash
gcloud run domain-mappings describe \
  --domain=javi.serbito.rs \
  --region=europe-west1 \
  --project=serbito \
  --format='value(status.resourceRecords)'
```

Добавьте эту запись в DNS-зону `serbito.rs` — **там же**, у того же
регистратора / DNS-провайдера, где вы заводили запись для `poker.serbito.rs`.
Например (значение подставьте из вывода выше):

```
Тип:   CNAME
Имя:   javi            (т.е. javi.serbito.rs)
Цель:  ghs.googlehosted.com.
```

### 5.3. Верификация и TLS

- Домен `serbito.rs` **уже верифицирован** в GCP (иначе `poker.serbito.rs` не
  работал бы), поэтому отдельная верификация владения доменом, скорее всего,
  **не потребуется**. Если Cloud Run всё же попросит верифицировать домен —
  следуйте инструкции из вывода команды (через Google Search Console).
- **TLS-сертификат** Cloud Run выпустит и подключит **автоматически** после того,
  как DNS-запись прописана и распространилась. Это может занять от ~15 до ~60 минут.
  Статус можно отслеживать:
  ```bash
  gcloud run domain-mappings describe \
    --domain=javi.serbito.rs \
    --region=europe-west1 \
    --project=serbito
  ```
  Дождитесь, пока в `status.conditions` всё станет `True`.

---

## 6. Первый деплой

Есть два пути запустить пайплайн.

### Вариант А — вручную через GitHub UI (workflow_dispatch)

1. Открой репозиторий на GitHub → вкладка **Actions**.
2. Слева выбери workflow **Deploy to Cloud Run**.
3. Кнопка **Run workflow** → ветка `main` → **Run workflow**.

Удобно для первой проверки, что инфраструктура (раздел 3) настроена правильно.

### Вариант Б — тегом (рекомендуемый рабочий способ)

```bash
bash scripts/release_minor.sh "first deploy"
```

Скрипт создаст тег `v0.1.0` (если тегов ещё нет), запушит его — и это
триггернёт workflow.

### Что будет после деплоя

- Сервис `javi` появится в Cloud Run и получит автоматический URL вида
  `https://javi-xxxxxxxx-ew.a.run.app`. Его можно посмотреть в конце лога
  workflow (шаг **Show URL**) или командой:
  ```bash
  gcloud run services describe javi \
    --region=europe-west1 --project=serbito \
    --format='value(status.url)'
  ```
- После настройки domain mapping (раздел 5) тот же сервис будет доступен по
  адресу **https://javi.serbito.rs**.

---

## 7. Как это работает дальше (ежедневно)

Рабочий цикл после настройки:

1. Вносишь изменения в код / лендинг, коммитишь в `main`
   (при коммите локально срабатывает **pre-commit** — гейт качества).
2. Выкатываешь релиз:
   ```bash
   bash scripts/release_minor.sh "что изменили" [новый_файл ...]
   ```
   Скрипт поднимает минорную версию, создаёт git-тег и пушит его.
3. Дальше всё автоматически — **GitHub Actions**:
   - **verify** — гейт из `ci.yaml`: ruff, `manage.py check`, pytest, лендинг;
   - **build + push** — собирает Docker-образ и пушит в Artifact Registry
     (`europe-west1-docker.pkg.dev/serbito/javi/javi`);
   - **deploy** — деплоит новую ревизию в Cloud Run (`javi`, `europe-west1`).

Через минуту-две новая версия уже на `https://javi.serbito.rs`. Никаких ручных
действий с GCP больше не нужно.

---

## 8. Этап 1 (на будущее): Django

Когда статический лендинг заменим на Django-приложение:

- Заменить `Dockerfile` на вариант с Python + `gunicorn` (вместо nginx-лендинга),
  по-прежнему слушающий порт `8080`.
- Завести `SECRET_KEY` в **Secret Manager** GCP и подключить его к Cloud Run через
  `--update-secrets=SECRET_KEY=javi-secret-key:latest` в шаге деплоя; прочие
  настройки — через `--set-env-vars`.
- Выдать deployer-SA (или runtime-SA) роль `roles/secretmanager.secretAccessor`.
- Ужесточить `pre-commit`: добавить запуск тестов (`pytest`/`manage.py test`) как
  блокирующий гейт перед коммитом, плюс линтеры (ruff/black).
