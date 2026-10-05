"""WhiteNoise for the static landing, with two SEO fixes (SERBITO-462).

- Redirects are permanent. WhiteNoise answers ``/index.html`` (and ``/en/index.html``,
  ``/ru/index.html``, ``/en``, ``/ru``) with a 302 to the directory URL. A 301 tells search
  engines that the directory URL is the one to index.
- ``/consent.js`` is cached for a long time as immutable. Every page loads it as
  ``/consent.js?v=<content hash>`` (``config/test_consent.py`` keeps the hash current), so a
  change to the file is a new URL for browsers and Cloudflare.
"""

from __future__ import annotations

from http import HTTPStatus

from whitenoise.middleware import WhiteNoiseMiddleware
from whitenoise.responders import Response

# Landing files that every page loads with a content hash in the query string.
VERSIONED_URLS = frozenset({"/consent.js"})


class _PermanentRedirect:
    def __init__(self, response: Response):
        self.response = response

    def get_response(self, method, request_headers):
        return self.response


class LandingWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    def redirect(self, from_url, to_url):
        found = super().redirect(from_url, to_url).response
        return _PermanentRedirect(Response(HTTPStatus.MOVED_PERMANENTLY, found.headers, None))

    def immutable_file_test(self, path, url):
        return url in VERSIONED_URLS or super().immutable_file_test(path, url)
