"""Sentry error monitoring (mirrors serbito's settings, env-gated).

Инициализируется ТОЛЬКО при заданном SENTRY_DSN (в проде — Secret Manager
`javi-sentry-dsn` через --set-secrets в deploy.yaml). Локально и в тестах DSN нет →
SDK не поднимается, событий нет. SENTRY_RELEASE ставит deploy.yaml из тега
(`javi@X.Y.Z`); без него release не передаём (иначе SDK подставит git SHA).
"""

import os
from collections.abc import Mapping

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


def init_sentry(environ: Mapping[str, str] = os.environ) -> bool:
    """Поднять Sentry, если задан SENTRY_DSN. Возвращает True, если инициализировали."""
    dsn = environ.get("SENTRY_DSN") or None
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        release=environ.get("SENTRY_RELEASE") or None,
        # Cloud Run выставляет K_SERVICE в контейнере — это и есть прод.
        environment="production" if environ.get("K_SERVICE") else "development",
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        # PII (IP, cookies, user) не шлём: в данных магазинов телефоны/адреса клиентов.
        send_default_pii=False,
    )
    return True
