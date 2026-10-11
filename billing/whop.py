"""Whop API client and webhook signature (SERBITO-593). Same patterns as serbito (docs/197).

* ``api_request`` is the one path to the Whop API: ``/api/v1``, JSON, a timeout, a pinned
  ``Api-Version-Date``, no secrets in logs. ``WHOP_SANDBOX`` selects ``sandbox-api.whop.com``.
  Under pytest a real call is refused at send time: only a mocked ``requests.request`` passes.
* ``shop_token`` is an HMAC of the shop id. It goes into the checkout ``metadata``. Whop copies
  the metadata to the payment, so the webhook brings it back. The token proves the payment is
  ours, and not a serbito payment on the same Whop account.
* ``verify_signature`` is Standard Webhooks: ``webhook-id``, ``webhook-timestamp`` and
  ``webhook-signature: v1,<base64 HMAC-SHA256>`` over ``id.timestamp.body``, ±5 minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

API_BASE = "https://api.whop.com/api/v1"
SANDBOX_API_BASE = "https://sandbox-api.whop.com/api/v1"
WEB_BASE = "https://whop.com"
SANDBOX_WEB_BASE = "https://sandbox.whop.com"
#: The API version every request pins (the same pin as serbito).
DEFAULT_API_VERSION = "2026-10-06"
#: Standard Webhooks: a signed timestamp further than this from now is refused.
SIGNATURE_TOLERANCE = timedelta(minutes=5)


class WhopError(Exception):
    """A Whop API call failed (network, HTTP status or configuration)."""

    def __init__(self, message: str = "", *, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class WhopBlocked(WhopError):
    """A real call to the Whop API was refused because it runs under pytest."""


# ---- configuration -----------------------------------------------------------------------


def _setting(name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def api_key() -> str:
    return _setting("WHOP_API_KEY")


def webhook_secret() -> str:
    return _setting("WHOP_WEBHOOK_SECRET")


def company_id() -> str:
    """Our Whop business id (``biz_...``): the same business as serbito."""
    return _setting("WHOP_COMPANY_ID")


def product_id() -> str:
    """The javi product (``prod_...``). Payments of other products are not ours."""
    return _setting("WHOP_PRODUCT_ID")


def is_sandbox() -> bool:
    return bool(getattr(settings, "WHOP_SANDBOX", True))


def api_base() -> str:
    return SANDBOX_API_BASE if is_sandbox() else API_BASE


def web_base() -> str:
    return SANDBOX_WEB_BASE if is_sandbox() else WEB_BASE


def api_version() -> str:
    return _setting("WHOP_API_VERSION") or DEFAULT_API_VERSION


def is_configured() -> bool:
    return bool(api_key() and company_id() and product_id())


def missing_settings() -> list[str]:
    names = ("WHOP_API_KEY", "WHOP_WEBHOOK_SECRET", "WHOP_COMPANY_ID", "WHOP_PRODUCT_ID")
    return [name for name in names if not _setting(name)]


def is_whop_url(value) -> str:
    """``value`` as a Whop URL, or "" when it is not ``https`` on whop.com or a subdomain.

    A relative path gets the Whop web origin. We never redirect a shop anywhere else.
    """
    url = str(value or "").strip()
    if url.startswith("/") and not url.startswith("//"):
        url = web_base() + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "whop.com" or host.endswith(".whop.com")):
        return ""
    return url


# ---- HTTP --------------------------------------------------------------------------------


def _send_blocked() -> bool:
    """True under pytest with the real HTTP layer: a forgotten mock fails loudly."""
    if getattr(requests.request, "__module__", None) != "requests.api":
        return False
    return "pytest" in sys.modules


def _error_detail(response) -> str:
    """The ``error.message`` of a Whop error body, short. Never the request or the key."""
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return ""
    return str(error.get("message") or error.get("code") or "")[:300]


def api_request(
    method: str,
    path: str,
    *,
    payload=None,
    params=None,
    idempotency_key: str = "",
    timeout: float | None = None,
) -> dict:
    """Call the Whop API and return the decoded JSON body. Raises WhopError."""
    key = api_key()
    if not key:
        raise WhopError("WHOP_API_KEY is not set")
    if _send_blocked():
        raise WhopBlocked(f"Whop API call blocked under tests: {method} {path}")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "Api-Version-Date": api_version(),
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if timeout is None:
        timeout = float(getattr(settings, "WHOP_API_TIMEOUT", 10) or 10)
    try:
        response = requests.request(
            method,
            f"{api_base()}{path}",
            headers=headers,
            json=payload,
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # The exception text can hold the URL, never the header with the key.
        raise WhopError(f"Whop {method} {path} failed: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise WhopError(
            f"Whop {method} {path} returned HTTP {response.status_code}: {_error_detail(response)}",
            status_code=response.status_code,
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise WhopError(f"Whop {method} {path} returned no JSON") from exc
    if not isinstance(body, dict):
        raise WhopError(f"Whop {method} {path} returned an unexpected body")
    return body


def get_membership(membership_id: str, *, timeout: float | None = None) -> dict:
    return api_request("GET", f"/memberships/{membership_id}", timeout=timeout)


def get_payment(payment_id: str, *, timeout: float | None = None) -> dict:
    return api_request("GET", f"/payments/{payment_id}", timeout=timeout)


# ---- shop token and webhook signature ----------------------------------------------------


def _token_key() -> bytes:
    return f"javi-whop-shop-token:{settings.SECRET_KEY}".encode()


def shop_token(shop_id) -> str:
    """32 hex chars of HMAC-SHA256(SECRET_KEY, shop id). Stable per shop."""
    return hmac.new(_token_key(), f"shop-{shop_id}".encode(), hashlib.sha256).hexdigest()[:32]


def token_is_valid(shop_id, token) -> bool:
    if not token or not isinstance(token, str):
        return False
    return hmac.compare_digest(shop_token(shop_id), token)


def _signing_keys(secret: str) -> list[bytes]:
    """HMAC keys to try: ``whsec_<base64>`` decoded, or Whop's ``ws_…`` string as given.

    Same rule as serbito: the UTF-8 bytes of the whole ``ws_`` secret, and without the
    prefix as a fallback. Both come from our secret only.
    """
    secret = secret.strip()
    if secret.startswith("whsec_"):
        try:
            return [base64.b64decode(secret.removeprefix("whsec_"), validate=True)]
        except ValueError:
            return []
    keys = [secret.encode()]
    if secret.startswith("ws_"):
        keys.append(secret.removeprefix("ws_").encode())
    return keys


def verify_signature(body: bytes, headers, secret: str, *, now: datetime | None = None) -> bool:
    """Standard Webhooks check of a Whop delivery. Constant time, ±5 minutes."""
    if not secret:
        return False
    msg_id = str(headers.get("webhook-id") or "")
    stamp = str(headers.get("webhook-timestamp") or "")
    signatures = str(headers.get("webhook-signature") or "")
    if not (msg_id and stamp and signatures):
        return False
    try:
        sent_at = int(stamp)
    except ValueError:
        return False
    now_ts = now.timestamp() if now is not None else time.time()
    if abs(now_ts - sent_at) > SIGNATURE_TOLERANCE.total_seconds():
        return False
    signed = f"{msg_id}.{stamp}.".encode() + body
    given = []
    for entry in signatures.split():
        version, _, sig = entry.partition(",")
        if version == "v1" and sig:
            given.append(sig.encode())
    if not given:
        return False
    ok = False
    for key in _signing_keys(secret):
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
        for candidate in given:
            ok = hmac.compare_digest(expected, candidate) or ok  # no early exit
    return ok


# ---- payload readers (native and stable shapes, as in serbito) ---------------------------


def money(value) -> Decimal | None:
    """A Whop amount as a Decimal in major units: a money object or a bare number."""
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def nested_id(data: dict, name: str) -> str:
    value = data.get(name)
    return str(value.get("id") or "") if isinstance(value, dict) else ""


def account_of(data: dict) -> str:
    """Native ``account_id``, or the stable ``company_id`` / ``company.id``."""
    return str(data.get("account_id") or data.get("company_id") or nested_id(data, "company"))


def product_of(data: dict) -> str:
    return str(data.get("product_id") or nested_id(data, "product"))


def membership_of(payment: dict) -> str:
    return str(payment.get("membership_id") or nested_id(payment, "membership"))


def metadata_of(data: dict) -> dict:
    metadata = data.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def when(value) -> datetime | None:
    """A Whop time: ISO 8601 (the docs' examples) or a Unix timestamp (the docs' text)."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    text = str(value)
    if text.isdigit():
        return when(int(text))
    return parse_datetime(text.replace("Z", "+00:00"))
