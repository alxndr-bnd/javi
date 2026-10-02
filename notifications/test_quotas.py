"""Лимиты исходящих сообщений и очистка названия магазина (SERBITO-345).

Все отправки — через фейк-провайдер или замоканный Infobip (requests.post): реальных
сообщений тесты не шлют.
"""

import importlib
import json
import logging
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone, translation

from common.phone import normalize_phone
from common.text import SHOP_NAME_MAX_LEN, sanitize_shop_name, shop_name_is_clean
from deliveries.models import ApiKey, Delivery, Shop, TrackingToken
from deliveries.services import (
    create_delivery,
    resend_on_the_way,
    send_rating_request,
    start_delivery,
)
from integrations.testing import FakeMessagingProvider
from notifications.models import Notification, OutboundSend
from notifications.quotas import (
    QuotaExceeded,
    ShopLimits,
    reserve_send,
    shop_limits,
    shop_usage,
)

pytestmark = pytest.mark.django_db

MAPS_OK = "integrations.testing.FakeMapsProvider"
ROUTES_OK = "integrations.testing.FakeRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"
BELGRADE = ZoneInfo("Europe/Belgrade")
RS_MOBILE = "+381641234567"
FOREIGN = "+4915123456789"

_n = 0


def _shop(*, verified=True, name="Shop Q", **fields):
    global _n
    _n += 1
    user = get_user_model().objects.create_user(email=f"q{_n}@shop.rs", password="pass12345")
    return Shop.objects.create(
        owner=user,
        name=name,
        sending_verified=verified,
        origin_address="Origin, Beograd",
        origin_lat=44.8,
        origin_lng=20.45,
        **fields,
    )


def _delivery(shop, phone="064 123 4567"):
    with override_settings(MAPS_PROVIDER=MAPS_OK):
        delivery, _ = create_delivery(
            shop, recipient_name="Ana", phone=normalize_phone(phone), dest_address="Adresa 1"
        )
    return delivery


def _started(shop, phone="064 123 4567"):
    delivery = _delivery(shop, phone)
    start_delivery(delivery)
    delivery.refresh_from_db()
    return delivery


def _fill(shop, n, *, phone=RS_MOBILE, when=None, kind=OutboundSend.Kind.ON_THE_WAY):
    OutboundSend.objects.bulk_create(
        [
            OutboundSend(shop=shop, phone=phone, kind=kind, created_at=when or timezone.now())
            for _ in range(n)
        ]
    )


@pytest.fixture(autouse=True)
def _fake_messaging():
    FakeMessagingProvider.sent = []
    with override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK):
        yield


# --- Лимиты магазина ------------------------------------------------------


@override_settings(SEND_LIMIT_SHOP_DAY=2)
def test_shop_daily_cap_blocks_start_before_sending():
    shop = _shop()
    _started(shop)
    _started(shop, "064 222 3333")
    third = _delivery(shop, "064 444 5555")

    with pytest.raises(QuotaExceeded) as exc:
        start_delivery(third)

    assert exc.value.code == "daily_limit"
    assert exc.value.http_status == 429
    assert "2 per day" in exc.value.message
    assert len(FakeMessagingProvider.sent) == 2  # третье сообщение провайдер не видел
    third.refresh_from_db()
    assert third.status == Delivery.Status.NEW  # доставка не стартовала
    assert not third.notifications.exists()


@override_settings(SEND_LIMIT_SHOP_DAY=1)
def test_daily_cap_resets_next_day():
    shop = _shop()
    now = datetime(2026, 9, 15, 0, 30, tzinfo=BELGRADE)
    _fill(shop, 1, when=datetime(2026, 9, 14, 23, 50, tzinfo=BELGRADE))  # вчера по Белграду
    reserve_send(shop, RS_MOBILE, kind=OutboundSend.Kind.ON_THE_WAY, now=now)
    with pytest.raises(QuotaExceeded):
        reserve_send(shop, "+381642222222", kind=OutboundSend.Kind.ON_THE_WAY, now=now)


@override_settings(SEND_LIMIT_SHOP_DAY=100, SEND_LIMIT_SHOP_MONTH=3)
def test_shop_monthly_cap():
    shop = _shop()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=BELGRADE)
    _fill(shop, 2, phone="+381641111111", when=datetime(2026, 9, 3, 10, tzinfo=BELGRADE))
    _fill(shop, 5, phone="+381641111111", when=datetime(2026, 8, 30, 10, tzinfo=BELGRADE))
    reserve_send(shop, RS_MOBILE, kind=OutboundSend.Kind.ON_THE_WAY, now=now)  # 3-е за сентябрь

    with pytest.raises(QuotaExceeded) as exc:
        reserve_send(shop, "+381642222222", kind=OutboundSend.Kind.ON_THE_WAY, now=now)
    assert exc.value.code == "monthly_limit"


