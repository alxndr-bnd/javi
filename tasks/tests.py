import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from common.timewindow import rating_send_time
from deliveries.models import Delivery, Shop, TrackingToken
from deliveries.services import start_delivery
from notifications.models import Notification
from tasks.testing import RecordingTaskScheduler

pytestmark = pytest.mark.django_db

ROUTES_OK = "integrations.testing.FakeRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"
SCHED = "tasks.testing.RecordingTaskScheduler"
SECRET = "t0ken"


def _make_shop(email="s@shop.rs", name="Shop"):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    shop = Shop.objects.create(owner=user, name=name, origin_lat=44.8, origin_lng=20.45)
    return shop


def _delivery(shop):
    return Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="adr",
        dest_lat=44.81,
        dest_lng=20.46,
    )


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK, TASK_SCHEDULER=SCHED)
def test_start_schedules_rating_request():
    """AC#1: старт планирует rating на rating_send_time(ETA)."""
    RecordingTaskScheduler.scheduled = []
    delivery = _delivery(_make_shop())
    start_delivery(delivery)
    delivery.refresh_from_db()
    assert len(RecordingTaskScheduler.scheduled) == 1
    did, run_at = RecordingTaskScheduler.scheduled[0]
    assert did == delivery.id
    assert run_at == rating_send_time(delivery.eta_at)


@override_settings(
    ROUTES_PROVIDER=ROUTES_OK,
    MESSAGING_PROVIDER=MSG_OK,
    TASK_SCHEDULER="tasks.testing.FailingTaskScheduler",
)
def test_start_survives_scheduler_failure():
    """Сбой планировщика не ломает старт (сообщение уже ушло)."""
    delivery = _delivery(_make_shop())
    result = start_delivery(delivery)
    assert result.ok is True
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.ON_THE_WAY


@override_settings(MESSAGING_PROVIDER=MSG_OK, TASKS_SECRET=SECRET)
def test_send_rating_callback_sends_request(client):
    """AC#2/#3: верный секрет → rating_request Notification."""
    shop = _make_shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    resp = client.post(f"/tasks/send-rating/{delivery.id}/", HTTP_X_TASKS_SECRET=SECRET)
    assert resp.status_code == 200
    assert delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).count() == 1


@override_settings(MESSAGING_PROVIDER=MSG_OK, TASKS_SECRET=SECRET)
def test_send_rating_idempotent(client):
    shop = _make_shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    client.post(f"/tasks/send-rating/{delivery.id}/", HTTP_X_TASKS_SECRET=SECRET)
    client.post(f"/tasks/send-rating/{delivery.id}/", HTTP_X_TASKS_SECRET=SECRET)
    assert delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).count() == 1


@override_settings(TASKS_SECRET=SECRET)
def test_send_rating_wrong_secret_forbidden(client):
    shop = _make_shop()
    delivery = _delivery(shop)
    resp = client.post(f"/tasks/send-rating/{delivery.id}/?secret=wrong")
    assert resp.status_code == 403


# --- P4: async DLR-driven escalation (off by default) ---

from deliveries.services import escalate_delivery  # noqa: E402

P4_CHAIN = [
    "integrations.testing.FakeViberOkProvider",
    "integrations.testing.FakeSmsOkProvider",
]
_P4 = dict(
    ROUTES_PROVIDER=ROUTES_OK,
    MESSAGING_PROVIDER="",
    MESSAGING_CHAIN=P4_CHAIN,
    TASK_SCHEDULER=SCHED,
    FALLBACK_ESCALATION_ENABLED=True,
)


@override_settings(**_P4)
def test_start_schedules_escalation_when_untried_channels_remain():
    """Viber принят, SMS не пробован → планируется проверка доставки (эскалация)."""
    RecordingTaskScheduler.escalations = []
    delivery = _delivery(_make_shop())
    start_delivery(delivery)
    assert [d for d, _ in RecordingTaskScheduler.escalations] == [delivery.id]


@override_settings(**{**_P4, "FALLBACK_ESCALATION_ENABLED": False})
def test_start_no_escalation_when_flag_off():
    RecordingTaskScheduler.escalations = []
    start_delivery(_delivery(_make_shop()))
    assert RecordingTaskScheduler.escalations == []


