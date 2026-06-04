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
LANGUAGE_CODE = "sr-latn"
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

# Публичный базовый URL для ссылок в сообщениях (трекинг).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="https://javi.serbito.rs")

# Публичная страница статуса: срок жизни ссылки и rate limit (FR-20/NFR-6).
TRACKING_TOKEN_TTL_DAYS = env.int("TRACKING_TOKEN_TTL_DAYS", default=7)
TRACKING_RATE_LIMIT = env.int("TRACKING_RATE_LIMIT", default=60)  # запросов/мин на IP
