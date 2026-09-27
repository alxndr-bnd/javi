"""Sentry error monitoring (mirrors serbito's settings, env-gated).

Инициализируется ТОЛЬКО при заданном SENTRY_DSN (в проде — Secret Manager
`javi-sentry-dsn` через --set-secrets в deploy.yaml). Локально и в тестах DSN нет →
SDK не поднимается, событий нет. SENTRY_RELEASE ставит deploy.yaml из тега
(`javi@X.Y.Z`); без него release не передаём (иначе SDK подставит git SHA).
"""

import os
import re
from collections.abc import Mapping
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

# SERBITO-314: a /t/<token>/ URL opens a customer's delivery status, so the token must not
# reach Sentry. send_default_pii=False keeps the path, so we rewrite it to /t/:token/.
# "/t/" counts only at a path start: string start, after a quote/space/"="/"(" etc. (reprs,
# log lines, query values) or right after scheme://host[:port].
_TRACKING_URL = re.compile(
    r"(?P<prefix>^|[\s'\"(<\[=,]|[a-z][a-z0-9+.-]*://[^/\s'\"<>]+)"
    r"/t/(?P<token>[^/?#\s'\"<>]+)",
    re.IGNORECASE,
)
TOKEN_PLACEHOLDER = ":token"
# Route placeholders (the Django integration names transactions "/t/{token}/") are not tokens.
_NOT_TOKENS = {TOKEN_PLACEHOLDER, "{token}"}
# Real tokens are secrets.token_urlsafe(24) = 32 chars. A found token is also scrubbed as a bare
# string (TrackingToken's repr in frame vars); shorter junk is scrubbed only inside URLs, so a
# short 404 path like /t/x/ never rewrites unrelated text.
_MIN_BARE_TOKEN_LEN = 16


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _rewrite(value: Any, bare_tokens: set[str]) -> Any:
    if isinstance(value, str):
        value = _TRACKING_URL.sub(rf"\g<prefix>/t/{TOKEN_PLACEHOLDER}", value)
        for token in bare_tokens:
            value = value.replace(token, TOKEN_PLACEHOLDER)
        return value
    if isinstance(value, dict):
        return {key: _rewrite(item, bare_tokens) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_rewrite(item, bare_tokens) for item in value]
    return value


def scrub_tracking_tokens(event: dict, hint: dict | None = None) -> dict:
    """before_send / before_send_transaction: replace tracking tokens with ":token".

    Walks the whole (already serialized) event, so request.url, the Referer header, the
    transaction name, breadcrumbs, spans, log messages and frame-variable reprs are covered.
    """
    bare_tokens = {
        match["token"]
        for text in _strings(event)
        for match in _TRACKING_URL.finditer(text)
        if match["token"] not in _NOT_TOKENS and len(match["token"]) >= _MIN_BARE_TOKEN_LEN
    }
    return _rewrite(event, bare_tokens)


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
        before_send=scrub_tracking_tokens,
        before_send_transaction=scrub_tracking_tokens,
    )
    return True
