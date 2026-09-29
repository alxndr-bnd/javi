"""Keep credentials and customer data out of log lines and Sentry (SERBITO-362, JAVI-5).

requests puts the full URL into its exception text ("... for url: https://maps.googleapis.com/
...?address=<customer address>&key=<API key>", "... url: /bot<token>/sendMessage"), and a
logged exception reaches Cloud Logging and Sentry. `describe_request_error` is what gets logged
instead; `redact` is the safety net for any text (also used by config/sentry.py).
"""

from __future__ import annotations

import re

import requests

FILTERED = "[Filtered]"

# Query parameters that carry secrets: ?secret=, &key=, api_key=, token=, …
_SECRET_PARAM = re.compile(
    r"(?i)(?P<name>\b(?:secret|key|api[_-]?key|token|access_token|password|passwd|signature"
    r"|sig|auth)=)(?P<value>[^&\s'\"#<>]+)"
)
# Telegram Bot API: the token is part of the path (/bot123456:ABC-DEF/).
_BOT_TOKEN = re.compile(r"(?i)/bot\d+:[\w-]+")


def redact(text: str) -> str:
    """Mask secret query values and Telegram bot tokens in any text."""
    text = _SECRET_PARAM.sub(rf"\g<name>{FILTERED}", text)
    return _BOT_TOKEN.sub(f"/bot{FILTERED}", text)


def describe_request_error(exc: BaseException) -> str:
    """A loggable summary of a requests/JSON error: type and HTTP status, never the URL."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    name = type(exc).__name__
    if isinstance(exc, requests.HTTPError) and status is not None:
        return f"{name}: HTTP {status}"
    if isinstance(exc, requests.RequestException):
        return name  # ConnectionError/Timeout text repeats the URL with its query
    return redact(f"{name}: {exc}")
