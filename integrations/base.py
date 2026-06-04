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
