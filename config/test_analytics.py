"""SERBITO-306: GA4 never sees a customer's tracking token; the privacy page tells the truth.

- /t/<token>/ pages (live, expired, unknown, unsubscribe) load no GA: the token in their URL
  opens the customer's delivery status, so it must not reach Google as page_location. They also
  send only the origin as referrer, so a GA page opened from them cannot read the token either.
- The landing, the privacy page and the shop dashboard keep GA.
- landing/privacy.html lists GA4 (cookies _ga/_ga_*, Google as processor, where it runs) and
  Cloudflare Web Analytics in sr/en/ru and no longer claims "no tracking cookies".
"""

import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from deliveries.models import Delivery, Shop, TrackingToken

pytestmark = pytest.mark.django_db

PRIVACY = Path(__file__).resolve().parent.parent / "landing" / "privacy.html"
GA_ID = "G-KHME7DK2K0"
GA_MARKERS = ["googletagmanager.com", "gtag(", GA_ID, "google-analytics.com"]


def _body(resp):
    if resp.streaming:
        return b"".join(resp.streaming_content).decode()
    return resp.content.decode()


def _assert_no_ga(body):
    for marker in GA_MARKERS:
        assert marker not in body, f"GA marker {marker!r} on a tracking page"


def _assert_ga(body):
    assert f"googletagmanager.com/gtag/js?id={GA_ID}" in body
    assert f"gtag('config', '{GA_ID}'" in body


@pytest.fixture
def shop(db):
    user = get_user_model().objects.create_user(email="ga@shop.rs", password="pass12345")
    return Shop.objects.create(owner=user, name="Pizza Napoli")


@pytest.fixture
def token(shop):
    cache.clear()  # the tracking page rate limiter lives in the cache
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Adresa 1, Beograd",
        dest_city="Beograd",
        status=Delivery.Status.ON_THE_WAY,
    )
    yield TrackingToken.objects.create(delivery=delivery)
    cache.clear()


# --- tracking pages: no GA ---


def test_tracking_page_has_no_ga(client, token):
    resp = client.get(f"/t/{token.token}/")
    assert resp.status_code == 200
    _assert_no_ga(_body(resp))


def test_expired_tracking_page_has_no_ga(client, token):
    token.expires_at = timezone.now() - timedelta(days=1)
    token.save(update_fields=["expires_at"])
    resp = client.get(f"/t/{token.token}/")
    assert resp.status_code == 410
    _assert_no_ga(_body(resp))


@pytest.mark.parametrize("path", ["/t/unknown-token/", "/t/unknown-token/odjava/"])
def test_unknown_tracking_token_has_no_ga(client, token, path):
    resp = client.get(path)
    assert resp.status_code == 404
    _assert_no_ga(_body(resp))


def test_unsubscribe_page_has_no_ga(client, token):
    resp = client.get(f"/t/{token.token}/odjava/")
    assert resp.status_code == 200
    _assert_no_ga(_body(resp))


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.referrer = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "referrer":
            self.referrer = attrs.get("content")
        for attr in ("href", "action", "src"):
            if tag != "link" and attrs.get(attr):
                self.urls.append(attrs[attr])


def test_tracking_page_leaks_token_nowhere(client, token):
    """Every link and form stays under /t/<token>/; anything else sees only the origin."""
    parser = _Links()
    parser.feed(_body(client.get(f"/t/{token.token}/")))
    assert parser.referrer == "strict-origin"
    assert parser.urls, "expected the tracking page to have forms/links"
    for url in parser.urls:
        assert url.startswith(f"/t/{token.token}/"), url


# --- GA stays where it belongs ---


def test_landing_has_ga(client):
    resp = client.get("/")
    assert resp.status_code == 200
    _assert_ga(_body(resp))


def test_privacy_page_has_ga(client):
    resp = client.get("/privacy.html")
    assert resp.status_code == 200
    _assert_ga(_body(resp))


def test_dashboard_has_ga(client, shop):
    client.force_login(shop.owner)
    resp = client.get("/app/")
    assert resp.status_code == 200
    _assert_ga(_body(resp))


# --- privacy page tells the truth ---


def _section(lang):
    html = PRIVACY.read_text(encoding="utf-8")
    match = re.search(rf'<section id="{lang}">(.*?)</section>', html, re.S)
    assert match, f"no #{lang} section in privacy.html"
    return match.group(1)


@pytest.mark.parametrize("lang", ["sr", "en", "ru"])
def test_privacy_lists_google_analytics(lang):
    section = _section(lang)
    assert "Google Analytics" in section
    assert "_ga</strong>" in section and "_ga_*" in section
    assert "Google Ireland" in section  # Google named as processor
    assert "/t/" in section  # says where GA does not run
    assert "Cloudflare Web Analytics" in section
    assert "mailto:alexander.bondarchuk@gmail.com" in section


@pytest.mark.parametrize(
    "claim",
    [
        "Ne koristimo kolačiće za praćenje",
        "We use no tracking cookies",
        "не используем отслеживающие cookies",
    ],
)
def test_privacy_no_longer_claims_no_tracking_cookies(claim):
    assert claim.lower() not in PRIVACY.read_text(encoding="utf-8").lower()
