"""Время Europe/Belgrade: форматирование ETA + окно рассылки 08:00–22:00 (FR-16)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

BELGRADE = ZoneInfo("Europe/Belgrade")
WINDOW_START = time(8, 0)
WINDOW_END = time(22, 0)
RATING_DELAY = timedelta(minutes=30)


def format_eta(dt: datetime) -> str:
    """UTC-datetime → «HH:MM» в Europe/Belgrade (верхняя граница ETA)."""
    return dt.astimezone(BELGRADE).strftime("%H:%M")


def format_eta_label(dt: datetime, now: datetime | None = None) -> str:
    """ETA для людей (SERBITO-356): «14:00» сегодня, иначе с датой — «03.10. 14:00».

    Одно время без даты врёт, когда ETA не сегодня (после полуночи, завтра) или уже прошло.
    """
    from django.utils import timezone

    local = dt.astimezone(BELGRADE)
    today = (now or timezone.now()).astimezone(BELGRADE).date()
    if local.date() == today:
        return local.strftime("%H:%M")
    return local.strftime("%d.%m. %H:%M")


def clamp_to_window(dt: datetime) -> datetime:
    """Сдвигает время в окно 08:00–22:00 (Europe/Belgrade); возвращает aware-datetime.

    До 08:00 → 08:00 того же дня; в 22:00 и позже → 08:00 следующего дня.
    """
    local = dt.astimezone(BELGRADE)
    if local.time() < WINDOW_START:
        local = local.replace(hour=8, minute=0, second=0, microsecond=0)
    elif local.time() >= WINDOW_END:
        local = (local + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return local


def rating_send_time(eta_at: datetime) -> datetime:
    """Когда слать запрос оценки: ETA+30 мин, прижатое к окну рассылки."""
    return clamp_to_window(eta_at + RATING_DELAY)
