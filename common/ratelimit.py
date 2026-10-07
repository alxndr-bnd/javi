"""Fixed-window counters in the database (SERBITO-362).

The Django cache here is per-process memory: two gunicorn workers count separately and a
Cloud Run cold start (min-instances=0) forgets everything, so a slow attacker would never hit
a limit. Counters live in the DB instead: one row per (scope, identity, window), keyed by a
hash so raw IPs and emails are not stored. Expired rows are removed when a new window starts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import RateLimitCounter


@dataclass(frozen=True)
class Window:
    key: str
    expires_at: datetime


def _window(scope: str, ident: str, window_seconds: int, now: datetime) -> Window:
    index = int(now.timestamp()) // window_seconds
    raw = f"{scope}\0{ident}\0{window_seconds}\0{index}"
    return Window(
        key=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=datetime.fromtimestamp((index + 1) * window_seconds, UTC),
    )


def hit(scope: str, ident: str, *, limit: int, window_seconds: int) -> bool:
    """Count one event. True while the window's count stays within `limit`."""
    now = timezone.now()
    window = _window(scope, ident, window_seconds, now)
    with transaction.atomic():
        counter, created = RateLimitCounter.objects.get_or_create(
            key=window.key, defaults={"expires_at": window.expires_at}
        )
        RateLimitCounter.objects.filter(pk=counter.pk).update(count=F("count") + 1)
    if created:
        RateLimitCounter.objects.filter(expires_at__lt=now).delete()
    counter.refresh_from_db(fields=["count"])
    return counter.count <= limit


def exceeded(scope: str, ident: str, *, limit: int, window_seconds: int) -> bool:
    """True if the current window already has `limit` events (does not count one)."""
    window = _window(scope, ident, window_seconds, timezone.now())
    count = RateLimitCounter.objects.filter(key=window.key).values_list("count", flat=True).first()
    return (count or 0) >= limit
