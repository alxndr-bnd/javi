"""Интерфейсы провайдеров (изоляция вендоров). Домен зовёт только эти абстракции."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GeocodeResult:
    """Результат геокодинга: координаты + нормализованный (formatted) адрес."""

    lat: float
    lng: float
    formatted_address: str


class MapsProvider(ABC):
    """Провайдер карт. В Story 1.2 нужен только geocode; ETA (Routes) — Epic 2."""

    @abstractmethod
    def geocode(self, address: str) -> GeocodeResult | None:
        """Адрес → координаты. None = не распознан или сбой провайдера (мягкая деградация)."""
        raise NotImplementedError


class RoutesProvider(ABC):
    """Провайдер маршрутов (ETA). Время в пути origin→dest с учётом трафика."""

    @abstractmethod
    def route_duration_seconds(
        self, origin: tuple[float, float], dest: tuple[float, float]
    ) -> int | None:
        """(lat,lng)×2 → секунды в пути. None = маршрут недоступен (fallback на ручной ETA)."""
        raise NotImplementedError


@dataclass(frozen=True)
class SendResult:
    """Результат отправки сообщения провайдером."""

    ok: bool
    provider_message_id: str | None = None


class MessagingProvider(ABC):
    """Провайдер сообщений (Viber/SMS через Infobip)."""

    @abstractmethod
    def send_text(self, to_e164: str, text: str) -> SendResult:
        """Отправить текст на номер E.164. ok=False при сбое (без исключения наружу)."""
        raise NotImplementedError
