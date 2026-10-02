"""Error pages (SERBITO-356)."""

from django.conf import settings
from django.shortcuts import render
from django.utils import translation
from django.utils.translation.trans_real import parse_accept_lang_header

from common.i18n import SERBIAN, supported_language


def _visitor_language(request) -> str:
    """The visitor's language: their language cookie, then the browser, else Serbian.

    Not LocaleMiddleware's guess: that falls back to the app's default (English), while the
    people who land on a broken link are mostly customers in Serbia opening an SMS.
    """
    candidates = [request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)]
    header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    candidates += [code for code, _q in parse_accept_lang_header(header) if code != "*"]
    for code in candidates:
        language = supported_language(code, default=None)
        if language:
            return language
    return SERBIAN


def not_found(request, exception=None):
    """Friendly 404 in the visitor's language instead of Django's bare English "Not Found".

    A mistyped or cut-off tracking link (/t/…) gets its own text: what probably happened and
    to ask the shop. The page loads no analytics: the URL may hold (part of) a tracking token.
    """
    language = _visitor_language(request)
    with translation.override(language):
        response = render(
            request, "404.html", {"tracking": request.path.startswith("/t/")}, status=404
        )
        response.headers["Content-Language"] = language
    return response
