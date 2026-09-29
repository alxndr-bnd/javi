from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def is_https_url(url: str) -> bool:
    return urlsplit(url or "").scheme.lower() == "https"


def validate_https_url(url: str) -> None:
    """Webhook URLs must be https (SERBITO-362, JAVI-10): the body carries customer data."""
    if url and not is_https_url(url):
        raise ValidationError(_("The webhook URL must start with https://."), code="https")
