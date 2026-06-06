"""Эмиссия исходящих событий мерчанту на ключевых переходах флоу доставки."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from deliveries.models import Delivery, Shop, TrackingToken
from deliveries.services import start_delivery
from notifications.models import Notification
from tasks.testing import RecordingWebhookScheduler

pytestmark = pytest.mark.django_db

ROUTES_OK = "integrations.testing.FakeRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"
SCHED = "tasks.testing.RecordingWebhookScheduler"
INFOBIP_SECRET = "s3cret"


def _shop(
    *, webhook_url="https://merchant.example/hook", webhook_secret="whsec", email="e@shop.rs"
):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    return Shop.objects.create(
        owner=user,
        name="Shop E",
        origin_lat=44.8,
        origin_lng=20.45,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
    )


def _delivery(shop):
    return Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567",
        dest_address="adr", dest_lat=44.81, dest_lng=20.46,
    )


def _events():
    return [json.loads(wh["body"])["event"] for wh in RecordingWebhookScheduler.webhooks]


def _by_event(event):
    for wh in RecordingWebhookScheduler.webhooks:
        body = json.loads(wh["body"])
        if body["event"] == event:
            return body
    return None


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK, TASK_SCHEDULER=SCHED)
def test_delivery_started_emitted():
    RecordingWebhookScheduler.webhooks = []
    delivery = _delivery(_shop())
    start_delivery(delivery)
    body = _by_event("delivery.started")
    assert body is not None
    data = body["data"]
    assert data["id"] == delivery.id
    assert data["status"] == Delivery.Status.ON_THE_WAY
    assert data["recipient"]["phone"] == "+381641234567"
    assert data["tracking_url"]


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK, TASK_SCHEDULER=SCHED)
def test_no_webhook_when_url_empty():
    RecordingWebhookScheduler.webhooks = []
    delivery = _delivery(_shop(webhook_url=""))
    start_delivery(delivery)
    assert RecordingWebhookScheduler.webhooks == []


@override_settings(
    INFOBIP_WEBHOOK_SECRET=INFOBIP_SECRET, TASK_SCHEDULER=SCHED, MESSAGING_PROVIDER=MSG_OK
)
def test_notification_delivered_emitted(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    notif = Notification.objects.create(
        delivery=delivery, kind=Notification.Kind.ON_THE_WAY,
        provider_message_id="m-1", status=Notification.Status.SENT,
    )
    client.post(
        f"/webhooks/infobip/reports/?secret={INFOBIP_SECRET}",
        data=json.dumps({"results": [{"messageId": "m-1", "status": {"groupName": "DELIVERED"}}]}),
        content_type="application/json",
    )
    body = _by_event("notification.delivered")
    assert body is not None
    assert body["data"]["id"] == delivery.id
    assert body["data"]["notification_status"] == Notification.Status.DELIVERED
    notif.refresh_from_db()
    assert notif.status == Notification.Status.DELIVERED


@override_settings(
    INFOBIP_WEBHOOK_SECRET=INFOBIP_SECRET, TASK_SCHEDULER=SCHED, MESSAGING_PROVIDER=MSG_OK
)
def test_notification_read_emitted(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    Notification.objects.create(
        delivery=delivery, kind=Notification.Kind.ON_THE_WAY,
        provider_message_id="m-2", status=Notification.Status.DELIVERED,
    )
    client.post(
        f"/webhooks/infobip/reports/?secret={INFOBIP_SECRET}",
        data=json.dumps({"results": [{"messageId": "m-2", "seen": True}]}),
        content_type="application/json",
    )
    assert "notification.read" in _events()


@override_settings(
    INFOBIP_WEBHOOK_SECRET=INFOBIP_SECRET, TASK_SCHEDULER=SCHED, MESSAGING_PROVIDER=MSG_OK
)
def test_notification_failed_emitted(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    Notification.objects.create(
        delivery=delivery, kind=Notification.Kind.ON_THE_WAY,
        provider_message_id="m-3", status=Notification.Status.SENT,
    )
    client.post(
        f"/webhooks/infobip/reports/?secret={INFOBIP_SECRET}",
        data=json.dumps(
            {"results": [{"messageId": "m-3", "status": {"groupName": "UNDELIVERABLE"}}]}
        ),
        content_type="application/json",
    )
    assert "notification.failed" in _events()


@override_settings(
    INFOBIP_WEBHOOK_SECRET=INFOBIP_SECRET, TASK_SCHEDULER=SCHED, MESSAGING_PROVIDER=MSG_OK
)
def test_no_emit_when_status_unchanged(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    delivery = _delivery(shop)
    Notification.objects.create(
        delivery=delivery, kind=Notification.Kind.ON_THE_WAY,
        provider_message_id="m-4", status=Notification.Status.READ,
    )
    # READ → DELIVERED не понижается, статус не меняется → не эмитим.
    client.post(
        f"/webhooks/infobip/reports/?secret={INFOBIP_SECRET}",
        data=json.dumps({"results": [{"messageId": "m-4", "status": {"groupName": "DELIVERED"}}]}),
        content_type="application/json",
    )
    assert _events() == []


@override_settings(TASK_SCHEDULER=SCHED)
def test_delivery_delivered_emitted_on_mark_delivered(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    user = shop.owner
    delivery = _delivery(shop)
    client.force_login(user)
    client.post(reverse("deliveries:mark_delivered", args=[delivery.id]))
    body = _by_event("delivery.delivered")
    assert body is not None
    assert body["data"]["id"] == delivery.id
    assert body["data"]["status"] == Delivery.Status.DELIVERED


@override_settings(TASK_SCHEDULER=SCHED)
def test_delivery_delivered_emitted_on_public_mark_received(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    delivery = _delivery(shop)
    delivery.status = Delivery.Status.ON_THE_WAY
    delivery.save(update_fields=["status"])
    token = TrackingToken.objects.create(delivery=delivery)
    client.post(reverse("tracking:mark_received", args=[token.token]))
    assert "delivery.delivered" in _events()


@override_settings(TASK_SCHEDULER=SCHED)
def test_rating_created_emitted(client):
    RecordingWebhookScheduler.webhooks = []
    shop = _shop()
    delivery = _delivery(shop)
    delivery.status = Delivery.Status.DELIVERED
    delivery.save(update_fields=["status"])
    token = TrackingToken.objects.create(delivery=delivery)
    client.post(reverse("tracking:rate", args=[token.token]), {"value": "5"})
    body = _by_event("rating.created")
    assert body is not None
    assert body["data"]["id"] == delivery.id
    assert body["data"]["rating"] == 5
