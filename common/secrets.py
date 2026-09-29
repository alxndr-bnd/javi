"""Shared-secret checks for machine callbacks (SERBITO-362, JAVI-3).

Cloud Tasks callbacks and Infobip webhooks prove themselves with a shared secret. It used to
travel as ?secret=… in the URL, so it landed in request logs, task definitions, Infobip's logs
and Sentry's query_string, and was compared with `==` (timing leak).

Now the secret is read from a header (or from HTTP Basic auth — what an Infobip subscription
can send) and compared in constant time. `?secret=` is still accepted so tasks queued before
this release and Infobip's per-message report URL keep working (INFOBIP_WEBHOOK_SECRET_IN_URL);
each use is logged, and after the secrets are rotated nothing should use it.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging

logger = logging.getLogger(__name__)


def secret_matches(provided: str | None, expected: str) -> bool:
    """Constant-time compare; an empty expected secret never matches (fail closed)."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def _basic_auth_password(request) -> str | None:
    scheme, _, encoded = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return decoded.partition(":")[2] or None


def request_has_secret(request, expected: str, *, header: str) -> bool:
    """True if the request carries `expected` in `header`, Basic auth or legacy ?secret=."""
    if secret_matches(request.headers.get(header), expected):
        return True
    if secret_matches(_basic_auth_password(request), expected):
        return True
    if secret_matches(request.GET.get("secret"), expected):
        logger.info("Shared secret accepted from the query string (legacy): %s", request.path)
        return True
    return False
