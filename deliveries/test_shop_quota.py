"""SERBITO-356 (J10): the cabinet menu shows the shop's own message limits, not platform usage.

Before: "Free quota left" showed the platform-wide Viber/SMS/Maps usage to every shop.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings

from common.testing import parse_html
from deliveries.models import Delivery, Shop
from integrations.models import METRIC_VIBER, ProviderUsage
from notifications.models import OutboundSend

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _shop(**extra):
    user = get_user_model().objects.create_user(email="q@shop.rs", password="pass12345")
    return Shop.objects.create(owner=user, name="Pekara", **extra)


@override_settings(SEND_LIMIT_TRIAL_DAY=10, SEND_LIMIT_TRIAL_MONTH=30)
def test_shop_sees_its_own_caps_not_platform_usage(client):
    ProviderUsage.record(METRIC_VIBER, 777)
    shop = _shop()
    delivery = Delivery.objects.create(
        shop=shop, recipient_name="A", recipient_phone="+381641234567", dest_address="a"
    )
    for _ in range(3):
        OutboundSend.objects.create(
            shop=shop, delivery=delivery, phone="+381641234567", kind=OutboundSend.Kind.ON_THE_WAY
        )
    client.force_login(shop.owner)
    resp = client.get("/app/", HTTP_ACCEPT_LANGUAGE="en")
    assert "free_quota" not in resp.context
    menu = parse_html(resp.content.decode()).find("div", {"class": "menu-pop"}).text()
    assert "Customer messages" in menu
    assert "3 of 10" in menu and "3 of 30" in menu
    assert "Free quota left" not in menu and "777" not in menu
    assert "Trial limits" in menu


def test_verified_shop_with_custom_caps(client):
    shop = _shop(sending_verified=True, daily_send_limit=80, monthly_send_limit=900)
    client.force_login(shop.owner)
    menu = (
        parse_html(client.get("/app/", HTTP_ACCEPT_LANGUAGE="en").content.decode())
        .find("div", {"class": "menu-pop"})
        .text()
    )
    assert "0 of 80" in menu and "0 of 900" in menu
    assert "Trial limits" not in menu


def test_staff_also_sees_platform_quota(client):
    shop = _shop()
    shop.owner.is_staff = True
    shop.owner.save(update_fields=["is_staff"])
    client.force_login(shop.owner)
    resp = client.get("/app/", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.context["free_quota"]
    assert "Free quota left" in resp.content.decode()
