"""Django settings for Javi (config project). Env-driven (12-factor)."""

import sys
from pathlib import Path

import environ
from django.utils.csp import CSP

from common.static_headers import add_landing_security_headers
from config.sentry import init_sentry

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    # Пусто по умолчанию (SERBITO-362, JAVI-11): без env сервер не отвечает на чужие Host,
    # а config/wsgi.py вообще не стартует. При DEBUG Django сам пускает localhost.
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
# Локально читаем .env, если он есть (в проде переменные приходят из окружения).
environ.Env.read_env(BASE_DIR / ".env")

# Sentry — только при заданном SENTRY_DSN (прод: Secret Manager, см. config/sentry.py).
# Под pytest не поднимаем никогда, даже если DSN случайно есть в окружении/.env
# (как в serbito: "pytest" in sys.modules надёжен и в xdist-воркерах).
if "pytest" not in sys.modules:
    init_sentry()

# Дефолт — только для локалки/тестов/сборки образа; веб-сервер без DEBUG с ним не стартует
# (config/checks.py из config/wsgi.py — fail closed, SERBITO-362, JAVI-11).
INSECURE_SECRET_KEY = "django-insecure-dev-only-change-me"
SECRET_KEY = env("SECRET_KEY", default=INSECURE_SECRET_KEY)
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Админка не на /admin/ (SERBITO-362, JAVI-2): путь из env (в проде — секрет). Без него
# админка в проде не подключена вовсе; локально (DEBUG) — /admin/.
ADMIN_PATH = env("ADMIN_PATH", default="admin/" if DEBUG else "").strip("/")
ADMIN_PATH = f"{ADMIN_PATH}/" if ADMIN_PATH else ""

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
    # После WhiteNoise: лендинг сюда не доходит, всё, что рендерит Django, — noindex (SERBITO-303).
    "common.middleware.NoIndexMiddleware",
    # CSP (SERBITO-362, JAVI-12): политика — SECURE_CSP / SECURE_CSP_REPORT_ONLY ниже.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
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
                "django.template.context_processors.csp",  # {{ csp_nonce }} для <script>
                "django.template.context_processors.i18n",
                "common.i18n.language",  # html_lang (sr-Latn), lang_base (sr)
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "deliveries.context_processors.free_quota",
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

# Защита входа от перебора (SERBITO-362, JAVI-2; accounts/lockout.py): неудачные входы
# считаются по IP клиента и по аккаунту в окне LOGIN_LOCKOUT_MINUTES; на лимите вход
# (и в админку) отклоняется до проверки пароля.
AUTHENTICATION_BACKENDS = ["accounts.lockout.LockoutBackend"]
LOGIN_FAILURE_LIMIT_IP = env.int("LOGIN_FAILURE_LIMIT_IP", default=10)
LOGIN_FAILURE_LIMIT_ACCOUNT = env.int("LOGIN_FAILURE_LIMIT_ACCOUNT", default=20)
LOGIN_LOCKOUT_MINUTES = env.int("LOGIN_LOCKOUT_MINUTES", default=15)

# IP клиента = запись X-Forwarded-For на TRUSTED_PROXY_HOPS-м месте справа (common/client_ip.py).
# 1 — только Google front end Cloud Run (javi.serbito.rs DNS-only); 2 — если добавится
# Cloudflare-прокси; 0 — без прокси (REMOTE_ADDR).
TRUSTED_PROXY_HOPS = env.int("TRUSTED_PROXY_HOPS", default=1)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# i18n / время
LANGUAGE_CODE = "en"  # дефолт — английский
# Сербский — латиницей: `sr-latn` (каталог locale/sr_Latn). С `sr` Django брал свой
# кириллический каталог, и ошибки форм шли кириллицей посреди латиницы (SERBITO-356).
# Старая кука `sr` и Accept-Language `sr`/`sr-RS` сводятся к `sr-latn` сами.
LANGUAGES = [("en", "English"), ("sr-latn", "Srpski")]
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
# Кабинет и API живут под /app/, /accounts/, ADMIN_PATH (их WhiteNoise пропускает в Django).
WHITENOISE_ROOT = BASE_DIR / "landing"
WHITENOISE_INDEX_FILE = True
# Лендинг не проходит через XFrameOptions/CSP-middleware: запрет фреймов ставит WhiteNoise
# (SERBITO-348, common/static_headers.py).
WHITENOISE_ADD_HEADERS_FUNCTION = add_landing_security_headers

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Логи — JSON-строка на stdout с `severity` (SERBITO-336, common/logging.py): Cloud Logging
# видит уровень записи, WARNING/ERROR фильтруются и алертятся. LOG_FORMAT=text — для локалки.
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_FORMAT = env("LOG_FORMAT", default="json")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "common.logging.JsonFormatter"},
        "text": {"format": "%(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "text" if LOG_FORMAT == "text" else "json",
        },
    },
    "root": {"handlers": ["stdout"], "level": LOG_LEVEL},
    # Без своих обработчиков (у Django по умолчанию — console при DEBUG): всё идёт в root.
    "loggers": {"django": {"level": LOG_LEVEL, "propagate": True}},
}

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

