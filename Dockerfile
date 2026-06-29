# ---- Stage 1: Django + gunicorn (Javi MVP) ----
# Лендинг Этапа 0 остаётся в образе (landing/) и отдаётся WhiteNoise на /.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    STATICFILES_BACKEND=whitenoise.storage.CompressedManifestStaticFilesStorage

WORKDIR /app

# Patch base-image OS packages (Debian security updates) so the Trivy deploy gate
# doesn't fail on a fixed base CVE.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# uv для установки зависимостей по lock-файлу
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Собрать статику (manifest) на этапе сборки
RUN python manage.py collectstatic --noinput

EXPOSE 8080

# Миграции на старте, затем gunicorn на $PORT (Cloud Run = 8080)
CMD exec sh -c "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 60"
