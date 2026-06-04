import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from deliveries.models import Delivery, Shop
from notifications.models import Notification

pytestmark = pytest.mark.django_db

SECRET = "s3cret"
URL = "/webhooks/infobip/reports/"


def _notification(message_id="m-1", status=Notification.Status.SENT):
    user = get_user_model().objects.create_user(email="w@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Shop W")
    delivery = Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_address="adr"
    )
    return Notification.objects.create(
        delivery=delivery,
        kind=Notification.Kind.ON_THE_WAY,
        provider_message_id=message_id,
        status=status,
    )


def _post(client, payload):
    return client.post(
        f"{URL}?secret={SECRET}", data=json.dumps(payload), content_type="application/json"
    )


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_delivered_report_updates_status(client):
    n = _notification()
    resp = _post(client, {"results": [{"messageId": "m-1", "status": {"groupName": "DELIVERED"}}]})
    assert resp.status_code == 200
    n.refresh_from_db()
    assert n.status == Notification.Status.DELIVERED


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_seen_report_sets_read(client):
    n = _notification(status=Notification.Status.DELIVERED)
    _post(client, {"results": [{"messageId": "m-1", "seen": True}]})
    n.refresh_from_db()
    assert n.status == Notification.Status.READ


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_undeliverable_sets_failed(client):
    n = _notification()
    _post(client, {"results": [{"messageId": "m-1", "status": {"groupName": "UNDELIVERABLE"}}]})
    n.refresh_from_db()
    assert n.status == Notification.Status.FAILED


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_no_downgrade_read_to_delivered(client):
    n = _notification(status=Notification.Status.READ)
    _post(client, {"results": [{"messageId": "m-1", "status": {"groupName": "DELIVERED"}}]})
    n.refresh_from_db()
    assert n.status == Notification.Status.READ  # не понижаем


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_unknown_message_id_ignored(client):
    _notification()
    resp = _post(client, {"results": [{"messageId": "x", "status": {"groupName": "DELIVERED"}}]})
    assert resp.status_code == 200  # тихо, без ошибки


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_wrong_secret_forbidden(client):
    _notification()
    resp = client.post(
        f"{URL}?secret=wrong",
        data=json.dumps({"results": []}),
        content_type="application/json",
    )
    assert resp.status_code == 403
