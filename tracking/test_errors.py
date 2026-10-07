"""SERBITO-356 (2a/2b): customers who open a broken or expired link get a page that helps.

2a: a mistyped tracking link used to show Django's bare English "Not Found", even to a Serbian
browser. 2b: the expired page said only "Link has expired." with no shop name or contact.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from common.testing import parse_html
from deliveries.models import Delivery, Shop, TrackingToken

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _token(*, phone="", language="sr-latn", expired=False):
    user = get_user_model().objects.create_user(email="e@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pekara Mika", contact_phone=phone)
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Tajna 5",
        recipient_language=language,
        status=Delivery.Status.ON_THE_WAY,
        eta_at=timezone.now() + timedelta(minutes=30),
    )
    expires = timezone.now() + (timedelta(hours=-1) if expired else timedelta(days=1))
    return TrackingToken.objects.create(delivery=delivery, expires_at=expires)


@pytest.mark.parametrize(
    ("accept", "lang", "heading"),
    [
        ("sr-Latn-RS,sr;q=0.9", "sr-Latn", "Ne možemo da pronađemo ovu dostavu."),
        ("sr", "sr-Latn", "Ne možemo da pronađemo ovu dostavu."),
        ("en-US,en;q=0.9", "en", "We can't find this delivery."),
        ("de-DE", "sr-Latn", "Ne možemo da pronađemo ovu dostavu."),  # unsupported → Serbian
        ("", "sr-Latn", "Ne možemo da pronađemo ovu dostavu."),  # no preference → Serbian
    ],
)
def test_bad_tracking_link_friendly_localized_404(client, accept, lang, heading):
    resp = client.get("/t/no-such-token/", HTTP_ACCEPT_LANGUAGE=accept)
    assert resp.status_code == 404
    body = resp.content.decode()
    root = parse_html(body)
    assert root.find("html").attrs["lang"] == lang
    assert root.find("main").find("h1").text() == heading
    assert "Not Found" not in body
    assert "googletagmanager" not in body  # the URL may hold part of a token: no analytics


def test_bad_tracking_link_respects_language_cookie(client, settings):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    resp = client.get("/t/no-such-token/", HTTP_ACCEPT_LANGUAGE="sr")
    assert "We can't find this delivery." in resp.content.decode()


def test_other_unknown_page_gets_generic_friendly_404(client):
    resp = client.get("/app/no-such-page/", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.status_code == 404
    root = parse_html(resp.content.decode())
    assert root.find("h1").text() == "Page not found."
    assert root.find("a", {"href": "/"})


def test_expired_link_shows_shop_name_and_contact_in_customer_language(client):
    token = _token(phone="+381111234567", expired=True)
    resp = client.get(f"/t/{token.token}/", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.status_code == 410
    body = resp.content.decode()
    root = parse_html(body)
    assert root.find("html").attrs["lang"] == "sr-Latn"
    assert "Pekara Mika" in root.find("main").text()
    assert root.find("h1").text() == "Ovaj link za praćenje je istekao."
    tel = root.find("a", {"href": "tel:+381111234567"})
    assert tel.text() == "+381 11 1234567"


def test_expired_link_without_contact_still_names_the_shop(client):
    token = _token(expired=True, language="en")
    root = parse_html(client.get(f"/t/{token.token}/").content.decode())
    assert "Pekara Mika" in root.find("main").text()
    assert "contact the shop" in root.find("main").text()
    assert not root.find_all("a", {"href": "tel:"})


@pytest.mark.parametrize("path", ["oceni/", "primljeno/", "odjava/"])
def test_expired_actions_show_the_same_page(client, path):
    token = _token(phone="+381111234567", expired=True)
    resp = client.post(f"/t/{token.token}/{path}", {"value": "5"})
    assert resp.status_code == 410
    assert "Pekara Mika" in resp.content.decode()


def test_live_status_page_shows_shop_contact(client):
    token = _token(phone="+381641112223")
    root = parse_html(client.get(f"/t/{token.token}/").content.decode())
    assert root.find("a", {"href": "tel:+381641112223"})


def test_profile_saves_contact_phone(client):
    user = get_user_model().objects.create_user(email="p@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pekara")
    client.force_login(user)
    data = {"name": "Pekara", "address": "Adr 1", "contact_phone": "011 123 4567"}
    from django.test import override_settings

    with override_settings(MAPS_PROVIDER="integrations.testing.FakeMapsProvider"):
        client.post("/app/prodavnica/", data)
    shop.refresh_from_db()
    assert shop.contact_phone == "+381111234567"

    resp = client.post("/app/prodavnica/", {**data, "contact_phone": "12"})
    assert resp.status_code == 200
    shop.refresh_from_db()
    assert shop.contact_phone == "+381111234567"
