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
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="adr",
        dest_lat=44.81,
        dest_lng=20.46,
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


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK, TASK_SCHEDULER=SCHED)
def test_no_webhook_to_a_plain_http_url():
    """JAVI-10: a pre-existing http:// URL gets nothing (the body holds customer data)."""
    RecordingWebhookScheduler.webhooks = []
    delivery = _delivery(_shop(webhook_url="http://merchant.example/hook"))
    start_delivery(delivery)
    assert RecordingWebhookScheduler.webhooks == []


S = Notification.Status


@override_settings(
    INFOBIP_WEBHOOK_SECRET=INFOBIP_SECRET, TASK_SCHEDULER=SCHED, MESSAGING_PROVIDER=MSG_OK
)
@pytest.mark.parametrize(
    ("before", "result", "after", "event"),
    [
        (S.SENT, {"status": {"groupName": "DELIVERED"}}, S.DELIVERED, "notification.delivered"),
        (S.DELIVERED, {"seen": True}, S.READ, "notification.read"),
        (S.SENT, {"status": {"groupName": "UNDELIVERABLE"}}, S.FAILED, "notification.failed"),
        # READ → DELIVERED не понижается: статус не меняется — и не эмитим
        (S.READ, {"status": {"groupName": "DELIVERED"}}, S.READ, None),
    ],
)
def test_infobip_report_sets_status_and_notifies_merchant(client, before, result, after, event):
    """Отчёт Infobip → статус уведомления и вебхук мерчанту (только если статус сменился)."""
    RecordingWebhookScheduler.webhooks = []
    delivery = _delivery(_shop())
    TrackingToken.objects.create(delivery=delivery)
    notif = Notification.objects.create(
        delivery=delivery,
        kind=Notification.Kind.ON_THE_WAY,
        provider_message_id="m-1",
        status=before,
    )
    resp = client.post(
        f"/webhooks/infobip/reports/?secret={INFOBIP_SECRET}",
        data=json.dumps({"results": [{"messageId": "m-1", **result}]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    notif.refresh_from_db()
    assert notif.status == after
    assert _events() == ([event] if event else [])
    if event:
        data = _by_event(event)["data"]
        assert (data["id"], data["notification_status"]) == (delivery.id, after)


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
