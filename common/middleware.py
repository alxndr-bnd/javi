"""Keep everything Django renders out of search engines (SERBITO-303).

The public site is the static landing (WhiteNoise serves landing/ at the root, sitemap.xml and
robots.txt included). Django renders only private or per-customer pages: the shop dashboard,
login/register, admin, API and its docs, webhooks, Cloud Tasks callbacks and the delivery
tracking pages /t/<token>/, which show a customer's delivery status to anyone holding the link.

This middleware sits right after WhiteNoiseMiddleware, so landing files never reach it and every
Django response gets `X-Robots-Tag: noindex, nofollow` — including 404/410/429 and redirects, which
a view decorator would miss (an unknown token raises Http404 outside the view). A view that ever
needs to be indexed can set its own X-Robots-Tag; it is not overwritten.
"""

ROBOTS_HEADER = "X-Robots-Tag"
NOINDEX = "noindex, nofollow"


class NoIndexMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault(ROBOTS_HEADER, NOINDEX)
        return response
