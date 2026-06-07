from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import requests
from django.test import override_settings

from integrations.base import GeocodeResult, SendResult
from integrations.google_maps import GoogleMapsProvider
from integrations.infobip import InfobipProvider
from integrations.metering import (
    MeteringMapsProvider,
    MeteringMessagingProvider,
    MeteringRoutesProvider,
)
from integrations.models import (
    METRIC_MAPS_GEOCODE,
    METRIC_MAPS_ROUTE,
    METRIC_SMS,
    METRIC_VIBER,
    GeocodeCache,
    ProviderUsage,
)
from integrations.providers import get_maps_provider
from integrations.testing import FakeMapsProvider
from integrations.usage import quota_summary


@pytest.mark.django_db
@override_settings(MAPS_PROVIDER="integrations.testing.FakeMapsProvider")
def test_cache_prevents_second_provider_call():
    """AC#6: одинаковый адрес второй раз берётся из кэша, провайдер не вызывается."""
    FakeMapsProvider.calls = 0
    provider = get_maps_provider()

    first = provider.geocode("Knez Mihailova 6, Beograd")
    second = provider.geocode("  knez   mihailova 6,  BEOGRAD ")  # тот же ключ после нормализации

    assert first == second
    assert FakeMapsProvider.calls == 1
    assert GeocodeCache.objects.count() == 1


# --- Quota metering (free-tier counters) ---


class _Inner:
    """Минимальные фейки провайдеров для проверки обёрток-счётчиков."""

    def geocode(self, address):
        return GeocodeResult(1.0, 2.0, address, "")

    def route_duration_seconds(self, *a, **k):
        return 600

    def __init__(self, send_result=None):
        self._send_result = send_result

    def send_text(self, to, text):
        return self._send_result


@pytest.mark.django_db
def test_record_increments_atomically_per_period():
    """record() копит в строке (metric, period); период — UTC-месяц."""
    now = datetime(2026, 6, 15, tzinfo=UTC)
    ProviderUsage.record(METRIC_VIBER, now=now)
    ProviderUsage.record(METRIC_VIBER, 3, now=now)
    row = ProviderUsage.objects.get(metric=METRIC_VIBER, period="2026-06")
    assert row.count == 4


@pytest.mark.django_db
def test_record_separate_bucket_per_month():
    ProviderUsage.record(METRIC_SMS, now=datetime(2026, 6, 1, tzinfo=UTC))
    ProviderUsage.record(METRIC_SMS, now=datetime(2026, 7, 1, tzinfo=UTC))
    assert ProviderUsage.objects.filter(metric=METRIC_SMS).count() == 2


@pytest.mark.django_db
def test_metering_maps_counts_each_real_call():
    MeteringMapsProvider(_Inner()).geocode("addr")
    assert ProviderUsage.objects.get(metric=METRIC_MAPS_GEOCODE).count == 1


@pytest.mark.django_db
def test_metering_routes_counts_each_call():
    MeteringRoutesProvider(_Inner()).route_duration_seconds()
    assert ProviderUsage.objects.get(metric=METRIC_MAPS_ROUTE).count == 1


@pytest.mark.django_db
def test_metering_messaging_counts_actual_channel():
    """Считается фактический канал из SendResult (viber/sms), не запрошенный."""
    inner = _Inner(send_result=SendResult(ok=True, channel="sms"))
    MeteringMessagingProvider(inner).send_text("+381", "hi")
    assert ProviderUsage.objects.get(metric=METRIC_SMS).count == 1
    assert not ProviderUsage.objects.filter(metric=METRIC_VIBER).exists()


@pytest.mark.django_db
def test_metering_messaging_skips_failed_send():
    inner = _Inner(send_result=SendResult(ok=False, channel=""))
    MeteringMessagingProvider(inner).send_text("+381", "hi")
    assert ProviderUsage.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    MAPS_PROVIDER="integrations.testing.FakeMapsProvider", USAGE_METERING_ENABLED=True
)
def test_cache_hit_does_not_meter():
    """Кэш-хит геокодинга не доходит до счётчика — считается только первый реальный вызов."""
    FakeMapsProvider.calls = 0
    provider = get_maps_provider()
    provider.geocode("Knez Mihailova 6, Beograd")
    provider.geocode("knez mihailova 6, beograd")  # тот же ключ → кэш
    assert ProviderUsage.objects.get(metric=METRIC_MAPS_GEOCODE).count == 1


