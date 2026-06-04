"""Фейк-провайдеры карт для тестов (без реальной сети). Подключаются через MAPS_PROVIDER."""

from __future__ import annotations

from .base import GeocodeResult, MapsProvider, MessagingProvider, RoutesProvider, SendResult


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


class FakeRoutesProvider(RoutesProvider):
    """Возвращает фиксированное время в пути (по умолчанию 900 c = 15 мин)."""

    seconds = 900

    def route_duration_seconds(self, origin, dest) -> int | None:
        return self.seconds


class FailingRoutesProvider(RoutesProvider):
    """Маршрут недоступен → None (ветка ручного ETA)."""

    def route_duration_seconds(self, origin, dest) -> int | None:
        return None


class FakeMessagingProvider(MessagingProvider):
    """Записывает отправки в класс-уровневый список; всегда ok (если ok=True)."""

    ok = True
    sent: list[tuple[str, str]] = []

    def send_text(self, to_e164: str, text: str) -> SendResult:
        type(self).sent.append((to_e164, text))
        return SendResult(ok=self.ok, provider_message_id="fake-msg-1" if self.ok else None)


class FailingMessagingProvider(MessagingProvider):
    """Сбой отправки → ok=False."""

    def send_text(self, to_e164: str, text: str) -> SendResult:
        return SendResult(ok=False)
