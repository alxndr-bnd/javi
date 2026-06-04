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
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567",
        dest_address="adr", dest_lat=44.81, dest_lng=20.46,
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
    resp = client.post(f"/tasks/send-rating/{delivery.id}/?secret={SECRET}")
    assert resp.status_code == 200
    assert delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).count() == 1


@override_settings(MESSAGING_PROVIDER=MSG_OK, TASKS_SECRET=SECRET)
def test_send_rating_idempotent(client):
    shop = _make_shop()
    delivery = _delivery(shop)
    TrackingToken.objects.create(delivery=delivery)
    client.post(f"/tasks/send-rating/{delivery.id}/?secret={SECRET}")
    client.post(f"/tasks/send-rating/{delivery.id}/?secret={SECRET}")
    assert delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).count() == 1


@override_settings(TASKS_SECRET=SECRET)
def test_send_rating_wrong_secret_forbidden(client):
    shop = _make_shop()
    delivery = _delivery(shop)
    resp = client.post(f"/tasks/send-rating/{delivery.id}/?secret=wrong")
    assert resp.status_code == 403