@pytest.mark.django_db
@override_settings(FREE_QUOTA_VIBER=1000, FREE_QUOTA_SMS=500, FREE_QUOTA_MAPS=10000)
def test_quota_summary_used_limit_remaining():
    now = datetime(2026, 6, 10, tzinfo=UTC)
    ProviderUsage.record(METRIC_VIBER, 120, now=now)
    ProviderUsage.record(METRIC_MAPS_GEOCODE, 800, now=now)
    ProviderUsage.record(METRIC_MAPS_ROUTE, 200, now=now)
    summary = {b["key"]: b for b in quota_summary(now=now)}
    assert summary["viber"]["remaining"] == 880
    assert summary["sms"]["remaining"] == 500  # ничего не потрачено
    assert summary["maps"]["used"] == 1000 and summary["maps"]["remaining"] == 9000
    assert summary["maps"]["pct"] == 10


@pytest.mark.django_db
@override_settings(FREE_QUOTA_MAPS=10000, FREE_QUOTA_VIBER=1000)
def test_quota_maps_is_monthly_viber_is_lifetime():
    """Maps сбрасывается помесячно (другой месяц не считается); Viber — пожизненно."""
    june = datetime(2026, 6, 1, tzinfo=UTC)
    may = datetime(2026, 5, 1, tzinfo=UTC)
    ProviderUsage.record(METRIC_MAPS_GEOCODE, 300, now=may)  # прошлый месяц — не в счёт
    ProviderUsage.record(METRIC_MAPS_GEOCODE, 50, now=june)
    ProviderUsage.record(METRIC_VIBER, 10, now=may)
    ProviderUsage.record(METRIC_VIBER, 5, now=june)
    summary = {b["key"]: b for b in quota_summary(now=june)}
    assert summary["maps"]["used"] == 50  # только июнь
    assert summary["viber"]["used"] == 15  # май + июнь


@pytest.mark.django_db
@override_settings(FREE_QUOTA_VIBER=0)
def test_quota_unlimited_when_limit_zero():
    ProviderUsage.record(METRIC_VIBER, 7, now=datetime(2026, 6, 1, tzinfo=UTC))
    viber = {b["key"]: b for b in quota_summary(now=datetime(2026, 6, 1, tzinfo=UTC))}[
        "viber"
    ]
    assert viber["remaining"] is None and viber["used"] == 7


def _fake_response(payload):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    return _Resp()


def test_google_provider_parses_ok():
    """Успешный OK-ответ → GeocodeResult."""
    payload = {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Knez Mihailova 6, Beograd 11000, Srbija",
                "geometry": {"location": {"lat": 44.8167, "lng": 20.4592}},
            }
        ],
    }
    with patch("integrations.google_maps.requests.get", return_value=_fake_response(payload)):
        result = GoogleMapsProvider(api_key="test-key").geocode("Knez Mihailova 6")

    assert result == GeocodeResult(44.8167, 20.4592, "Knez Mihailova 6, Beograd 11000, Srbija")


def test_google_provider_zero_results_returns_none():
    """ZERO_RESULTS → None (адрес не распознан)."""
    payload = {"status": "ZERO_RESULTS", "results": []}
    with patch("integrations.google_maps.requests.get", return_value=_fake_response(payload)):
        result = GoogleMapsProvider(api_key="test-key").geocode("несуществующий адрес")
    assert result is None


def test_google_provider_network_error_returns_none():
    """Сетевой сбой → None (мягкая деградация, без исключения наружу)."""
    with patch(
        "integrations.google_maps.requests.get",
        side_effect=requests.RequestException("timeout"),
    ):
        result = GoogleMapsProvider(api_key="test-key").geocode("Knez Mihailova 6")
    assert result is None


def test_google_provider_no_key_returns_none():
    """Без ключа геокодинг отключён → None."""
    assert GoogleMapsProvider(api_key="").geocode("Knez Mihailova 6") is None


