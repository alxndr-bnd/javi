"""Реализация MapsProvider поверх Google Geocoding API."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import GeocodeResult, MapsProvider

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
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
