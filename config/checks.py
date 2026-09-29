"""Fail closed on unsafe production settings (SERBITO-362, JAVI-11).

Without SECRET_KEY the app would sign sessions with the public dev key, and ALLOWED_HOSTS="*"
accepts any Host header. settings.py keeps dev defaults so tests, `manage.py check` in CI and
`collectstatic` in the image build run without secrets; the web server (config/wsgi.py) calls
this first and refuses to start with them when DEBUG is off.
"""

from django.core.exceptions import ImproperlyConfigured


def assert_safe_to_serve(settings) -> None:
    if settings.DEBUG:
        return
    problems = []
    if not settings.SECRET_KEY or settings.SECRET_KEY == settings.INSECURE_SECRET_KEY:
        problems.append("SECRET_KEY is not set")
    if not settings.ALLOWED_HOSTS or "*" in settings.ALLOWED_HOSTS:
        problems.append("ALLOWED_HOSTS must list the site's hosts (not empty, no '*')")
    if problems:
        raise ImproperlyConfigured("Refusing to serve with DEBUG off: " + "; ".join(problems))
