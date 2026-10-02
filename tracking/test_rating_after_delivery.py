"""SERBITO-356 (J8): the customer rates only a delivered order and confirms "received" first.

Before: the stars showed while the order was still on its way, and "Primio sam porudžbinu"
(masculine only) marked it delivered with one tap and no confirmation.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from common.testing import parse_html
from deliveries.models import Delivery, Rating, Shop, TrackingToken

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _token(status, language="sr-latn"):
    user = get_user_model().objects.create_user(email="r@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pekara")
    delivery = Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_address="a",
        status=status, recipient_language=language,
    )
    return TrackingToken.objects.create(delivery=delivery)


def test_no_stars_while_on_the_way(client):
    token = _token(Delivery.Status.ON_THE_WAY, "en")
    root = parse_html(client.get(f"/t/{token.token}/").content.decode())
    assert not root.find_all("form", {"role": "group"})
    assert "After that you can rate the delivery." in root.text()


def test_rating_post_before_delivery_is_ignored(client):
    token = _token(Delivery.Status.ON_THE_WAY)
    resp = client.post(f"/t/{token.token}/oceni/", {"value": "5"})
    assert resp.status_code == 302
    assert not Rating.objects.exists()


def test_stars_after_delivery(client):
    token = _token(Delivery.Status.DELIVERED)
    root = parse_html(client.get(f"/t/{token.token}/").content.decode())
    assert root.find("form", {"role": "group"})
    client.post(f"/t/{token.token}/oceni/", {"value": "4"})
    assert Rating.objects.get().value == 4


def test_received_button_asks_first_and_is_gender_neutral(client):
    token = _token(Delivery.Status.ON_THE_WAY)
    body = client.get(f"/t/{token.token}/").content.decode()
    root = parse_html(body)
    form = root.find("form", {"action": f"/t/{token.token}/primljeno/"})
    assert form.attrs["data-confirm"].startswith("Potvrđujete da je porudžbina primljena?")
    assert form.find("button").text() == "Potvrdi prijem porudžbine"
    assert "Primio sam" not in body
