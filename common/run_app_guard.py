"""Close the Cloudflare bypass through ``*.run.app`` (SERBITO-430, as serbito SERBITO-348 PLT-4).

javi.serbito.rs is behind the Cloudflare proxy (SERBITO-428). Cloud Run also answers on its own
``javi-….run.app`` host, and a request there skips the Cloudflare WAF, rules and Bot Fight Mode.

On a run.app host this middleware serves only the deploy tag host ``candidate---…run.app``: the
deploy smoke-checks it and checks its security headers, then removes the tag. Any other request
gets a 301 to the same path on ``PUBLIC_BASE_URL`` (GET/HEAD) or a 403 (other methods).

No machine path needs run.app: Cloud Tasks callbacks use ``CLOUD_TASKS_SERVICE_URL`` and Infobip
webhooks use ``PUBLIC_BASE_URL`` (both javi.serbito.rs). The guard is off when ``PUBLIC_BASE_URL``
is itself a run.app URL: the redirect would point back at the same host. Hosts that are not
run.app are not affected. ``.run.app`` stays in ``ALLOWED_HOSTS``: the tag host needs it.

The middleware sits right after SecurityMiddleware and before WhiteNoise, so the static landing
is guarded too, and the 301/403 still get HSTS and nosniff.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponseForbidden, HttpResponsePermanentRedirect

RUN_APP_SUFFIX = ".run.app"
CANDIDATE_TAG_PREFIX = "candidate---"


def host_name(value: str) -> str:
    """A Host value in lower case, without the port and a trailing dot."""
    host = value.strip().lower()
    if host.startswith("["):  # IPv6 literal: never a run.app name
        return host
    return host.split(":", 1)[0].rstrip(".")


def is_run_app_host(host: str) -> bool:
    return host.endswith(RUN_APP_SUFFIX)


def public_origin() -> str:
    """scheme://host of PUBLIC_BASE_URL, or "" when it is itself a run.app URL (guard off)."""
    url = urlsplit(settings.PUBLIC_BASE_URL)
    if not url.scheme or not url.netloc or is_run_app_host(host_name(url.netloc)):
        return ""
    return f"{url.scheme}://{url.netloc}"


class RunAppHostGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = host_name(request.META.get("HTTP_HOST") or "")
        if not is_run_app_host(host) or host.startswith(CANDIDATE_TAG_PREFIX):
            return self.get_response(request)
        origin = public_origin()
        if not origin:
            return self.get_response(request)
        if request.method in ("GET", "HEAD"):
            return HttpResponsePermanentRedirect(origin + request.get_full_path())
        return HttpResponseForbidden(f"Use {origin}")
