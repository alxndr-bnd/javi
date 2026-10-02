"""SERBITO-356 (J7): the ETA carries a date when it isn't today, and a past ETA is refused.

Before: the ETA was a bare "HH:MM" taken as today, a past time was accepted, and after it
passed the customer's page kept saying "arriving by 14:00".
"""

import json
from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from common.testing import parse_html
from common.timewindow import BELGRADE, format_eta_label
from deliveries.forms import ManualEtaForm
from deliveries.models import ApiKey, Delivery, Shop, TrackingToken
from integrations.testing import FakeMessagingProvider

pytestmark = pytest.mark.django_db

MSG_OK = "integrations.testing.FakeMessagingProvider"


@pytest.fixture(autouse=True)
def _clean():
    FakeMessagingProvider.sent = []
    cache.clear()
    yield
    cache.clear()


def _today():
    return timezone.now().astimezone(BELGRADE).date()


def _shop():
    user = get_user_model().objects.create_user(email="eta@shop.rs", password="pass12345")
    return Shop.objects.create(
        owner=user, name="Pekara", origin_lat=44.8, origin_lng=20.45, sending_verified=True
    )


def _delivery(shop, **extra):
    return Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_address="adr",
        status=Delivery.Status.CREATED, recipient_language="en", **extra,
    )


def test_label_is_time_today_and_date_otherwise():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=BELGRADE)
    assert format_eta_label(datetime(2026, 10, 2, 16, 30, tzinfo=BELGRADE), now) == "16:30"
    assert format_eta_label(datetime(2026, 10, 3, 0, 30, tzinfo=BELGRADE), now) == "03.10. 00:30"


def test_form_rejects_a_past_eta():
    yesterday = _today() - timedelta(days=1)
    form = ManualEtaForm({"eta_date": str(yesterday), "eta_time": "16:00"})
    assert not form.is_valid()
    assert "already passed" in str(form.non_field_errors())


def test_form_accepts_tomorrow_after_midnight():
    tomorrow = _today() + timedelta(days=1)
    form = ManualEtaForm({"eta_date": str(tomorrow), "eta_time": "00:30"})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["eta_at"] == datetime.combine(
        tomorrow, datetime.min.time().replace(minute=30), tzinfo=BELGRADE
    )


@override_settings(MESSAGING_PROVIDER=MSG_OK)
def test_start_view_refuses_past_eta_and_sends_nothing(client):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    yesterday = _today() - timedelta(days=1)
    resp = client.post(
        f"/app/dostava/{delivery.pk}/start/",
        {"eta_date": str(yesterday), "eta_time": "16:00"},
        HTTP_ACCEPT_LANGUAGE="en",
    )
    assert resp.status_code == 200
    assert "already passed" in resp.content.decode()
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.CREATED
    assert FakeMessagingProvider.sent == []


@override_settings(MESSAGING_PROVIDER=MSG_OK)
def test_eta_tomorrow_shows_the_date_in_sms_card_and_tracking(client):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    tomorrow = _today() + timedelta(days=1)
    client.post(
        f"/app/dostava/{delivery.pk}/start/", {"eta_date": str(tomorrow), "eta_time": "09:15"}
    )
    label = tomorrow.strftime("%d.%m.") + " 09:15"
    assert f"by {label}" in FakeMessagingProvider.sent[-1][1]
    assert label in client.get("/app/").content.decode()
    token = TrackingToken.objects.get(delivery=delivery)
    assert label in client.get(f"/t/{token.token}/").content.decode()


def test_confirm_screen_has_a_date_field(client):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    root = parse_html(client.post(f"/app/dostava/{delivery.pk}/start/").content.decode())
    date_input = root.find("input", {"name": "eta_date"})
    assert date_input.attrs["type"] == "date"
    assert date_input.attrs["value"] == str(_today())


def test_tracking_page_says_running_late_after_eta(client):
    delivery = _delivery(_shop(), eta_at=timezone.now() - timedelta(minutes=20))
    delivery.status = Delivery.Status.ON_THE_WAY
    delivery.save(update_fields=["status"])
    token = TrackingToken.objects.create(delivery=delivery)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "Running a little late" in body
    assert "Arriving approximately by" not in body


def _api_start(client, eta):
    shop = _shop()
    _obj, key = ApiKey.generate(shop)
    delivery = _delivery(shop)
    return client.post(
        f"/api/v1/deliveries/{delivery.pk}/start",
        data=json.dumps({"eta": eta}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )


@override_settings(MESSAGING_PROVIDER=MSG_OK)
def test_api_refuses_past_eta(client):
    resp = _api_start(client, "00:00")  # midnight today has always passed
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_eta"
    assert FakeMessagingProvider.sent == []


@override_settings(MESSAGING_PROVIDER=MSG_OK)
def test_api_accepts_iso_eta_tomorrow(client):
    tomorrow = _today() + timedelta(days=1)
    resp = _api_start(client, f"{tomorrow.isoformat()}T00:30")
    assert resp.status_code == 200, resp.json()
    assert resp.json()["eta"] == "00:30"
