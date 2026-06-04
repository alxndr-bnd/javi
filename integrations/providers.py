"""Фабрика провайдеров — единая точка выбора реализации (свап вендора/фейка в тестах)."""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from .base import MapsProvider
from .cache import CachingMapsProvider


def get_maps_provider() -> MapsProvider:
    """Возвращает MapsProvider по `settings.MAPS_PROVIDER`, обёрнутый кэшем геокодинга."""
    provider = import_string(settings.MAPS_PROVIDER)()
    return CachingMapsProvider(provider)