# Content Security Policy (SERBITO-362, JAVI-12) на всё, что рендерит Django (кабинет, вход,
# админка, /t/). Лендинг отдаёт WhiteNoise — туда не доходит.
# Всегда (enforce): без <object>, <base> и фреймов, формы — только на свой домен.
# Полная политика: скрипты — свои и с nonce (+ gtag), стили — свои + inline-атрибуты,
# GA — только свои домены. Пока report-only: gtag (Consent Mode) может ходить куда-то ещё;
# нарушения видно в консоли браузера. CSP_ENFORCE=True — включить её в полную силу.
_CSP_BASELINE = {
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
}
_GOOGLE_ANALYTICS = [
    "https://*.google-analytics.com",
    "https://*.analytics.google.com",
    "https://*.googletagmanager.com",
]
CSP_FULL_POLICY = {
    **_CSP_BASELINE,
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE, "https://www.googletagmanager.com"],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", *_GOOGLE_ANALYTICS],
    "connect-src": [CSP.SELF, *_GOOGLE_ANALYTICS],
    "font-src": [CSP.SELF],
}
CSP_ENFORCE = env.bool("CSP_ENFORCE", default=False)
SECURE_CSP = CSP_FULL_POLICY if CSP_ENFORCE else _CSP_BASELINE
SECURE_CSP_REPORT_ONLY = {} if CSP_ENFORCE else CSP_FULL_POLICY

# Учёт расхода квот free-tier (глобально, account-wide). Считаем свои вызовы провайдеров.
USAGE_METERING_ENABLED = env.bool("USAGE_METERING_ENABLED", default=True)
# Бесплатные лимиты. Maps — помесячный free tier (по умолч. 10000 вызовов/мес, общий бакет
# геокодинг+маршруты). Viber/SMS — пожизненный остаток триала; выставить реальные значения.
FREE_QUOTA_MAPS = env.int("FREE_QUOTA_MAPS", default=10000)
FREE_QUOTA_VIBER = env.int("FREE_QUOTA_VIBER", default=1000)
FREE_QUOTA_SMS = env.int("FREE_QUOTA_SMS", default=1000)
# Часовой пояс сброса месячных квот. Google Maps free tier обнуляется 1-го числа в полночь
# по Тихоокеанскому времени — выравниваем границу месяца под него (а не под UTC).
QUOTA_RESET_TZ = env("QUOTA_RESET_TZ", default="America/Los_Angeles")

# Лимиты исходящих Viber/SMS (SERBITO-345): открытая регистрация не должна давать
# безлимитный отправитель на любые номера. Проверяются ДО отправки (notifications/quotas.py).
# День/месяц — по Белграду (TIME_ZONE). Лимит 0 — отправка запрещена (не «безлимит»).
# Проверенный магазин (Shop.sending_verified) — обычные лимиты; индивидуальные — в админке.
SEND_LIMIT_SHOP_DAY = env.int("SEND_LIMIT_SHOP_DAY", default=50)
SEND_LIMIT_SHOP_MONTH = env.int("SEND_LIMIT_SHOP_MONTH", default=500)
# Новый (непроверенный) магазин — пробные лимиты и только сербские мобильные номера.
SEND_LIMIT_TRIAL_DAY = env.int("SEND_LIMIT_TRIAL_DAY", default=10)
SEND_LIMIT_TRIAL_MONTH = env.int("SEND_LIMIT_TRIAL_MONTH", default=30)
# Один номер за день по ВСЕМ магазинам (доставка = «в пути» + запрос оценки = 2 сообщения).
SEND_LIMIT_RECIPIENT_DAY = env.int("SEND_LIMIT_RECIPIENT_DAY", default=5)
# Переотправок одной доставки (каждая — новая отправка во всех лимитах выше).
SEND_LIMIT_RESENDS_PER_DELIVERY = env.int("SEND_LIMIT_RESENDS_PER_DELIVERY", default=3)
# Глобальный предохранитель на весь сервис за день; упор → logger.error (→ Sentry).
SEND_LIMIT_GLOBAL_DAY = env.int("SEND_LIMIT_GLOBAL_DAY", default=500)

# Пробный магазин (SERBITO-357): куда писать, чтобы проверили (показываем на «Prodavnica»).
SHOP_VERIFY_EMAIL = env("SHOP_VERIFY_EMAIL", default="alexander.bondarchuk@gmail.com")
# Регистраций с одного IP клиента за сутки (UTC); сверх — 429 на форме регистрации.
SIGNUP_LIMIT_PER_IP_DAY = env.int("SIGNUP_LIMIT_PER_IP_DAY", default=3)
# Активных (не отозванных) API-ключей у магазина.
API_KEYS_PER_SHOP = env.int("API_KEYS_PER_SHOP", default=5)

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

