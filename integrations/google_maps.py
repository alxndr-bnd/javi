"""Реализация MapsProvider поверх Google Geocoding API."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import GeocodeResult, MapsProvider, RoutesProvider

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
DEFAULT_TIMEOUT = 5  # секунд


class GoogleMapsProvider(MapsProvider):
    """Геокодинг через Google Geocoding API (регион RS, sr-латиница)."""

    def __init__(self, api_key: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.api_key = api_key if api_key is not None else settings.GOOGLE_MAPS_API_KEY
        self.timeout = timeout

    def geocode(self, address: str) -> GeocodeResult | None:
        if not self.api_key:
            logger.error("GOOGLE_MAPS_API_KEY не задан — геокодинг отключён")
            return None

        params = {
            "address": address,
            "key": self.api_key,
            "region": "rs",
            "language": "sr-Latn",
        }
        try:
            resp = requests.get(GEOCODE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            # Не логируем params (там ключ) — только тип/сообщение ошибки.
            logger.error("Geocoding request failed: %s", exc)
            return None

        status = data.get("status")
        results = data.get("results") or []
        if status != "OK" or not results:
            # ZERO_RESULTS — штатный «не распознан»; остальные не-OK = ошибка конфигурации/квоты.
            if status != "ZERO_RESULTS":
                logger.error("Geocoding returned status=%s", status)
            return None

        top = results[0]
        location = top["geometry"]["location"]
        return GeocodeResult(
            lat=location["lat"],
            lng=location["lng"],
            formatted_address=top["formatted_address"],
        )


class GoogleRoutesProvider(RoutesProvider):
    """ETA через Google Routes API (computeRoutes, TRAFFIC_AWARE)."""

    def __init__(self, api_key: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.api_key = api_key if api_key is not None else settings.GOOGLE_MAPS_API_KEY
        self.timeout = timeout

    def route_duration_seconds(
        self, origin: tuple[float, float], dest: tuple[float, float]
    ) -> int | None:
        if not self.api_key:
            logger.error("GOOGLE_MAPS_API_KEY не задан — расчёт ETA отключён")
            return None

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.duration",
        }
        body = {
            "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
            "destination": {"location": {"latLng": {"latitude": dest[0], "longitude": dest[1]}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        try:
            resp = requests.post(ROUTES_URL, json=body, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("Routes request failed: %s", exc)
            return None

        routes = data.get("routes") or []
        if not routes:
            logger.error("Routes returned no routes")
            return None
        duration = routes[0].get("duration")  # напр. "845s"
        if not duration or not duration.endswith("s"):
            logger.error("Routes returned unexpected duration=%r", duration)
            return None
        try:
            return int(duration[:-1])
        except ValueError:
            logger.error("Cannot parse duration=%r", duration)
            return None
