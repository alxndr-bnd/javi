"""The real client IP behind Cloud Run and Cloudflare (SERBITO-362/JAVI-8, SERBITO-420).

Trust model (the same as gtd ``client_ip``, SERBITO-346):

1. Every proxy *appends* to ``X-Forwarded-For`` the address that connected to it; everything
   to the left was written by the client and can be forged. The leftmost entry is never read.
2. XFF is read only when the socket peer (``REMOTE_ADDR``) is a proxy: loopback, private or
   link-local (Cloud Run's front end connects from 169.254.x.x), or in ``TRUSTED_PROXIES``.
   A public peer is the client itself, and its XFF is ignored.
3. Walk XFF from the right and skip our own proxies: loopback, link-local, Google front end
   ranges and ``TRUSTED_PROXIES``. The first other address is the *edge peer*.
4. If the edge peer is a Cloudflare address (``cloudflare_ips.txt``), the request really came
   through the Cloudflare proxy, and the client is ``CF-Connecting-IP`` (Cloudflare sets it and
   overwrites any value the client sent). From any other edge peer ``CF-Connecting-IP`` is
   ignored: there it is forged as easily as XFF.

So the same code is right for javi.serbito.rs DNS-only and proxied, and for ``*.run.app``.
Callers: sign-in lockout (accounts.lockout), signup limit (accounts.views), /t/ rate limit
(tracking.views).
"""

from __future__ import annotations

import ipaddress
from functools import cache
from pathlib import Path

from django.conf import settings

CLOUDFLARE_IPS_FILE = Path(__file__).with_name("cloudflare_ips.txt")
GOOGLE_FRONT_END = ("35.191.0.0/16", "130.211.0.0/22")


def _nets(cidrs) -> tuple:
    return tuple(ipaddress.ip_network(c.strip(), strict=False) for c in cidrs if c.strip())


@cache
def cloudflare_networks() -> tuple:
    lines = CLOUDFLARE_IPS_FILE.read_text().splitlines()
    return _nets(line for line in lines if not line.lstrip().startswith("#"))


@cache
def _proxy_networks(trusted: tuple[str, ...]) -> tuple[tuple, tuple]:
    """(TRUSTED_PROXIES, everything skipped in XFF) as parsed networks."""
    own = _nets(trusted)
    return own, _nets(GOOGLE_FRONT_END) + own


def _ip(value: str | None):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _within(ip, nets) -> bool:
    return any(ip.version == net.version and ip in net for net in nets)


def is_cloudflare_ip(value: str | None) -> bool:
    ip = _ip(value)
    return ip is not None and _within(ip, cloudflare_networks())


def client_ip(request) -> str:
    """Client IP for rate limits and lockouts (see the module docstring); "unknown" if none."""
    trusted, skip = _proxy_networks(tuple(settings.TRUSTED_PROXIES))
    ip = _ip(request.META.get("REMOTE_ADDR"))
    if ip is None:
        return "unknown"
    if ip.is_private or ip.is_loopback or ip.is_link_local or _within(ip, trusted):
        for hop in reversed(request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")):
            hop_ip = _ip(hop)
            if hop_ip is None:
                break
            ip = hop_ip
            if not (hop_ip.is_loopback or hop_ip.is_link_local or _within(hop_ip, skip)):
                break
    if _within(ip, cloudflare_networks()):
        ip = _ip(request.META.get("HTTP_CF_CONNECTING_IP")) or ip
    return str(ip)
