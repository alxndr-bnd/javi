"""The real client IP behind Cloud Run (SERBITO-362, JAVI-8).

On Cloud Run REMOTE_ADDR is the Google front end, the same for every visitor, so a per-IP
limit keyed on it is one shared bucket. The front end appends the address it saw to
X-Forwarded-For; everything to the left of it came from the client and can be forged. So the
client IP is the entry TRUSTED_PROXY_HOPS places from the right: 1 = only the Google front end
(javi.serbito.rs is DNS-only today), 2 = behind Cloudflare too, 0 = no proxy (use REMOTE_ADDR).
"""

from __future__ import annotations

import ipaddress

from django.conf import settings


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    """Client IP for rate limits and lockouts; never the leftmost (client-controlled) XFF."""
    hops = settings.TRUSTED_PROXY_HOPS
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if hops > 0 and forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(parts) >= hops:
            ip = _valid_ip(parts[-hops])
            if ip:
                return ip
    return _valid_ip(request.META.get("REMOTE_ADDR", "")) or "unknown"
