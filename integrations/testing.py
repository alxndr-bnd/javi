"""Фейк-провайдеры карт для тестов (без реальной сети). Подключаются через MAPS_PROVIDER."""

from __future__ import annotations

from .base import GeocodeResult, MapsProvider


class FakeMapsProvider(MapsProvider):
    """Всегда успешный геокод фиксированной точкой. Считает вызовы (для проверки кэша)."""

    calls = 0
    result = GeocodeResult(
        lat=44.8167,
        lng=20.4592,
        formatted_address="Knez Mihailova 6, Beograd, Srbija",
    )

    def geocode(self, address: str) -> GeocodeResult | None:
        type(self).calls += 1
        return self.result


class FailingMapsProvider(MapsProvider):
    """Всегда miss (адрес не распознан / провайдер недоступен)."""

    def geocode(self, address: str) -> GeocodeResult | None:
        return None
