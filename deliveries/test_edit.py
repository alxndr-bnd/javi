"""SERBITO-356 (4): a delivery can be edited until it is delivered.

Before: a wrong address or phone meant delete and recreate, and "We could not recognize the
address — please check it later" led nowhere. Editing never sends a message; resending stays
the explicit "Resend" with its own limits.
"""

import logging
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from common.testing import parse_html
from common.timewindow import BELGRADE, rating_send_time
from deliveries.models import Delivery, Shop, TrackingToken
from integrations.testing import FakeMessagingProvider
from notifications.models import Notification
from tasks.testing import RecordingTaskScheduler

pytestmark = pytest.mark.django_db

MAPS_OK = "integrations.testing.FakeMapsProvider"
MAPS_FAIL = "integrations.testing.FailingMapsProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"
SCHED = "tasks.testing.RecordingTaskScheduler"
SECRET = "t0ken"


@pytest.fixture(autouse=True)
def _clean():
    FakeMessagingProvider.sent = []
    RecordingTaskScheduler.scheduled = []


def _shop(email="edit@shop.rs"):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    return Shop.objects.create(
        owner=user, name="Pekara", origin_lat=44.8, origin_lng=20.45, sending_verified=True
    )


def _delivery(shop, status=Delivery.Status.CREATED, **extra):
    return Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Stara 1, Beograd",
        dest_lat=44.81,
        dest_lng=20.46,
        status=status,
        **extra,
    )


def _form(**overrides):
    data = {
        "recipient_phone": "+381641234567",
        "recipient_name": "Ana",
        "dest_address": "Stara 1, Beograd",
        "description": "",
        "recipient_language": "sr-latn",
    }
    data.update(overrides)
    return data


def _url(delivery):
    return f"/app/dostava/{delivery.pk}/izmeni/"


def test_edit_form_prefilled(client):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    root = parse_html(client.get(_url(delivery)).content.decode())
    assert root.find("input", {"name": "recipient_name"}).attrs["value"] == "Ana"
    assert root.find("input", {"name": "dest_address"}).attrs["value"] == "Stara 1, Beograd"
    assert not root.find_all("input", {"name": "eta_time"})  # no ETA before the start


@override_settings(MAPS_PROVIDER=MAPS_OK, MESSAGING_PROVIDER=MSG_OK)
def test_edit_name_phone_address_language_without_sending(client, caplog):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    with caplog.at_level(logging.INFO, logger="deliveries.services"):
        resp = client.post(
            _url(delivery),
            _form(
                recipient_name="Ana Anić",
                recipient_phone="065 765 4321",
                dest_address="Nova 2, Novi Sad",
                recipient_language="en",
            ),
        )
    assert resp.status_code == 302
    delivery.refresh_from_db()
    assert delivery.recipient_name == "Ana Anić"
    assert delivery.recipient_phone == "+381657654321"
    assert delivery.recipient_language == "en"
    assert delivery.dest_address != "Stara 1, Beograd" and delivery.dest_lat is not None
    assert FakeMessagingProvider.sent == []
    # audit: one structured event with the field names, no customer data
    (record,) = [r for r in caplog.records if getattr(r, "event", "") == "delivery.edited"]
    assert record.fields == [
        "dest_address",
        "recipient_language",
        "recipient_name",
        "recipient_phone",
    ]
    assert record.delivery_id == delivery.pk and record.shop_id == shop.pk
    assert "765" not in record.getMessage() and "Nova" not in record.getMessage()


@override_settings(MAPS_PROVIDER=MAPS_FAIL)
def test_unrecognized_address_is_kept_and_flagged(client):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    client.post(_url(delivery), _form(dest_address="Nepoznata bb"))
    delivery.refresh_from_db()
    assert delivery.dest_address == "Nepoznata bb" and delivery.dest_lat is None
    body = client.get("/app/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "Address not recognized." in body
    assert f'href="{_url(delivery)}"' in body


@override_settings(TASK_SCHEDULER=SCHED, MESSAGING_PROVIDER=MSG_OK)
def test_on_the_way_eta_can_move_and_rating_follows(client):
    shop = _shop()
    old_eta = timezone.now() + timedelta(minutes=30)
    delivery = _delivery(shop, Delivery.Status.ON_THE_WAY, eta_at=old_eta)
    client.force_login(shop.owner)
    new_local = (
        (timezone.now() + timedelta(days=1))
        .astimezone(BELGRADE)
        .replace(hour=11, minute=45, second=0, microsecond=0)
    )
    client.post(
        _url(delivery),
        _form(eta_date=str(new_local.date()), eta_time="11:45"),
    )
    delivery.refresh_from_db()
    assert delivery.eta_at == new_local and delivery.eta_source == "manual"
    assert RecordingTaskScheduler.scheduled == [(delivery.pk, rating_send_time(new_local))]
    assert FakeMessagingProvider.sent == []


@override_settings(TASKS_SECRET=SECRET, MESSAGING_PROVIDER=MSG_OK)
def test_rating_task_for_the_old_eta_waits_for_the_new_one(client):
    shop = _shop()
    delivery = _delivery(
        shop, Delivery.Status.ON_THE_WAY, eta_at=timezone.now() + timedelta(hours=3)
    )
    TrackingToken.objects.create(delivery=delivery)
    client.post(f"/tasks/send-rating/{delivery.id}/", HTTP_X_TASKS_SECRET=SECRET)
    assert not delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).exists()


def test_late_delivery_edit_keeps_past_eta_untouched(client):
    shop = _shop()
    past = (timezone.now() - timedelta(minutes=20)).replace(second=0, microsecond=0)
    delivery = _delivery(shop, Delivery.Status.ON_THE_WAY, eta_at=past)
    client.force_login(shop.owner)
    local = past.astimezone(BELGRADE)
    resp = client.post(
        _url(delivery),
        _form(recipient_name="Ana B", eta_date=str(local.date()), eta_time=local.strftime("%H:%M")),
    )
    assert resp.status_code == 302
    delivery.refresh_from_db()
    assert delivery.recipient_name == "Ana B" and delivery.eta_at == past


def test_moving_eta_into_the_past_is_refused(client):
    shop = _shop()
    delivery = _delivery(
        shop, Delivery.Status.ON_THE_WAY, eta_at=timezone.now() + timedelta(hours=1)
    )
    client.force_login(shop.owner)
    yesterday = timezone.now().astimezone(BELGRADE).date() - timedelta(days=1)
    resp = client.post(
        _url(delivery),
        _form(eta_date=str(yesterday), eta_time="10:00"),
        HTTP_ACCEPT_LANGUAGE="en",
    )
    assert resp.status_code == 200
    assert "already passed" in resp.content.decode()


def test_delivered_cannot_be_edited(client):
    shop = _shop()
    delivery = _delivery(shop, Delivery.Status.DELIVERED)
    client.force_login(shop.owner)
    assert client.get(_url(delivery)).status_code == 302
    client.post(_url(delivery), _form(recipient_name="X"))
    delivery.refresh_from_db()
    assert delivery.recipient_name == "Ana"
    assert f'href="{_url(delivery)}"' not in client.get("/app/").content.decode()


def test_other_shop_gets_404(client):
    delivery = _delivery(_shop())
    other = _shop("other@shop.rs")
    client.force_login(other.owner)
    assert client.get(_url(delivery)).status_code == 404
    assert client.post(_url(delivery), _form(recipient_name="X")).status_code == 404
