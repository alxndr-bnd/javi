# uv, pinned by version and digest (supply chain, SERBITO-289). A named stage rather than
# `COPY --from=<image>`: Dependabot's docker ecosystem only parses and bumps FROM lines.
# The single source of the uv version: CI (ci.yaml) reads it from this line (SERBITO-294).
# Build-time only: the sync step bind-mounts the binary, the runtime image has no uv
# (Aikido flagged its Rust crates, SERBITO-387).
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

# ---- Stage 1: Django + gunicorn (Javi MVP) ----
# Лендинг Этапа 0 остаётся в образе (landing/) и отдаётся WhiteNoise на /.
# Base pinned by tag + multi-arch index digest (SERBITO-294): a re-pushed 3.14-slim can't
# change prod without a commit; Dependabot (docker) bumps the digest. Python minor must match
# .python-version (CI's interpreter) — config/test_dockerfile.py checks it.
FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    STATICFILES_BACKEND=whitenoise.storage.CompressedManifestStaticFilesStorage

WORKDIR /app

# Patch base-image OS packages (Debian security updates) so the Trivy deploy gate
# doesn't fail on a fixed base CVE. APT_REFRESH is the UTC date (deploy.yaml passes it):
# the RUN reads it, so each day's first build re-runs the upgrade instead of reusing a
# stale cached layer (SERBITO-369).
ARG APT_REFRESH
RUN echo "apt refresh: ${APT_REFRESH:-unset}" && \
    apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Манифесты вендоринга системного pip (pip/_vendor/bom.cdx.json, vendor.txt) декларируют его
# внутренние setuptools 70.3.0 и msgpack 1.1.2 — Trivy видит в них HIGH CVE без PkgPath, хотя
# таких пакетов в окружении нет и pip они для работы не нужны (как в serbito и gtd).
RUN find /usr/local/lib -type f \( -name 'bom.cdx.json' -o -name 'vendor.txt' \) -path '*/pip/_vendor/*' -delete

# Cold start (SERBITO-323): every process start used to compile all imported modules from
# source — the base image ships the stdlib without .pyc, uv installs without them, and
# PYTHONDONTWRITEBYTECODE never caches them. Compile once at build time instead: stdlib here
# (its own layer, cached), dependencies via --compile-bytecode, app code after COPY.
RUN python -m compileall -q -j 0 "$(python -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"

COPY pyproject.toml uv.lock ./
# uv only for this step: a BuildKit bind mount from the uv stage, not a COPY into the image.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --compile-bytecode

COPY . .
RUN python -m compileall -q -j 0 -x '/\.venv/' /app

# Собрать статику (manifest) на этапе сборки
RUN python manage.py collectstatic --noinput

# Run as an unprivileged user (least privilege; Cloud Run binds non-privileged 8080).
# Added after collectstatic (which needs root write) and before runtime; nothing writes to
# the image filesystem at runtime.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Только gunicorn на $PORT (Cloud Run = 8080). Миграций на старте нет (SERBITO-323): их
# гоняет деплой — Cloud Run job javi-migrate до переключения трафика (deploy.yaml). Для
# локального/self-hosted запуска: `docker run … python manage.py migrate --noinput`.
# --preload: приложение импортируется один раз в мастере, воркеры форкаются готовыми — на
# 1 vCPU два воркера не импортируют Django параллельно. БД при импорте не трогается (соединения
# ленивые), Sentry после fork сам перезапускает свой поток.
# JSON-форма CMD + exec: gunicorn становится PID 1 и получает SIGTERM от Cloud Run напрямую
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 60 --preload"]
