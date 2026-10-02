"""SERBITO-356 (J6): the first customer notification without detours.

Before: register → "New delivery" redirected to the store address → save → back → form →
"Mark ready" → "Delivery started" → ETA → "Confirm and notify". Now the store address can be
given at sign-up, and "Save and notify the customer now" goes from the form straight to the
ETA confirmation.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings

from common.testing import parse_html
from deliveries.models import Delivery, Shop
from integrations.testing import FakeMessagingProvider

pytestmark = pytest.mark.django_db

MAPS_OK = "integrations.testing.FakeMapsProvider"
MAPS_FAIL = "integrations.testing.FailingMapsProvider"
ROUTES_OK = "integrations.testing.FakeRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"

SIGNUP = {
    "email": "new@shop.rs",
    "store_name": "Cvećara Ruža",
    "password1": "Vrlo-Tajna-123",
    "password2": "Vrlo-Tajna-123",
}


@pytest.fixture(autouse=True)
def _clean():
    FakeMessagingProvider.sent = []
    cache.clear()
    yield
    cache.clear()


@override_settings(MAPS_PROVIDER=MAPS_OK)
def test_store_address_at_signup_skips_the_detour(client):
    resp = client.post("/accounts/register/", {**SIGNUP, "store_address": "Knez Mihailova 6"})
    assert resp.status_code == 302
    shop = Shop.objects.get()
    assert shop.origin_lat is not None
    assert client.get("/app/dostava/nova/").status_code == 200  # no redirect to "Store"


@override_settings(MAPS_PROVIDER=MAPS_FAIL)
def test_unrecognized_signup_address_still_registers(client):
    resp = client.post(
        "/accounts/register/", {**SIGNUP, "store_address": "???"}, HTTP_ACCEPT_LANGUAGE="en"
    )
    assert resp.status_code == 302
    assert Shop.objects.get().origin_lat is None
    body = client.get("/app/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "We could not recognize the store address" in body


def test_signup_without_address_still_works(client):
    assert client.post("/accounts/register/", SIGNUP).status_code == 302
    assert client.get("/app/dostava/nova/").status_code == 302  # address asked for later


def _shop_client(client):
    user = get_user_model().objects.create_user(email="o@shop.rs", password="pass12345")
    shop = Shop.objects.create(
        owner=user, name="Pekara", origin_lat=44.8, origin_lng=20.45, sending_verified=True
    )
    client.force_login(user)
    return shop


DELIVERY = {"recipient_phone": "064 123 4567", "recipient_name": "Ana", "dest_address": "Adr 1"}


@override_settings(MAPS_PROVIDER=MAPS_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_save_and_notify_now_goes_straight_to_the_eta_confirmation(client):
    shop = _shop_client(client)
    resp = client.post("/app/dostava/nova/", {**DELIVERY, "notify_now": "1"})
    assert resp.status_code == 200
    delivery = shop.deliveries.get()
    assert delivery.status == Delivery.Status.CREATED
    root = parse_html(resp.content.decode())
    form = root.find("form", {"action": f"/app/dostava/{delivery.pk}/start/"})
    eta = form.find("input", {"name": "eta_time"}).attrs["value"]
    day = form.find("input", {"name": "eta_date"}).attrs["value"]
    # one more click and the customer is notified
    client.post(f"/app/dostava/{delivery.pk}/start/", {"eta_time": eta, "eta_date": day})
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.ON_THE_WAY
    assert len(FakeMessagingProvider.sent) == 1


@override_settings(MAPS_PROVIDER=MAPS_OK)
def test_plain_save_keeps_the_old_flow(client):
    shop = _shop_client(client)
    resp = client.post("/app/dostava/nova/", DELIVERY)
    assert resp.status_code == 302
    assert shop.deliveries.get().status == Delivery.Status.NEW


def test_form_offers_both_buttons(client):
    _shop_client(client)
    root = parse_html(client.get("/app/dostava/nova/").content.decode())
    buttons = root.find("form").find_all("button")
    assert buttons[0].attrs.get("name") == "notify_now"  # Enter = the main action
    assert len(buttons) == 2
