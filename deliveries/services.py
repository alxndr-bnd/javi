"""Бизнес-логика deliveries. Views тонкие — вся логика здесь."""

from __future__ import annotations

from integrations.providers import get_maps_provider

from .models import Shop


def set_shop_origin(shop: Shop, raw_address: str) -> bool:
    """Геокодит адрес и сохраняет origin магазина.

    Успех → сохраняет formatted-адрес + координаты, возвращает True.
    Сбой/не распознан → НЕ трогает существующий origin, возвращает False
    (origin без координат бесполезен для ETA — просим исправить).
    """
    provider = get_maps_provider()
    result = provider.geocode(raw_address)
    if result is None:
        return False

    shop.origin_address = result.formatted_address
    shop.origin_lat = result.lat
    shop.origin_lng = result.lng
    shop.save(update_fields=["origin_address", "origin_lat", "origin_lng"])
    return True