@override_settings(
    SEND_LIMIT_SHOP_DAY=50, SEND_LIMIT_SHOP_MONTH=500,
    SEND_LIMIT_TRIAL_DAY=10, SEND_LIMIT_TRIAL_MONTH=30,
)
def test_limits_trial_verified_and_override():
    assert shop_limits(_shop(verified=False)) == ShopLimits(10, 30, True)
    assert shop_limits(_shop(verified=True)) == ShopLimits(50, 500, False)
    custom = _shop(verified=True, daily_send_limit=200, monthly_send_limit=4000)
    assert (shop_limits(custom).day, shop_limits(custom).month) == (200, 4000)


@override_settings(SEND_LIMIT_TRIAL_DAY=1)
def test_trial_shop_has_low_limit_and_is_told_why():
    shop = _shop(verified=False)
    _started(shop)
    with pytest.raises(QuotaExceeded) as exc:
        start_delivery(_delivery(shop, "064 222 3333"))
    assert exc.value.code == "daily_limit"
    assert "until the store is verified" in exc.value.message


def test_trial_shop_cannot_message_foreign_numbers():
    shop = _shop(verified=False)
    delivery = _delivery(shop, FOREIGN)
    assert delivery.phone_risk

    with pytest.raises(QuotaExceeded) as exc:
        start_delivery(delivery)
    assert exc.value.code == "destination_not_allowed"
    assert exc.value.http_status == 403
    assert FakeMessagingProvider.sent == []


def test_verified_shop_can_message_foreign_numbers():
    shop = _shop(verified=True)
    result = start_delivery(_delivery(shop, FOREIGN))
    assert result.ok and result.sent


# --- Номер получателя и глобальный предохранитель ----------------------------


@override_settings(SEND_LIMIT_RECIPIENT_DAY=2)
def test_recipient_daily_cap_counts_all_shops():
    _started(_shop())
    _started(_shop())
    with pytest.raises(QuotaExceeded) as exc:
        start_delivery(_delivery(_shop()))
    assert exc.value.code == "recipient_daily_limit"
    assert len(FakeMessagingProvider.sent) == 2
    # Другой номер тем же магазином — можно.
    assert start_delivery(_delivery(_shop(), "064 999 8888")).ok


@override_settings(SEND_LIMIT_GLOBAL_DAY=3)
def test_global_daily_cap_blocks_and_logs_error(caplog):
    _fill(_shop(), 3, phone="+381640000001")
    with caplog.at_level(logging.ERROR, logger="notifications.quotas"):
        with pytest.raises(QuotaExceeded) as exc:
            start_delivery(_delivery(_shop()))
    assert exc.value.code == "global_limit"
    assert exc.value.http_status == 503
    assert any("GLOBAL DAILY CAP HIT" in r.getMessage() for r in caplog.records)
    assert FakeMessagingProvider.sent == []


def test_blocked_send_is_not_recorded():
    shop = _shop(verified=False)
    with pytest.raises(QuotaExceeded):
        reserve_send(shop, FOREIGN, kind=OutboundSend.Kind.ON_THE_WAY, risky=True)
    assert not OutboundSend.objects.exists()


def test_zero_limit_means_no_sending_not_unlimited():
    shop = _shop(daily_send_limit=0)
    with pytest.raises(QuotaExceeded):
        reserve_send(shop, RS_MOBILE, kind=OutboundSend.Kind.ON_THE_WAY)


# --- Переотправка -----------------------------------------------------------


@override_settings(SEND_LIMIT_RESENDS_PER_DELIVERY=3, SEND_LIMIT_RECIPIENT_DAY=100)
def test_resend_cap_per_delivery():
    delivery = _started(_shop())
    for _ in range(3):
        assert resend_on_the_way(delivery).ok
    with pytest.raises(QuotaExceeded) as exc:
        resend_on_the_way(delivery)
    assert exc.value.code == "resend_limit"
    assert "3 times" in exc.value.message
    assert len(FakeMessagingProvider.sent) == 4  # старт + 3 переотправки


@override_settings(SEND_LIMIT_SHOP_DAY=2, SEND_LIMIT_RECIPIENT_DAY=100)
def test_resend_to_new_number_counts_against_shop_quota_and_keeps_number():
    shop = _shop()
    delivery = _started(shop)
    assert resend_on_the_way(delivery, new_phone=normalize_phone("064 222 3333")).ok

    with pytest.raises(QuotaExceeded) as exc:
        resend_on_the_way(delivery, new_phone=normalize_phone("064 444 5555"))
    assert exc.value.code == "daily_limit"
    delivery.refresh_from_db()
    assert delivery.recipient_phone == "+381642223333"  # заблокированная правка не сохранена
    kinds = list(OutboundSend.objects.filter(delivery=delivery).values_list("kind", "phone"))
    assert sorted(kinds) == [("on_the_way", RS_MOBILE), ("resend", "+381642223333")]


