"""SERBITO-356 (J9): a double submit of "Confirm and notify" sends one SMS, and a failed send
shows one clear message.

The race: two requests both passed the "already started?" check while the first one was still
waiting for the route (a network call), and each sent an SMS. The second request is simulated
here by starting a stale copy of the delivery from inside the first one's route lookup.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import override_settings

from deliveries.models import Delivery, Shop
from deliveries.services import start_delivery
from integrations.base import RoutesProvider
from integrations.testing import FakeMessagingProvider
from notifications.models import Notification, OutboundSend

pytestmark = pytest.mark.django_db

MSG_OK = "integrations.testing.FakeMessagingProvider"
MSG_FAIL = "integrations.testing.FailingMessagingProvider"


class SecondSubmitDuringRouteLookup(RoutesProvider):
    """While the first request waits for the route, the second one (a stale copy) starts."""

    stale_copy: Delivery | None = None

    def route_duration_seconds(self, origin, dest):
        copy, type(self).stale_copy = type(self).stale_copy, None
        if copy is not None:
            start_delivery(copy)
        return 900


@pytest.fixture(autouse=True)
def _clean():
    FakeMessagingProvider.sent = []
    yield
    SecondSubmitDuringRouteLookup.stale_copy = None


def _delivery():
    user = get_user_model().objects.create_user(email="dbl@shop.rs", password="pass12345")
    shop = Shop.objects.create(
        owner=user, name="Pekara", origin_lat=44.8, origin_lng=20.45, sending_verified=True
    )
    return Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_address="a",
        dest_lat=44.81, dest_lng=20.46, status=Delivery.Status.CREATED,
    )


@override_settings(
    ROUTES_PROVIDER="deliveries.test_double_submit.SecondSubmitDuringRouteLookup",
    MESSAGING_PROVIDER=MSG_OK,
)
def test_concurrent_start_sends_one_sms():
    delivery = _delivery()
    SecondSubmitDuringRouteLookup.stale_copy = Delivery.objects.get(pk=delivery.pk)
    first = start_delivery(delivery)
    assert len(FakeMessagingProvider.sent) == 1
    assert first.already is True  # the "second" request won the race; this one backs off
    assert Notification.objects.filter(kind=Notification.Kind.ON_THE_WAY).count() == 1
    assert OutboundSend.objects.count() == 1  # one send counted against the limits
    assert delivery.status == Delivery.Status.ON_THE_WAY


@override_settings(MESSAGING_PROVIDER=MSG_OK)
def test_second_confirm_post_is_a_no_op(client):
    delivery = _delivery()
    client.force_login(delivery.shop.owner)
    url = f"/app/dostava/{delivery.pk}/start/"
    data = {"eta_time": "23:59", "eta_date": "2099-01-01"}
    client.post(url, data)
    client.get("/app/")  # the first outcome message is shown and consumed
    resp = client.post(url, data, HTTP_ACCEPT_LANGUAGE="en")
    assert len(FakeMessagingProvider.sent) == 1
    assert [str(m) for m in get_messages(resp.wsgi_request)] == [
        "Delivery is already in progress."
    ]


def test_confirm_form_submits_once(client):
    delivery = _delivery()
    client.force_login(delivery.shop.owner)
    body = client.post(f"/app/dostava/{delivery.pk}/start/").content.decode()
    assert "data-submit-once" in body


@override_settings(MESSAGING_PROVIDER=MSG_FAIL)
def test_failed_send_shows_one_consistent_message(client):
    delivery = _delivery()
    client.force_login(delivery.shop.owner)
    resp = client.post(
        f"/app/dostava/{delivery.pk}/start/",
        {"eta_time": "23:59", "eta_date": "2099-01-01"},
        HTTP_ACCEPT_LANGUAGE="en",
    )
    msgs = list(get_messages(resp.wsgi_request))
    assert len(msgs) == 1
    assert msgs[0].level_tag == "warning"
    assert "not sent" in str(msgs[0]) and "notified" not in str(msgs[0])
