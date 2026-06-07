"""Фабрики провайдеров — единая точка выбора реализации (свап вендора/фейка в тестах)."""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from .base import MapsProvider, MessagingProvider, RoutesProvider
from .cache import CachingMapsProvider
from .chained import ChainedMessagingProvider
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


def _default_chain_paths() -> list[str]:
    """Дефолтная цепочка из legacy-настроек Infobip — повторяет прежнее поведение.

    `INFOBIP_CHANNEL=sms` → только [Sms]; иначе [Viber] + [Sms] если SMS-fallback включён.
    """
    if getattr(settings, "INFOBIP_CHANNEL", "viber") == "sms":
        return ["integrations.infobip.SmsProvider"]
    chain = ["integrations.infobip.ViberProvider"]
    if getattr(settings, "INFOBIP_SMS_FALLBACK", True):
        chain.append("integrations.infobip.SmsProvider")
    return chain


def _build_messaging_chain() -> MessagingProvider:
    """Собирает MessagingProvider из настроек.

    Приоритет: явный одиночный `MESSAGING_PROVIDER` (обратная совместимость / тесты) →
    используется напрямую. Иначе — `ChainedMessagingProvider` из `MESSAGING_CHAIN`
    (или дефолтной цепочки, повторяющей legacy Viber→SMS).
    """
    single = getattr(settings, "MESSAGING_PROVIDER", "")
    if single:
        return import_string(single)()
    paths = getattr(settings, "MESSAGING_CHAIN", None) or _default_chain_paths()
    return ChainedMessagingProvider([import_string(p)() for p in paths])


def get_messaging_provider() -> MessagingProvider:
    """MessagingProvider по настройкам, со счётчиком по фактическому каналу.

    Прод-путь — цепочка одно-канальных провайдеров (`MESSAGING_CHAIN`, дефолт Viber→SMS),
    обёрнутая `MeteringMessagingProvider`. Одиночный `MESSAGING_PROVIDER` имеет приоритет
    (тесты/legacy-свап вендора)."""
    provider = _build_messaging_chain()
    if _metering_on():
        provider = MeteringMessagingProvider(provider)
    return provider
