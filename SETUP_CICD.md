# CI/CD and domain setup for Javi

How Javi (`alxndr-bnd/transport_site`) is built, tested and deployed to Cloud Run at
`javi.serbito.rs`, and the one-time GCP/DNS setup behind it. Same GCP project (`serbito`),
region (`europe-west1`) and Workload Identity Pool (`github-pool`) as `poker.serbito.rs`.

## Contents

1. [What is in the repo](#1-what-is-in-the-repo)
2. [Local setup: uv and pre-commit](#2-local-setup-uv-and-pre-commit)
3. [GCP one-time setup](#3-gcp-one-time-setup)
4. [GitHub secrets](#4-github-secrets)
5. [DNS: javi.serbito.rs](#5-dns-javiserbitors)
6. [First deploy](#6-first-deploy)
7. [Day-to-day release flow](#7-day-to-day-release-flow)
8. [Runtime: Cloud SQL, secrets, env](#8-runtime-cloud-sql-secrets-env)
9. [Database migrations](#9-database-migrations)
10. [Scheduled jobs: recipient data purge](#10-scheduled-jobs-recipient-data-purge)

> Commands assume an authenticated Google Cloud SDK
> (`gcloud auth login`, `gcloud config set project serbito`).

---

## 1. What is in the repo

- **CI** — `.github/workflows/ci.yaml`: the release gate (`ruff check`, `manage.py check`,
  `pytest`, landing HTML parse) on every PR (incl. Dependabot) and every push to `main`.
  Tests use the sqlite fallback: no `DATABASE_URL`, no `.env`.
- **Deploy** — `.github/workflows/deploy.yaml`, triggered by a pushed `v*.*.*` tag, and by the
  weekly OS refresh of the newest tag ([section 7](#7-day-to-day-release-flow)):
  1. `verify` — the same `ci.yaml` via `workflow_call`;
  2. `build`, at the same time as `verify` (SERBITO-552) — build the image with Buildx (registry
     cache `:buildcache`), push it to Artifact Registry as `:<commit sha>` (a refresh:
     `:<commit sha>-r<YYYYMMDD>`), Trivy scan (fails on a *fixed* HIGH/CRITICAL vulnerability or a
     leaked secret). A red `verify` leaves this image unused in Artifact Registry;
  3. `deploy`, only after `verify` and `build` passed — check out the built tag (stops if the tag
     moved since the build), run the migrate job if migrations changed
     ([section 9](#9-database-migrations)), then `gcloud run deploy`, which moves traffic, and a
     smoke check of the main page (not 200 → traffic back to the previous revision, run fails),
     then a security headers check of `/` (`scripts/check_security_headers.sh`; a missing header
     fails the run, traffic stays on the new revision). The new revision gets the tag
     `candidate`; both checks use `https://candidate---<service host>/`, and the last step
     removes the tag, also after a failure (SERBITO-430).

  Auth is keyless via Workload Identity Federation. Pipeline `env`:
  - `PROJECT_ID=serbito`, `REGION=europe-west1`, `SERVICE=javi`
  - `AR_IMAGE=europe-west1-docker.pkg.dev/serbito/javi/javi`
  - `WIF_PROVIDER=projects/488744139718/locations/global/workloadIdentityPools/github-pool/providers/github`
  - `DEPLOYER_SA=javi-deployer@serbito.iam.gserviceaccount.com`
  - `RUNTIME_SA=javi-run@serbito.iam.gserviceaccount.com` (service and migrate job; SERBITO-347)
  - `CLOUDSQL_INSTANCE`, `MIGRATE_JOB=javi-migrate`, `RUN_SECRETS` (shared by service and job)
- **Dockerfile** — Django + gunicorn:
  - base `python:3.14-slim` and a `uv` stage (`ghcr.io/astral-sh/uv`), both pinned by
    tag + digest;
  - OS packages upgraded (`apt-get upgrade`); pip's vendored SBOM manifests removed
    (false-positive Trivy CVEs);
  - dependencies installed with `uv sync --frozen --no-dev` from `pyproject.toml` + `uv.lock`;
    uv is bind-mounted for that step only, so the runtime image has no `uv` (SERBITO-387);
  - bytecode compiled at build time (stdlib, dependencies, app), so a cold start doesn't
    compile every module from source;
  - `collectstatic` at build time; WhiteNoise serves static files and the landing page
    (`landing/`) at `/`;
  - runs as unprivileged `appuser` (uid 10001);
  - on start: only gunicorn on `$PORT` (8080 on Cloud Run), 2 workers × 4 threads,
    `--preload`. No migrations on start: the deploy runs them ([section 9](#9-database-migrations)).
- **One toolchain for CI and the image** — CI's Python comes from `.python-version` and must
  match the image's `python:X.Y-slim`; CI's uv version is read from the Dockerfile's `uv`
  stage. `config/test_dockerfile.py` fails if they drift or a base image loses its digest.
- **Dependabot** — `.github/dependabot.yml`, weekly: `uv` (Python deps), `docker` (Dockerfile
  `FROM` digests and the uv tag), `github-actions` (SHA-pinned actions).
- **pre-commit** — `.pre-commit-config.yaml`: pre-commit-hooks (check-yaml,
  check-merge-conflict, end-of-file-fixer, trailing-whitespace), `ruff --fix`,
  `ruff-format`, and local hooks: landing HTML parses, `uv run python manage.py check`.
- **Release script** — `scripts/release_minor.sh "message" [new_file ...]`, from `main` only:
  turns `## [Unreleased]` in `CHANGELOG.md` into `## [X.Y.0] - <today>` (refuses when it has no
  entries, before anything else), runs the gate (`pytest`, `ruff check`, `manage.py check`,
  landing parse), stages tracked changes (`git add -u`) plus the listed new files (warns about
  other untracked files), commits, bumps the minor version (`vMAJOR.MINOR.0`; `v0.1.0` if no
  tags), then tags and pushes, which triggers the deploy. Last, it creates the GitHub Release from
  the version's English CHANGELOG lines (`changelog.py notes`).

---

## 2. Local setup: uv and pre-commit

```bash
uv sync                  # .venv with runtime + dev dependencies from uv.lock
uv run playwright install chromium  # once: the browser for config/test_consent_focus.py
uv run pytest            # the gate, as in CI
uv run ruff check .
uv run python manage.py check

pre-commit install       # hooks on every commit (install pre-commit first, e.g. `uv tool install pre-commit`)
pre-commit run --all-files
```

If a hook rewrites files (ruff, whitespace), stage the changes and commit again.

---

## 3. GCP one-time setup

Idempotent: much of it already exists for poker, so re-running is safe.

### 3.1. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project=serbito
```

The Django runtime also uses Cloud SQL, Secret Manager and Cloud Tasks (section 8).

### 3.2. Artifact Registry repository `javi`

```bash
gcloud artifacts repositories create javi \
  --repository-format=docker \
  --location=europe-west1 \
  --project=serbito
```

`ALREADY_EXISTS` is fine.

### 3.3. Deployer service account and roles

```bash
gcloud iam service-accounts create javi-deployer \
  --display-name="Javi GitHub Actions deployer" \
  --project=serbito

PROJECT_ID=serbito
SA=javi-deployer@serbito.iam.gserviceaccount.com
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role="$ROLE"
done
```

- `run.admin` covers the service and the `javi-migrate` job (create, update, execute).
- `iam.serviceAccountUser` lets the deployer deploy the service and the job under the
  Cloud Run runtime account (`RUNTIME_SA`).
- `storage.admin` covers Artifact Registry's GCS bucket; can be narrowed to that bucket later.

### 3.4. WIF: allow this repo to impersonate the deployer

Pool `github-pool` and provider `github` already exist (created for poker); reuse them.

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

Check first:

```bash
gcloud projects describe serbito --format='value(projectNumber)'   # must be 488744139718
gcloud iam workload-identity-pools describe github-pool --location=global --project=serbito
gcloud iam workload-identity-pools providers describe github \
  --location=global --workload-identity-pool=github-pool --project=serbito
```

If they differ, fix `WIF_PROVIDER` in `deploy.yaml`.

---

## 4. GitHub secrets

None. GCP auth is keyless (WIF) and the pipeline parameters live in `deploy.yaml` `env`.
Runtime secrets are in GCP Secret Manager (section 8), not in GitHub.

---

## 5. DNS: javi.serbito.rs

Requires the `javi` service to exist: run it after the first deploy.

```bash
gcloud run domain-mappings create \
  --service=javi --domain=javi.serbito.rs \
  --region=europe-west1 --project=serbito

# DNS record to add (usually CNAME javi -> ghs.googlehosted.com.):
gcloud run domain-mappings describe \
  --domain=javi.serbito.rs --region=europe-west1 --project=serbito \
  --format='value(status.resourceRecords)'
```

- Add the record in the `serbito.rs` zone, at the same DNS provider as `poker.serbito.rs`.
- `serbito.rs` is already verified in GCP; if Cloud Run still asks, follow its instructions.
- Cloud Run issues the TLS certificate automatically once DNS propagates (~15-60 min).
  Done when all `status.conditions` of the mapping are `True` (same `describe`, no `--format`).

### Client IP and the Cloudflare proxy (SERBITO-420)

Sign-in lockout, the signup limit and the `/t/` rate limit count per client IP
(`common/client_ip.py`). The same code works for a DNS-only and a proxied `javi` record:

- The client is the rightmost `X-Forwarded-For` entry after our own proxies (link-local,
  Google front end, `TRUSTED_PROXIES`). XFF is read only from a private or link-local peer.
- If that entry is a Cloudflare address, the client is `CF-Connecting-IP`. From any other
  address the header is ignored, so a direct request to `*.run.app` cannot forge it.
- Cloudflare ranges are vendored in `common/cloudflare_ips.txt`. To refresh, follow the
  steps at the top of that file (source: https://www.cloudflare.com/ips/), then run
  `pytest common/test_client_ip.py`. If the list is out of date, visitors behind a new
  Cloudflare range share the limit of their edge address. No one can forge an address.
- `TRUSTED_PROXIES` (comma-separated CIDRs) is only for an extra proxy with a public
  address, e.g. an external load balancer. It is not needed today.

### The `*.run.app` guard (SERBITO-430)

`javi.serbito.rs` is behind the Cloudflare proxy (SERBITO-428). A request to the Cloud Run URL
(`javi-….run.app`) skips it, so `common/run_app_guard.py` answers there:

- GET/HEAD: `301` to the same path on `PUBLIC_BASE_URL`;
- other methods: `403`;
- the deploy tag host `candidate---…run.app`: served as usual (smoke and header checks).

No machine caller uses run.app: Cloud Tasks callbacks go to `CLOUD_TASKS_SERVICE_URL` and
Infobip webhooks to `PUBLIC_BASE_URL` (both `https://javi.serbito.rs`). Keep it so: a run.app
value there gets 403. `.run.app` stays in `ALLOWED_HOSTS` for the tag host. The guard is off
when `PUBLIC_BASE_URL` is itself a run.app URL.

---

## 6. First deploy

Deploys run only from a `v*.*.*` tag. From `main`:

```bash
bash scripts/release_minor.sh "first deploy"
```

The service URL (`https://javi-xxxxxxxx-ew.a.run.app`) is in the workflow log, or:

```bash
gcloud run services describe javi \
  --region=europe-west1 --project=serbito --format='value(status.url)'
```

After section 5 it is also served at https://javi.serbito.rs.

---

## 7. Day-to-day release flow

1. Merge to `main` (CI runs the gate on the PR and on `main`). Changes that shops notice carry
   their `CHANGELOG.md` entry under `## [Unreleased]` (format: the file's header).
2. `bash scripts/release_minor.sh "what changed" [new_file ...]` — CHANGELOG, gate, commit, tag,
   push, GitHub Release. An empty `[Unreleased]` stops the release before the gate.
3. GitHub Actions: `verify` (the CI gate) and, in parallel, `CHANGELOG.md` has a `## [X.Y.Z]`
   section for the tag (a tag pushed by hand without it fails here) → build + push the image →
   Trivy; then, only when both are green → migrate job
   (only if migration files changed) → deploy a new Cloud Run revision (`javi`,
   `europe-west1`) → smoke check of the main page, rollback on failure → security headers check.
4. Weekly OS refresh (SERBITO-401): every Wednesday 03:00 UTC, or *Run workflow*, the deploy job
   rebuilds the newest `vX.Y.Z` tag with fresh Debian packages and redeploys it. Same version and
   Sentry release; `verify` is skipped (the tag passed it). It never deploys a branch.

---

## 8. Runtime: Cloud SQL, secrets, env

What `gcloud run deploy` in `deploy.yaml` expects to exist:

- **Cloud SQL** instance `serbito:europe-west1:serbitodb` (`--add-cloudsql-instances`).
- **Secret Manager** secrets, exposed as env vars via `--set-secrets`:

  | Env var | Secret |
  |---|---|
  | `SECRET_KEY` | `javi-secret-key` |
  | `DATABASE_URL` | `javi-database-url` |
  | `GOOGLE_MAPS_API_KEY` | `javi-google-maps-key` |
  | `INFOBIP_API_KEY` | `javi-infobip-key` |
  | `INFOBIP_WEBHOOK_SECRET` | `javi-infobip-webhook-secret` |
  | `TASKS_SECRET` | `javi-tasks-secret` |
  | `SENTRY_DSN` | `javi-sentry-dsn` (Sentry org `nohandoff`, project `javi`) |
  | `ADMIN_PATH` | `javi-admin-path` — the admin's non-obvious URL prefix, e.g. `ops-<random>/` (SERBITO-362). Without it the admin is not mounted. |

  Without `SECRET_KEY` or `ALLOWED_HOSTS` the web server refuses to start (`config/checks.py`).
  Cloud Tasks callbacks get `TASKS_SECRET` in the `X-Tasks-Secret` header. Infobip delivery
  reports still carry `?secret=` in the per-message URL (Infobip sends no custom headers there);
  to drop it, create an Infobip subscription with Basic auth (password = the webhook secret)
  and set `INFOBIP_WEBHOOK_SECRET_IN_URL=False`.

- **Runtime service account** `javi-run@serbito.iam.gserviceaccount.com` (SERBITO-347; before
  it, the default compute SA): `roles/cloudsql.client` (project), `roles/secretmanager.secretAccessor`
  on each `javi-*` secret only, `roles/cloudtasks.enqueuer` on the `javi-rating` queue only.
  `javi-deployer` has `roles/iam.serviceAccountUser` on this SA. A new secret needs its own
  secret-level grant: `gcloud secrets add-iam-policy-binding <secret>
  --member=serviceAccount:javi-run@serbito.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor`.
- **Non-secret env** — `.github/deploy.env.yaml` (`--env-vars-file`); the deploy appends
  `SENTRY_RELEASE=javi@<tag without v>`. The rest (`INFOBIP_BASE_URL/SENDER/CHANNEL`,
  `PUBLIC_BASE_URL`, `CLOUD_TASKS_*`) uses the defaults in `config/settings.py`.
- **Service shape**: public (`--allow-unauthenticated`), 0-1 instances, concurrency 250,
  startup CPU boost, port 8080, request timeout 60 s.

---

## 9. Database migrations

Migrations run in the deploy, not on container start (SERBITO-323). Before, every cold start
(~28 a day, scale to zero) ran `manage.py migrate` first, which added seconds to the first
response of the landing, `robots.txt` and `sitemap.xml`.

- **Cloud Run job `javi-migrate`** — same image, runtime SA, Cloud SQL instance, secrets and
  env file as the service; command `python manage.py migrate --noinput`; 1 task, no retries,
  10 min timeout. `deploy.yaml` creates or updates it (`gcloud run jobs deploy … --execute-now
  --wait`), so there is no one-time setup and no new IAM role.
- **When it runs** — step `Detect pending migrations`: only if a `*/migrations/*.py` file
  (not `__init__.py`) changed since the commit the service runs now (the tag of its live
  image). Fallback baseline: the previous tag. Fail-safe — it runs when the job doesn't exist
  yet, when there is no baseline, or when the diff fails.
- **Order** — the job runs before `gcloud run deploy`, which is what moves traffic. A failed
  migration fails the workflow; the new revision isn't deployed and the old one keeps serving.
- **Compatibility rule** — for a moment the *old* code runs against the *new* schema. Keep
  migrations backward compatible: add columns/tables first, drop or rename in a later release.

Run it by hand (e.g. after a failed deploy, once fixed):

```bash
gcloud run jobs execute javi-migrate --region=europe-west1 --project=serbito --wait
gcloud run jobs executions list --job=javi-migrate --region=europe-west1 --project=serbito
```

Local or self-hosted Docker: the image no longer migrates on start, so run it once per
schema change: `docker run --rm --env-file .env <image> python manage.py migrate --noinput`.

---

## 10. Scheduled jobs: recipient data purge

SERBITO-467 (ZZPL, data minimisation). Javi erases the recipient's name, phone, address and
coordinates `RECIPIENT_PII_RETENTION_DAYS` (default 90) after a delivery is final. Status,
rating, dates and city stay. The same limit clears phones in the send log (`OutboundSend`) and
old geocode cache entries. Opt-outs stay, so they keep blocking sends. Code: `deliveries/retention.py`.

- **Trigger** — Cloud Scheduler job `javi-purge-recipient-pii`, daily 02:30 Europe/Belgrade,
  `POST https://javi.serbito.rs/tasks/purge-recipient-pii/` with the `X-Tasks-Secret` header
  (same secret as the Cloud Tasks callbacks). The call stops after ~40 s (request timeout 60 s);
  `"complete": false` in the answer means the next run continues. The answer and the log carry
  counts only.
- **One-time setup** — `bash scripts/setup_purge_scheduler.sh` (creates or updates the job; needs
  `roles/cloudscheduler.admin` and read access to `javi-tasks-secret`). After a secret rotation,
  run it again. No new role for the runtime SA.
- **By hand** — dry run first, then apply:

```bash
uv run python manage.py purge_recipient_pii            # counts only, nothing changes
uv run python manage.py purge_recipient_pii --apply    # erase
gcloud scheduler jobs run javi-purge-recipient-pii --location=europe-west1 --project=serbito
```

Change the period with the env var `RECIPIENT_PII_RETENTION_DAYS` (`.github/deploy.env.yaml`)
and update the privacy page (`landing/privacy.html`, sr/en/ru) in the same release.