# Интеграции — мессенджинг (Infobip Viber/SMS).
# Прод-путь: ChainedMessagingProvider из одно-канальных провайдеров (MESSAGING_CHAIN).
# MESSAGING_PROVIDER (одиночный, dotted-path) — обратная совместимость / свап вендора в тестах;
# если задан, имеет приоритет над цепочкой.
MESSAGING_PROVIDER = env("MESSAGING_PROVIDER", default="")
# Упорядоченный список dotted-path одно-канальных провайдеров (fallback-цепочка).
# Пусто → фабрика берёт дефолт из INFOBIP_CHANNEL/INFOBIP_SMS_FALLBACK (= сегодняшний Viber→SMS).
MESSAGING_CHAIN = env.list("MESSAGING_CHAIN", default=[])
INFOBIP_BASE_URL = env("INFOBIP_BASE_URL", default="https://m9dw19.api.infobip.com")
INFOBIP_API_KEY = env("INFOBIP_API_KEY", default="")
INFOBIP_SENDER = env("INFOBIP_SENDER", default="IBSelfServe")
INFOBIP_CHANNEL = env("INFOBIP_CHANNEL", default="viber")  # viber | sms
INFOBIP_SMS_FALLBACK = env.bool("INFOBIP_SMS_FALLBACK", default=True)  # Viber→SMS при сбое
INFOBIP_WEBHOOK_SECRET = env("INFOBIP_WEBHOOK_SECRET", default="")  # защита вебхука receipts
# Infobip не шлёт заголовки на URL отчёта из сообщения — секрет туда идёт как ?secret=.
# False — URL в сообщения не кладём: отчёты по подписке Infobip (Basic auth, пароль = секрет;
# вебхук принимает и X-Webhook-Secret). SERBITO-362, JAVI-3.
INFOBIP_WEBHOOK_SECRET_IN_URL = env.bool("INFOBIP_WEBHOOK_SECRET_IN_URL", default=True)

# WhatsApp (Infobip) — вставляется в цепочку между Viber и SMS, когда WHATSAPP_ENABLED.
# Off by default: business-initiated WhatsApp требует Meta business verification +
# одобренный Utility-шаблон. Пока выключено — прод-цепочка остаётся ровно Viber→SMS.
WHATSAPP_ENABLED = env.bool("WHATSAPP_ENABLED", default=False)
WHATSAPP_SENDER = env("WHATSAPP_SENDER", default="")  # WhatsApp-номер отправителя
WHATSAPP_TEMPLATE_NAME = env("WHATSAPP_TEMPLATE_NAME", default="")  # имя Utility-шаблона
WHATSAPP_TEMPLATE_LANG = env("WHATSAPP_TEMPLATE_LANG", default="en")  # язык шаблона

# Telegram — opt-in-only side channel (бот не пишет первым; см. integrations/telegram.py).
# Выключен по умолчанию: при TELEGRAM_ENABLED цепочка ставит Telegram первым (для opted-in).
TELEGRAM_ENABLED = env.bool("TELEGRAM_ENABLED", default=False)
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
# Секрет в заголовке X-Telegram-Bot-Api-Secret-Token (защита вебхука бота).
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", default="")

# Отложенные задачи (Cloud Tasks). Локально — Noop; прод — CloudTasksScheduler.
TASK_SCHEDULER = env("TASK_SCHEDULER", default="tasks.scheduler.NoopTaskScheduler")
TASKS_SECRET = env("TASKS_SECRET", default="")  # защита колбэков задач (заголовок X-Tasks-Secret)
CLOUD_TASKS_PROJECT = env("CLOUD_TASKS_PROJECT", default="serbito")
CLOUD_TASKS_LOCATION = env("CLOUD_TASKS_LOCATION", default="europe-west1")
CLOUD_TASKS_QUEUE = env("CLOUD_TASKS_QUEUE", default="javi-rating")
CLOUD_TASKS_SERVICE_URL = env("CLOUD_TASKS_SERVICE_URL", default="https://javi.serbito.rs")

# P4: async-эскалация по delivery-receipt. «Принято провайдером» ≠ «доставлено» — если
# on_the_way не подтверждён доставкой за FALLBACK_ESCALATION_DELAY_MINUTES, Cloud Task шлёт
# следующим неиспробованным каналом цепочки. Off by default (как и WhatsApp/Telegram).
FALLBACK_ESCALATION_ENABLED = env.bool("FALLBACK_ESCALATION_ENABLED", default=False)
FALLBACK_ESCALATION_DELAY_MINUTES = env.int("FALLBACK_ESCALATION_DELAY_MINUTES", default=10)

# Публичный базовый URL для ссылок в сообщениях (трекинг).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="https://javi.serbito.rs")

# Запас времени к расчётному ETA (минуты): now + время в пути + запас.
ETA_BUFFER_MINUTES = env.int("ETA_BUFFER_MINUTES", default=10)

# Публичная страница статуса: срок жизни ссылки и rate limit (FR-20/NFR-6).
TRACKING_TOKEN_TTL_DAYS = env.int("TRACKING_TOKEN_TTL_DAYS", default=7)
TRACKING_RATE_LIMIT = env.int("TRACKING_RATE_LIMIT", default=60)  # запросов/мин на IP, все /t/

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
        '**Errors** use a single envelope: `{"error": {"code", "message"}}`.'
    ),
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "COMPONENT_SPLIT_REQUEST": True,
}
