"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

from config.checks import assert_safe_to_serve

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
# Без SECRET_KEY / ALLOWED_HOSTS при DEBUG=False не стартуем (SERBITO-362, JAVI-11).
assert_safe_to_serve(settings)
