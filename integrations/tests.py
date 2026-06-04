from unittest.mock import patch

import pytest
import requests
from django.test import override_settings

from integrations.base import GeocodeResult
from integrations.google_maps import GoogleMapsProvider
from integrations.infobip import InfobipProvider
from integrations.models import GeocodeCache
from integrations.providers import get_maps_provider
from integrations.testing import FakeMapsProvider


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
