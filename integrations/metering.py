"""Учёт расхода квот: тонкие обёртки над провайдерами, считают РЕАЛЬНЫЕ вызовы.

Метеринг ставится на границе провайдера, поэтому в счётчик попадают только настоящие
вызовы, жгущие квоту: кэш-хиты геокодинга сюда не доходят (обёртка — внутри кэша), а
Viber→SMS fallback считается тем каналом, которым реально ушло сообщение.
"""

from __future__ import annotations

from .base import GeocodeResult, MapsProvider, MessagingProvider, RoutesProvider, SendResult
from .models import (
    MESSAGING_METRICS,
    METRIC_MAPS_GEOCODE,
    METRIC_MAPS_ROUTE,
    ProviderUsage,
)


class MeteringMapsProvider(MapsProvider):
    """Считает каждый реальный вызов геокодинга (квота Maps)."""

    def __init__(self, inner: MapsProvider) -> None:
        self.inner = inner

    def geocode(self, address: str) -> GeocodeResult | None:
        ProviderUsage.record(METRIC_MAPS_GEOCODE)
        return self.inner.geocode(address)


class MeteringRoutesProvider(RoutesProvider):
    """Считает каждый вызов расчёта маршрута/ETA (квота Maps Routes)."""

    def __init__(self, inner: RoutesProvider) -> None:
        self.inner = inner

    def route_duration_seconds(self, *args, **kwargs) -> int | None:
        ProviderUsage.record(METRIC_MAPS_ROUTE)
        return self.inner.route_duration_seconds(*args, **kwargs)


class MeteringMessagingProvider(MessagingProvider):
    """Считает успешную отправку по фактическому каналу (viber|sms)."""

    def __init__(self, inner: MessagingProvider) -> None:
        self.inner = inner

    def send_text(self, to_e164: str, text: str) -> SendResult:
        result = self.inner.send_text(to_e164, text)
        if result.ok and result.channel in MESSAGING_METRICS:
            ProviderUsage.record(result.channel)
        return result
