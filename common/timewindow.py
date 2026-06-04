"""Время Europe/Belgrade: форматирование ETA. Окно рассылки 08:00–22:00 — Story 3.1."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BELGRADE = ZoneInfo("Europe/Belgrade")


def format_eta(dt: datetime) -> str:
    """UTC-datetime → «HH:MM» в Europe/Belgrade (верхняя граница ETA)."""
    return dt.astimezone(BELGRADE).strftime("%H:%M")
