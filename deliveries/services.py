"""Бизнес-логика deliveries. Views тонкие — вся логика здесь."""

from __future__ import annotations

from common.phone import PhoneResult
from integrations.providers import get_maps_provider

from .models import Delivery, Shop


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


def create_delivery(
    shop: Shop,
    *,
    recipient_name: str,
    phone: PhoneResult,
    dest_address: str,
    description: str = "",
) -> tuple[Delivery, bool]:
    """Создаёт доставку дня. Геокодит адрес; при неудаче создаёт без координат (FR-5/9).

    Возвращает (delivery, geocoded_ok). Поток не блокируется на сбое геокода.
    """
    geo = get_maps_provider().geocode(dest_address)
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name=recipient_name,
        recipient_phone=phone.e164,
        phone_risk=phone.is_risky,
        dest_address=geo.formatted_address if geo else dest_address,
        dest_lat=geo.lat if geo else None,
        dest_lng=geo.lng if geo else None,
        description=description,
    )
    return delivery, geo is not None