@override_settings(SEND_LIMIT_RECIPIENT_DAY=1)
def test_resend_to_new_number_checks_new_recipient_cap():
    _fill(_shop(), 1, phone="+381642223333")  # новый номер уже получил сегодня лимит
    delivery = _started(_shop())
    with pytest.raises(QuotaExceeded) as exc:
        resend_on_the_way(delivery, new_phone=normalize_phone("064 222 3333"))
    assert exc.value.code == "recipient_daily_limit"


def test_trial_resend_cannot_switch_to_foreign_number():
    delivery = _started(_shop(verified=False))
    with pytest.raises(QuotaExceeded) as exc:
        resend_on_the_way(delivery, new_phone=normalize_phone(FOREIGN))
    assert exc.value.code == "destination_not_allowed"
    delivery.refresh_from_db()
    assert delivery.recipient_phone == RS_MOBILE


# --- Запрос оценки ----------------------------------------------------------


@override_settings(SEND_LIMIT_SHOP_DAY=1)
def test_rating_request_skipped_silently_over_quota():
    delivery = _started(_shop())
    assert send_rating_request(delivery) is None
    assert not delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).exists()
    assert len(FakeMessagingProvider.sent) == 1


def test_rating_request_counts_as_send():
    delivery = _started(_shop())
    send_rating_request(delivery)
    assert OutboundSend.objects.filter(kind=OutboundSend.Kind.RATING_REQUEST).count() == 1


# --- Замоканный Infobip: заблокированная отправка не доходит до HTTP ---------


def _infobip_ok():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"messages": [{"messageId": "m-1"}]}

    return _Resp()


@override_settings(
    MESSAGING_PROVIDER="",
    MESSAGING_CHAIN=[],
    INFOBIP_CHANNEL="viber",
    INFOBIP_SMS_FALLBACK=True,
    INFOBIP_API_KEY="test-key",
    SEND_LIMIT_SHOP_DAY=1,
)
def test_real_infobip_chain_not_called_when_over_quota():
    shop = _shop()
    with patch("integrations.infobip.requests.post", return_value=_infobip_ok()) as post:
        assert start_delivery(_delivery(shop)).sent
        assert post.call_count == 1
        with pytest.raises(QuotaExceeded):
            start_delivery(_delivery(shop, "064 222 3333"))
        assert post.call_count == 1


# --- UI и API ---------------------------------------------------------------


@override_settings(SEND_LIMIT_SHOP_DAY=0)
def test_start_view_shows_quota_error_in_serbian(client):
    shop = _shop()
    delivery = _delivery(shop)
    client.force_login(shop.owner)
    client.cookies["django_language"] = "sr"
    resp = client.post(
        f"/app/dostava/{delivery.pk}/start/", {"eta_time": "16:00"}, follow=True
    )
    body = resp.content.decode()
    assert "Dostignut je dnevni limit poruka (0 dnevno)" in body
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.NEW
    assert FakeMessagingProvider.sent == []


@override_settings(SEND_LIMIT_RESENDS_PER_DELIVERY=0)
def test_resend_view_shows_quota_error(client):
    shop = _shop()
    delivery = _started(shop)
    client.force_login(shop.owner)
    resp = client.post(
        f"/app/dostava/{delivery.pk}/posalji-ponovo/",
        {"recipient_phone": "064 123 4567"},
        follow=True,
    )
    assert "already been resent 0 times" in resp.content.decode()
    assert len(FakeMessagingProvider.sent) == 1


def _api(client, method, url, key, body=None):
    return getattr(client, method)(
        url, data=json.dumps(body or {}), content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )


@override_settings(SEND_LIMIT_SHOP_DAY=0)
def test_api_start_returns_429_with_code(client):
    shop = _shop()
    _obj, key = ApiKey.generate(shop)
    delivery = _delivery(shop)
    resp = _api(client, "post", f"/api/v1/deliveries/{delivery.pk}/start", key)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "daily_limit"
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.NEW


