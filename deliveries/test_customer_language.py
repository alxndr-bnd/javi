"""SERBITO-356 (3a/3b): customer messages and pages use the customer's language, not the shop's.

The language is stored on the delivery (default Serbian, Latin script) and set from the form
or the API. The shop's UI language and the language a Cloud Tasks callback runs in don't matter.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import translation

from common.phone import normalize_phone
from deliveries.models import ApiKey, Delivery, Shop, TrackingToken
from deliveries.services import create_delivery, resend_on_the_way, start_delivery
from integrations.testing import FakeMessagingProvider

pytestmark = pytest.mark.django_db

MAPS_OK = "integrations.testing.FakeMapsProvider"
ROUTES_OK = "integrations.testing.FakeRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"
SECRET = "t0ken"

SR_ON_THE_WAY = 'Vaša porudžbina iz "Pekara Mika" je u dostavi.'
EN_ON_THE_WAY = 'Your order from "Pekara Mika" is on its way.'
SR_RATING = 'Kako je prošla dostava iz "Pekara Mika"?'
EN_RATING = 'How did the delivery from "Pekara Mika" go?'


@pytest.fixture(autouse=True)
def _clean():
    FakeMessagingProvider.sent = []
    cache.clear()
    yield
    cache.clear()


def _shop():
    user = get_user_model().objects.create_user(email="lang@shop.rs", password="pass12345")
    return Shop.objects.create(
        owner=user, name="Pekara Mika", origin_address="Origin", origin_lat=44.8,
        origin_lng=20.45, sending_verified=True,
    )


def _delivery(shop, language=None):
    extra = {"recipient_language": language} if language else {}
    return Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567",
        dest_address="adr", dest_lat=44.81, dest_lng=20.46, **extra,
    )


def test_default_customer_language_is_serbian():
    assert _delivery(_shop()).recipient_language == "sr-latn"


@override_settings(MAPS_PROVIDER=MAPS_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_english_cabinet_still_sends_serbian_sms_by_default(client):
    """The shop works in English; the customer gets Serbian unless the shop says otherwise."""
    shop = _shop()
    client.force_login(shop.owner)
    client.post(
        "/app/dostava/nova/",
        {"recipient_phone": "064 123 4567", "recipient_name": "Ana", "dest_address": "Adr 1"},
        HTTP_ACCEPT_LANGUAGE="en",
    )
    delivery = shop.deliveries.get()
    assert delivery.recipient_language == "sr-latn"
    with translation.override("en"):  # the shop's UI language while starting
        start_delivery(delivery)
    assert FakeMessagingProvider.sent[-1][1].startswith(SR_ON_THE_WAY)


@override_settings(MAPS_PROVIDER=MAPS_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_form_sets_english_and_serbian_cabinet_sends_english(client):
    shop = _shop()
    client.force_login(shop.owner)
    client.post(
        "/app/dostava/nova/",
        {
            "recipient_phone": "064 123 4567",
            "recipient_name": "Ana",
            "dest_address": "Adr 1",
            "recipient_language": "en",
        },
        HTTP_ACCEPT_LANGUAGE="sr",
    )
    delivery = shop.deliveries.get()
    assert delivery.recipient_language == "en"
    with translation.override("sr-latn"):
        start_delivery(delivery)
    assert FakeMessagingProvider.sent[-1][1].startswith(EN_ON_THE_WAY)


def test_form_offers_the_language_with_serbian_preselected(client):
    shop = _shop()
    client.force_login(shop.owner)
    body = client.get("/app/dostava/nova/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert 'name="recipient_language"' in body
    assert '<option value="sr-latn" selected>' in body


@override_settings(MAPS_PROVIDER=MAPS_OK)
def test_lookup_returns_the_customers_last_language(client):
    shop = _shop()
    with override_settings(MAPS_PROVIDER=MAPS_OK):
        create_delivery(
            shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"),
            dest_address="Adr", language="en",
        )
    client.force_login(shop.owner)
    data = client.get("/app/klijent/", {"phone": "064 123 4567"}).json()
    assert data["language"] == "en"


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_resend_uses_the_customers_language():
    delivery = _delivery(_shop(), language="en")
    with translation.override("sr-latn"):
        start_delivery(delivery)
        resend_on_the_way(delivery)
    assert [t[1].startswith(EN_ON_THE_WAY) for t in FakeMessagingProvider.sent] == [True, True]


@pytest.mark.parametrize(("language", "text"), [("sr-latn", SR_RATING), ("en", EN_RATING)])
@override_settings(MESSAGING_PROVIDER=MSG_OK, TASKS_SECRET=SECRET)
def test_cloud_tasks_rating_sms_in_customer_language(client, language, text):
    """3b: the Cloud Tasks callback has no shop session; it used to send English always."""
    delivery = _delivery(_shop(), language=language)
    delivery.status = Delivery.Status.DELIVERED
    delivery.save(update_fields=["status"])
    TrackingToken.objects.create(delivery=delivery)
    resp = client.post(
        f"/tasks/send-rating/{delivery.id}/", HTTP_X_TASKS_SECRET=SECRET,
        HTTP_ACCEPT_LANGUAGE="en",
    )
    assert resp.status_code == 200
    assert FakeMessagingProvider.sent[-1][1].startswith(text)


def test_tracking_page_in_customer_language_whatever_the_browser(client):
    delivery = _delivery(_shop(), language="sr-latn")
    delivery.status = Delivery.Status.ON_THE_WAY
    delivery.save(update_fields=["status"])
    token = TrackingToken.objects.create(delivery=delivery)
    resp = client.get(f"/t/{token.token}/", HTTP_ACCEPT_LANGUAGE="en")
    body = resp.content.decode()
    assert "Vaša porudžbina je u dostavi" in body
    assert '<html lang="sr-Latn">' in body
    assert resp.headers["Content-Language"] == "sr-latn"


@override_settings(MAPS_PROVIDER=MAPS_OK)
@pytest.mark.parametrize(
    ("sent", "stored", "shown"),
    [
        (None, "sr-latn", "sr"),
        ("en", "en", "en"),
        ("sr", "sr-latn", "sr"),
        ("sr-Latn", "sr-latn", "sr"),
    ],
)
def test_api_create_takes_language(client, sent, stored, shown):
    shop = _shop()
    _obj, key = ApiKey.generate(shop)
    body = {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "Adr 1"}
    if sent:
        body["language"] = sent
    resp = client.post(
        "/api/v1/deliveries", data=json.dumps(body), content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )
    assert resp.status_code == 201
    assert resp.json()["language"] == shown
    assert shop.deliveries.get().recipient_language == stored


def test_api_rejects_unknown_language(client):
    shop = _shop()
    _obj, key = ApiKey.generate(shop)
    resp = client.post(
        "/api/v1/deliveries",
        data=json.dumps(
            {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "A",
             "language": "de"}
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_language"
    assert not shop.deliveries.exists()
