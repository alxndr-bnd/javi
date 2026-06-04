"""Cache-aside обёртка над MapsProvider (AR-6)."""

from __future__ import annotations

from .base import GeocodeResult, MapsProvider
from .models import GeocodeCache


def normalize_address(address: str) -> str:
    """Ключ кэша: trim + схлопывание пробелов + lower."""
    return " ".join(address.split()).lower()


class CachingMapsProvider(MapsProvider):
    """Оборачивает другой провайдер: сперва кэш, при miss — провайдер, затем запись.

    Промахи провайдера (None) НЕ кэшируются — исправленный адрес можно повторить.
    """

    def __init__(self, inner: MapsProvider) -> None:
        self.inner = inner

    def geocode(self, address: str) -> GeocodeResult | None:
        key = normalize_address(address)
        if not key:
            return None

        cached = GeocodeCache.objects.filter(normalized_address=key).first()
        if cached is not None:
            return GeocodeResult(cached.lat, cached.lng, cached.formatted_address)

        result = self.inner.geocode(address)
        if result is not None:
            GeocodeCache.objects.update_or_create(
                normalized_address=key,
                defaults={
                    "lat": result.lat,
                    "lng": result.lng,
                    "formatted_address": result.formatted_address,
                },
            )
        return result
