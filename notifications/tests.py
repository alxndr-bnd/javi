import base64
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


# --- Story 3.2: отписка ---

OPTOUT_URL = "/webhooks/infobip/optout/"


def test_opt_out_idempotent():
    from notifications.models import OptOut
    from notifications.services import is_opted_out, opt_out

    opt_out("+381641234567")
    opt_out("+381641234567")
    assert OptOut.objects.count() == 1
    assert is_opted_out("+381641234567") is True
    assert is_opted_out("+381600000000") is False


@override_settings(MESSAGING_PROVIDER="integrations.testing.FakeMessagingProvider")
def test_rating_request_skipped_for_opted_out():
    """AC#3: отписанному запрос оценки не шлётся, Notification не создаётся."""
    from deliveries.models import TrackingToken
    from deliveries.services import send_rating_request
    from notifications.services import opt_out

    n = _notification()
    delivery = n.delivery
    n.delete()  # уберём фоновый on_the_way, оставим чистую доставку
    TrackingToken.objects.create(delivery=delivery)
    opt_out(delivery.recipient_phone)
    assert send_rating_request(delivery) is None
    assert delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).count() == 0


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_optout_webhook_blocklists_number(client):
    from notifications.models import OptOut

    resp = client.post(
        f"{OPTOUT_URL}?secret={SECRET}",
        data=json.dumps({"results": [{"to": "381641234567"}]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert OptOut.objects.filter(phone="+381641234567").exists()


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_optout_webhook_wrong_secret_403(client):
    resp = client.post(
        f"{OPTOUT_URL}?secret=wrong",
        data=json.dumps({"results": []}),
        content_type="application/json",
    )
    assert resp.status_code == 403


# --- SERBITO-362 (JAVI-3): header / Basic auth (Infobip subscription), constant-time ---

_DELIVERED = {"results": [{"messageId": "m-1", "status": {"groupName": "DELIVERED"}}]}


@pytest.mark.parametrize(
    "auth",
    [
        {"HTTP_X_WEBHOOK_SECRET": SECRET},
        {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(f"infobip:{SECRET}".encode()).decode()},
    ],
)
@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
def test_reports_accept_secret_in_header_or_basic_auth(client, auth):
    notif = _notification()
    resp = client.post(URL, data=json.dumps(_DELIVERED), content_type="application/json", **auth)
    assert resp.status_code == 200
    notif.refresh_from_db()
    assert notif.status == Notification.Status.DELIVERED


@override_settings(INFOBIP_WEBHOOK_SECRET=SECRET)
@pytest.mark.parametrize("url", [URL, "/webhooks/infobip/optout/"])
def test_webhooks_reject_wrong_header(client, url):
    resp = client.post(
        url, data="{}", content_type="application/json", HTTP_X_WEBHOOK_SECRET="wrong"
    )
    assert resp.status_code == 403


@override_settings(INFOBIP_WEBHOOK_SECRET="")
def test_webhooks_fail_closed_without_configured_secret(client):
    resp = client.post(
        f"{URL}?secret=", data="{}", content_type="application/json", HTTP_X_WEBHOOK_SECRET=""
    )
    assert resp.status_code == 403
