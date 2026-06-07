"""Django settings for Javi (config project). Env-driven (12-factor)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
# Локально читаем .env, если он есть (в проде переменные приходят из окружения).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Сторонние библиотеки
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",  # офлайн-ассеты Swagger UI / Redoc
    # Доменные приложения Javi
    "accounts",
    "deliveries",
    "notifications",
    "integrations",
    "tracking",
    "tasks",
    "common",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# База данных: DATABASE_URL из окружения; локальный fallback — sqlite.
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# i18n / время
LANGUAGE_CODE = "en"  # дефолт — английский
LANGUAGES = [("en", "English"), ("sr", "Srpski")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Belgrade"
USE_I18N = True
USE_TZ = True

# Статика через WhiteNoise
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# В проде (после collectstatic) — WhiteNoise manifest; локально/в тестах — простой бэкенд.
STATICFILES_BACKEND = env(
    "STATICFILES_BACKEND",
    default="django.contrib.staticfiles.storage.StaticFilesStorage",
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": STATICFILES_BACKEND},
}

# Лендинг Этапа 0 отдаётся WhiteNoise в корне сайта (/, /og.png, /privacy.html, ...).
# Кабинет и API живут под /app/, /accounts/, /admin/ (их WhiteNoise пропускает в Django).
WHITENOISE_ROOT = BASE_DIR / "landing"
WHITENOISE_INDEX_FILE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Аутентификация магазина
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/"

# За прокси Cloud Run — доверяем X-Forwarded-Proto для HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Усиление безопасности — включается явным флагом SECURE_SSL=True в проде (deploy.yaml).
# Выключено локально и в тестах (там запросы по http без X-Forwarded-Proto).
SECURE_SSL = env.bool("SECURE_SSL", default=False)
if SECURE_SSL:
    SESSION_COOKIE_SECURE = True  # сессионную куку только по HTTPS
    CSRF_COOKIE_SECURE = True  # CSRF-куку только по HTTPS
    SECURE_SSL_REDIRECT = True  # http → https (с учётом X-Forwarded-Proto)
    SECURE_HSTS_SECONDS = 31536000  # HSTS на год
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True  # дефолт True, фиксируем явно (безопасно всегда)

# Интеграции — провайдер карт (геокодинг + ETA). Ключ из env/Secret Manager, не в коде.
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", default="")
MAPS_PROVIDER = env(
    "MAPS_PROVIDER",
    default="integrations.google_maps.GoogleMapsProvider",
)
ROUTES_PROVIDER = env(
    "ROUTES_PROVIDER",
    default="integrations.google_maps.GoogleRoutesProvider",
)

# Интеграции — мессенджинг (Infobip Viber/SMS). Ключ из Secret Manager.
MESSAGING_PROVIDER = env(
    "MESSAGING_PROVIDER",
    default="integrations.infobip.InfobipProvider",
)
INFOBIP_BASE_URL = env("INFOBIP_BASE_URL", default="https://m9dw19.api.infobip.com")
INFOBIP_API_KEY = env("INFOBIP_API_KEY", default="")
INFOBIP_SENDER = env("INFOBIP_SENDER", default="IBSelfServe")
INFOBIP_CHANNEL = env("INFOBIP_CHANNEL", default="viber")  # viber | sms
INFOBIP_SMS_FALLBACK = env.bool("INFOBIP_SMS_FALLBACK", default=True)  # Viber→SMS при сбое
INFOBIP_WEBHOOK_SECRET = env("INFOBIP_WEBHOOK_SECRET", default="")  # защита вебхука receipts

# Отложенные задачи (Cloud Tasks). Локально — Noop; прод — CloudTasksScheduler.
TASK_SCHEDULER = env("TASK_SCHEDULER", default="tasks.scheduler.NoopTaskScheduler")
TASKS_SECRET = env("TASKS_SECRET", default="")  # защита колбэков задач
CLOUD_TASKS_PROJECT = env("CLOUD_TASKS_PROJECT", default="serbito")
CLOUD_TASKS_LOCATION = env("CLOUD_TASKS_LOCATION", default="europe-west1")
CLOUD_TASKS_QUEUE = env("CLOUD_TASKS_QUEUE", default="javi-rating")
CLOUD_TASKS_SERVICE_URL = env("CLOUD_TASKS_SERVICE_URL", default="https://javi.serbito.rs")

# Публичный базовый URL для ссылок в сообщениях (трекинг).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="https://javi.serbito.rs")

# Запас времени к расчётному ETA (минуты): now + время в пути + запас.
ETA_BUFFER_MINUTES = env.int("ETA_BUFFER_MINUTES", default=10)

# Публичная страница статуса: срок жизни ссылки и rate limit (FR-20/NFR-6).
TRACKING_TOKEN_TTL_DAYS = env.int("TRACKING_TOKEN_TTL_DAYS", default=7)
TRACKING_RATE_LIMIT = env.int("TRACKING_RATE_LIMIT", default=60)  # запросов/мин на IP

# --- Публичный API (Django REST Framework + drf-spectacular) ---------------
# Аутентификация по API-ключу магазина (см. deliveries.auth.ApiKeyAuthentication).
# Единый формат ошибок {"error": {"code", "message"}} — через deliveries.api.exception_handler.
API_THROTTLE_RATE = env("API_THROTTLE_RATE", default="120/min")  # лимит на ключ
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": ["deliveries.auth.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["deliveries.auth.ApiKeyRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"api_key": API_THROTTLE_RATE},
    "EXCEPTION_HANDLER": "deliveries.api.exception_handler",
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Javi API",
    "VERSION": "1.0.0",
    "DESCRIPTION": (
        "Public REST API for shops to drive the delivery flow "
        "(create → ready → start → delivered) and notify customers.\n\n"
        "**Authentication:** pass your key as `Authorization: Bearer javi_live_…` "
        "or `X-Api-Key: javi_live_…`. Everything is scoped to the key's shop.\n\n"
        "**Statuses** are industry-standard (AfterShip-style): `pending`, "
        "`ready_for_pickup`, `out_for_delivery`, `delivered`. The internal Javi "
        "code is also returned as `status_internal`.\n\n"
        "**Errors** use a single envelope: `{\"error\": {\"code\", \"message\"}}`."
    ),
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "COMPONENT_SPLIT_REQUEST": True,
}
