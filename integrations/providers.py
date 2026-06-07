"""Фабрики провайдеров — единая точка выбора реализации (свап вендора/фейка в тестах)."""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from .base import MapsProvider, MessagingProvider, RoutesProvider
from .cache import CachingMapsProvider
from .metering import MeteringMapsProvider, MeteringMessagingProvider, MeteringRoutesProvider


def _metering_on() -> bool:
    return getattr(settings, "USAGE_METERING_ENABLED", True)


def get_maps_provider() -> MapsProvider:
    """MapsProvider по `settings.MAPS_PROVIDER`. Порядок Caching(Metering(real)) —
    кэш-хит не доходит до счётчика, считаются только реальные вызовы геокодинга."""
    provider = import_string(settings.MAPS_PROVIDER)()
    if _metering_on():
        provider = MeteringMapsProvider(provider)
    return CachingMapsProvider(provider)


def get_routes_provider() -> RoutesProvider:
    """RoutesProvider (ETA) по `settings.ROUTES_PROVIDER`, со счётчиком квоты Maps Routes."""
    provider = import_string(settings.ROUTES_PROVIDER)()
    if _metering_on():
        provider = MeteringRoutesProvider(provider)
    return provider


def get_messaging_provider() -> MessagingProvider:
    """MessagingProvider (Infobip) по `settings.MESSAGING_PROVIDER`, со счётчиком Viber/SMS."""
    provider = import_string(settings.MESSAGING_PROVIDER)()
    if _metering_on():
        provider = MeteringMessagingProvider(provider)
    return provider
