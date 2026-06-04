from unittest.mock import patch

import pytest
import requests
from django.test import override_settings

from integrations.base import GeocodeResult
from integrations.google_maps import GoogleMapsProvider
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
