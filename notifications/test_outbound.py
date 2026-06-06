"""Исходящие вебхуки мерчанту: HMAC-подпись, постановка в очередь, отказоустойчивость."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from deliveries.models import Delivery, Shop
from notifications.outbound import compute_signature, notify_merchant
from tasks.testing import RecordingWebhookScheduler

pytestmark = pytest.mark.django_db

SCHED = "tasks.testing.RecordingWebhookScheduler"


def _shop(*, webhook_url="https://merchant.example/hook", webhook_secret="whsec"):
    user = get_user_model().objects.create_user(email="o@shop.rs", password="pass12345")
    return Shop.objects.create(
        owner=user,
        name="Shop O",
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
    )


# --- HMAC подпись ---


def test_compute_signature_matches_hmac_sha256():
    body = b'{"event":"x"}'
    sig = compute_signature("topsecret", body)
    expected = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


def test_compute_signature_empty_secret_still_signs():
    # Пустой секрет — подпись всё равно вычисляется (детерминированно).
    sig = compute_signature("", b"{}")
    expected = hmac.new(b"", b"{}", hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


# --- notify_merchant постановка в очередь ---


@override_settings(TASK_SCHEDULER=SCHED)
def test_notify_merchant_enqueues_signed_webhook():
    RecordingWebhookScheduler.webhooks = []
    shop = _shop(webhook_secret="whsec")
    notify_merchant(shop, "delivery.started", {"id": 7, "status": "on_the_way"})

    assert len(RecordingWebhookScheduler.webhooks) == 1
    wh = RecordingWebhookScheduler.webhooks[0]
    assert wh["url"] == shop.webhook_url

    raw = wh["body"]
    parsed = json.loads(raw)
    assert parsed["event"] == "delivery.started"
    assert parsed["data"] == {"id": 7, "status": "on_the_way"}
    assert "sent_at" in parsed

    # Подпись валидна над СЫРЫМ телом.
    expected = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    assert wh["headers"]["Javi-Signature"] == f"sha256={expected}"
    assert wh["headers"]["Content-Type"] == "application/json"


@override_settings(TASK_SCHEDULER=SCHED)
def test_notify_merchant_noop_when_no_url():
    RecordingWebhookScheduler.webhooks = []
    shop = _shop(webhook_url="")
    notify_merchant(shop, "delivery.started", {"id": 1})
    assert RecordingWebhookScheduler.webhooks == []


@override_settings(TASK_SCHEDULER="tasks.testing.FailingTaskScheduler")
def test_notify_merchant_swallows_scheduler_failure():
    # Сбой постановки задачи НЕ должен пробрасываться наверх (не рвём основной поток).
    shop = _shop()
    notify_merchant(shop, "delivery.started", {"id": 1})  # не должно бросить


@override_settings(TASK_SCHEDULER=SCHED)
def test_recipient_phone_can_be_verified_by_merchant():
    """Сценарий мерчанта: пересчитать подпись по полученному телу и сверить заголовок."""
    RecordingWebhookScheduler.webhooks = []
    shop = _shop(webhook_secret="abc123")
    delivery = Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_address="adr"
    )
    notify_merchant(
        shop,
        "delivery.delivered",
        {"id": delivery.id, "status": "delivered", "recipient": {"name": "Ana"}},
    )
    wh = RecordingWebhookScheduler.webhooks[0]
    # Верификация на стороне мерчанта.
    recomputed = compute_signature(shop.webhook_secret, wh["body"])
    assert hmac.compare_digest(recomputed, wh["headers"]["Javi-Signature"])