# --- Story 2.3: Viber → SMS fallback ---


def _ok_response():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"messages": [{"messageId": "m-1"}]}

    return _Resp()


def _infobip():
    return InfobipProvider(base_url="https://x", api_key="k", sender="S", channel="viber")


def test_viber_ok_no_sms():
    """AC#1/#3: Viber успешен → SMS не вызывается, channel=viber."""
    with patch("integrations.infobip.requests.post", return_value=_ok_response()) as post:
        result = _infobip().send_text("+381641234567", "hi")
    assert result.ok and result.channel == "viber"
    assert post.call_count == 1
    assert post.call_args.args[0].endswith("/viber/2/messages")


def test_viber_fail_falls_back_to_sms():
    """AC#2: Viber падает → SMS, channel=sms."""
    calls = []

    def _side_effect(url, **kwargs):
        calls.append(url)
        if url.endswith("/viber/2/messages"):
            raise requests.RequestException("viber down")
        return _ok_response()

    with patch("integrations.infobip.requests.post", side_effect=_side_effect):
        result = _infobip().send_text("+381641234567", "hi")
    assert result.ok and result.channel == "sms"
    assert any("/viber/2/messages" in u for u in calls)
    assert any("/sms/2/text/advanced" in u for u in calls)


@override_settings(INFOBIP_SMS_FALLBACK=False)
def test_viber_fail_no_fallback_when_disabled():
    """AC#5: при выключенном fallback Viber-сбой → ok=False, без SMS."""
    with patch(
        "integrations.infobip.requests.post",
        side_effect=requests.RequestException("down"),
    ) as post:
        result = InfobipProvider(
            base_url="https://x", api_key="k", sender="S", channel="viber", sms_fallback=False
        ).send_text("+381641234567", "hi")
    assert result.ok is False
    assert post.call_count == 1  # только Viber


def test_channel_sms_sends_sms_directly():
    """AC#4: INFOBIP_CHANNEL=sms → сразу SMS, без Viber."""
    with patch("integrations.infobip.requests.post", return_value=_ok_response()) as post:
        result = InfobipProvider(
            base_url="https://x", api_key="k", sender="S", channel="sms"
        ).send_text("+381641234567", "hi")
    assert result.ok and result.channel == "sms"
    assert post.call_args.args[0].endswith("/sms/2/text/advanced")


def test_no_key_returns_not_ok():
    assert InfobipProvider(api_key="", channel="viber").send_text("+381", "x").ok is False


@override_settings(INFOBIP_WEBHOOK_SECRET="whsec", PUBLIC_BASE_URL="https://javi.serbito.rs")
def test_viber_payload_includes_report_webhook():
    """notifyUrl/webhooks: Viber-сообщение содержит delivery/seen webhook с секретом."""
    with patch("integrations.infobip.requests.post", return_value=_ok_response()) as post:
        _infobip().send_text("+381641234567", "hi")
    msg = post.call_args.kwargs["json"]["messages"][0]
    url = msg["webhooks"]["delivery"]["url"]
    assert url.endswith("/webhooks/infobip/reports/?secret=whsec")
    assert msg["webhooks"]["seen"]["url"] == url


@override_settings(INFOBIP_WEBHOOK_SECRET="whsec", PUBLIC_BASE_URL="https://javi.serbito.rs")
def test_sms_payload_includes_notify_url():
    with patch("integrations.infobip.requests.post", return_value=_ok_response()) as post:
        InfobipProvider(
            base_url="https://x", api_key="k", sender="S", channel="sms"
        ).send_text("+381641234567", "hi")
    msg = post.call_args.kwargs["json"]["messages"][0]
    assert msg["notifyUrl"].endswith("/webhooks/infobip/reports/?secret=whsec")
    assert msg["notifyContentType"] == "application/json"


@override_settings(INFOBIP_WEBHOOK_SECRET="")
def test_no_webhook_when_secret_unset():
    with patch("integrations.infobip.requests.post", return_value=_ok_response()) as post:
        _infobip().send_text("+381641234567", "hi")
    assert "webhooks" not in post.call_args.kwargs["json"]["messages"][0]