def test_api_resend_foreign_number_trial_403(client):
    shop = _shop(verified=False)
    _obj, key = ApiKey.generate(shop)
    delivery = _started(shop)
    resp = _api(
        client, "post", f"/api/v1/deliveries/{delivery.pk}/notifications/resend", key,
        {"recipient_phone": FOREIGN},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "destination_not_allowed"


def test_profile_shows_usage_and_trial_note(client):
    shop = _shop(verified=False)
    _started(shop)
    client.force_login(shop.owner)
    body = client.get("/app/prodavnica/").content.decode()
    assert "Today: 1 of 10" in body
    assert "Trial store" in body
    assert shop_usage(shop)["month_used"] == 1


def test_existing_shops_are_grandfathered_by_migration():
    shop = _shop(verified=False)
    migration = importlib.import_module("deliveries.migrations.0012_shop_send_limits")
    migration.grandfather_existing_shops(django_apps, None)
    shop.refresh_from_db()
    assert shop.sending_verified


def test_new_signup_starts_as_trial(client):
    client.post(
        "/accounts/register/",
        {
            "email": "new@shop.rs",
            "store_name": "Nova Prodavnica",
            "password1": "Xk9!long-pass",
            "password2": "Xk9!long-pass",
        },
    )
    assert Shop.objects.get(owner__email="new@shop.rs").sending_verified is False


# --- Название магазина в сообщении -------------------------------------------


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("Pizza Napoli", "Pizza Napoli"),
        ("Kafana kod Mike d.o.o.", "Kafana kod Mike d.o.o."),
        ("Pizza 2000", "Pizza 2000"),
        ("Pošta: platite na evil.com/pay", "Pošta: platite na"),
        ("Visit https://bit.ly/x now", "Visit now"),
        ("www.evil.rs", ""),
        ("ＷＷＷ．evil．com", ""),  # полноширинные символы → NFKC → домен
        ("Pay at a@b.co", "Pay at"),
        ("Call +381 64 123 4567", "Call"),
        ("Tel 064/123-45-67", "Tel"),
        ("Shop‮evil​", "Shopevil"),  # bidi-override и zero-width
        ("Line\nbreak\ttab", "Line break tab"),
        ('Mike\'s "Pizza" «Best»', "Mike's Pizza Best"),
    ],
)
def test_sanitize_shop_name(raw, clean):
    assert sanitize_shop_name(raw) == clean


def test_sanitize_shop_name_truncates():
    assert len(sanitize_shop_name("x" * 100)) == SHOP_NAME_MAX_LEN
    assert shop_name_is_clean("Pizza Napoli")
    assert not shop_name_is_clean("Pizza napoli.rs")
    assert not shop_name_is_clean("   ")


def test_message_uses_sanitized_quoted_shop_name():
    # Старые данные: название со ссылкой и номером, заведённое до валидации.
    shop = _shop(name="Posta Srbije: carina na evil.com ili 064 123 4567 " + "x" * 50)
    start_delivery(_delivery(shop))
    _to, text = FakeMessagingProvider.sent[0]
    assert "evil" not in text and "064 123" not in text
    assert text.startswith('Your order from "Posta Srbije: carina na ili xxx')
    quoted = text.split('"')[1]
    assert len(quoted) <= SHOP_NAME_MAX_LEN


def test_message_falls_back_when_name_is_all_link():
    shop = _shop(name="https://evil.com")
    start_delivery(_delivery(shop))
    assert FakeMessagingProvider.sent[0][1].startswith('Your order from "Javi" is on its way')


def test_rating_text_in_serbian_is_quoted():
    delivery = _started(_shop(name="Pekara Mika"))
    TrackingToken.objects.filter(delivery=delivery).update(
        expires_at=timezone.now() + timedelta(days=1)
    )
    with translation.override("sr-latn"):
        send_rating_request(delivery)
    assert 'Kako je prošla dostava iz "Pekara Mika"?' in FakeMessagingProvider.sent[-1][1]


def test_register_rejects_link_in_store_name(client):
    resp = client.post(
        "/accounts/register/",
        {
            "email": "phish@shop.rs",
            "store_name": "Paket čeka: evil.com",
            "password1": "Xk9!long-pass",
            "password2": "Xk9!long-pass",
        },
    )
    assert resp.status_code == 200
    assert "can&#x27;t contain links" in resp.content.decode()
    assert not Shop.objects.filter(owner__email="phish@shop.rs").exists()


def test_register_rejects_too_long_store_name(client):
    client.post(
        "/accounts/register/",
        {
            "email": "long@shop.rs",
            "store_name": "x" * (SHOP_NAME_MAX_LEN + 1),
            "password1": "Xk9!long-pass",
            "password2": "Xk9!long-pass",
        },
    )
    assert not Shop.objects.filter(owner__email="long@shop.rs").exists()


def test_profile_form_rejects_phone_in_name(client):
    shop = _shop()
    client.force_login(shop.owner)
    with override_settings(MAPS_PROVIDER=MAPS_OK):
        client.post(
            "/app/prodavnica/",
            {"name": "Zovite 064 123 4567", "address": "Knez Mihailova 6, Beograd"},
        )
    shop.refresh_from_db()
    assert shop.name == "Shop Q"


def test_api_patch_rejects_url_in_name(client):
    shop = _shop()
    _obj, key = ApiKey.generate(shop)
    resp = _api(client, "patch", "/api/v1/shop", key, {"name": "Go to https://evil.com"})
    assert resp.status_code == 400
    shop.refresh_from_db()
    assert shop.name == "Shop Q"