@override_settings(**_P4)
def test_escalate_sends_next_channel_when_not_delivered():
    """on_the_way не доставлен → следующий канал (SMS): новая попытка, канал обновлён."""
    RecordingTaskScheduler.escalations = []
    delivery = _delivery(_make_shop())
    start_delivery(delivery)
    notif = delivery.notifications.get(kind=Notification.Kind.ON_THE_WAY)
    assert notif.channel == "viber"

    assert escalate_delivery(delivery) is True
    notif.refresh_from_db()
    assert notif.channel == "sms"
    assert [(a.attempt_no, a.channel) for a in notif.attempts.all()] == [(1, "viber"), (2, "sms")]


@override_settings(**_P4)
def test_escalate_noop_when_delivered():
    delivery = _delivery(_make_shop())
    start_delivery(delivery)
    notif = delivery.notifications.get(kind=Notification.Kind.ON_THE_WAY)
    notif.status = Notification.Status.DELIVERED
    notif.save(update_fields=["status"])

    assert escalate_delivery(delivery) is False
    assert notif.attempts.count() == 1  # никаких новых попыток


@override_settings(**_P4)
def test_escalate_noop_when_channels_exhausted():
    delivery = _delivery(_make_shop())
    start_delivery(delivery)
    assert escalate_delivery(delivery) is True  # → SMS
    assert escalate_delivery(delivery) is False  # каналы исчерпаны


@override_settings(
    MESSAGING_PROVIDER="",
    MESSAGING_CHAIN=P4_CHAIN,
    TASKS_SECRET=SECRET,
    FALLBACK_ESCALATION_ENABLED=True,
)
def test_escalate_callback_secret_guarded(client):
    delivery = _delivery(_make_shop())
    assert client.post(f"/tasks/escalate/{delivery.id}/?secret=wrong").status_code == 403
    assert client.post(f"/tasks/escalate/{delivery.id}/?secret={SECRET}").status_code == 200


# --- SERBITO-362 (JAVI-3): the secret travels in a header, compared in constant time ---


@override_settings(MESSAGING_PROVIDER=MSG_OK, TASKS_SECRET=SECRET)
def test_legacy_query_secret_still_accepted_for_already_queued_tasks(client):
    shop = _make_shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    assert client.post(f"/tasks/send-rating/{delivery.id}/?secret={SECRET}").status_code == 200


@override_settings(TASKS_SECRET=SECRET)
@pytest.mark.parametrize("headers", [{}, {"HTTP_X_TASKS_SECRET": "wrong"}])
def test_callbacks_reject_missing_or_wrong_header(client, headers):
    delivery = _delivery(_make_shop())
    assert client.post(f"/tasks/send-rating/{delivery.id}/", **headers).status_code == 403
    assert client.post(f"/tasks/escalate/{delivery.id}/", **headers).status_code == 403


@override_settings(TASKS_SECRET="")
def test_callbacks_fail_closed_without_configured_secret(client):
    delivery = _delivery(_make_shop())
    resp = client.post(f"/tasks/send-rating/{delivery.id}/?secret=", HTTP_X_TASKS_SECRET="")
    assert resp.status_code == 403


@override_settings(
    TASKS_SECRET=SECRET,
    CLOUD_TASKS_SERVICE_URL="https://javi.serbito.rs",
    CLOUD_TASKS_PROJECT="p",
    CLOUD_TASKS_LOCATION="l",
    CLOUD_TASKS_QUEUE="q",
)
def test_cloud_tasks_put_the_secret_in_a_header_not_the_url():
    from datetime import UTC, datetime
    from unittest import mock

    from tasks.scheduler import CloudTasksScheduler

    with mock.patch("google.cloud.tasks_v2.CloudTasksClient") as client_cls:
        client_cls.return_value.queue_path.return_value = "queue"
        CloudTasksScheduler().schedule_rating_request(7, datetime(2026, 9, 29, 12, tzinfo=UTC))
    task = client_cls.return_value.create_task.call_args.kwargs["request"]["task"]
    http = task["http_request"]
    assert http["url"] == "https://javi.serbito.rs/tasks/send-rating/7/"
    assert SECRET not in http["url"]
    assert http["headers"] == {"X-Tasks-Secret": SECRET}
