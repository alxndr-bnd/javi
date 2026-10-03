"""Security headers for the static landing (SERBITO-348).

WhiteNoise serves the landing (``/``, ``/privacy.html``) before any Django middleware that
sets framing headers runs, so those pages could be framed (clickjacking of the lead form).
SecurityMiddleware sits before WhiteNoise and already adds HSTS, nosniff and Referrer-Policy.

Only framing is set here: a fuller CSP for the landing (scripts, form targets) needs its own
report-only period, and a wrong ``form-action`` would break the lead form.
"""

LANDING_HTML_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def add_landing_security_headers(headers, path, url):
    """WHITENOISE_ADD_HEADERS_FUNCTION: forbid framing of every HTML file WhiteNoise serves."""
    if path.endswith(".html"):
        for name, value in LANDING_HTML_HEADERS.items():
            headers[name] = value
