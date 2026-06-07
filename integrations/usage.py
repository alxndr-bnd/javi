"""Сводка остатка бесплатных квот (Viber / SMS / Maps) — глобально, account-wide.

Источник — наши же счётчики реальных вызовов (`ProviderUsage`). Магазины получают только
агрегат (used/limit/remaining), без доступа к провайдерам. Результат кэшируется на 60 с,
чтобы не дёргать БД на каждом рендере кабинета.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import (
    METRIC_MAPS_GEOCODE,
    METRIC_MAPS_ROUTE,
    METRIC_SMS,
    METRIC_VIBER,
    ProviderUsage,
    usage_period,
)

_CACHE_KEY = "free_quota_summary_v1"
_CACHE_TTL = 60


def _buckets():
    """Отображаемые бакеты квот. `window`: monthly (помесячный сброс) | lifetime."""
    return [
        {
            "key": "viber",
            "label": _("Viber"),
            "metrics": [METRIC_VIBER],
            "window": "lifetime",
            "limit": settings.FREE_QUOTA_VIBER,
        },
        {
            "key": "sms",
            "label": _("SMS"),
            "metrics": [METRIC_SMS],
            "window": "lifetime",
            "limit": settings.FREE_QUOTA_SMS,
        },
        {
            "key": "maps",
            "label": _("Maps"),
            "metrics": [METRIC_MAPS_GEOCODE, METRIC_MAPS_ROUTE],
            "window": "monthly",
            "limit": settings.FREE_QUOTA_MAPS,
        },
    ]


def _used(metrics, window, now) -> int:
    qs = ProviderUsage.objects.filter(metric__in=metrics)
    if window == "monthly":
        qs = qs.filter(period=usage_period(now))
    return qs.aggregate(total=Sum("count"))["total"] or 0


def quota_summary(now=None, *, use_cache: bool = True) -> list[dict]:
    """Список бакетов с used/limit/remaining/pct. limit<=0 → безлимит (remaining=None)."""
    live = now is None  # «живой» вызов без явного времени — только его и кэшируем
    if use_cache and live:
        cached = cache.get(_CACHE_KEY)
        if cached is not None:
            return cached

    now = now or timezone.now()
    out = []
    for b in _buckets():
        used = _used(b["metrics"], b["window"], now)
        limit = b["limit"]
        unlimited = not limit or limit <= 0
        remaining = None if unlimited else max(0, limit - used)
        pct = None if unlimited else min(100, round(used * 100 / limit))
        out.append(
            {
                "key": b["key"],
                "label": b["label"],
                "window": b["window"],
                "used": used,
                "limit": limit,
                "remaining": remaining,
                "pct": pct,
            }
        )

    if use_cache and live:
        cache.set(_CACHE_KEY, out, _CACHE_TTL)
    return out
