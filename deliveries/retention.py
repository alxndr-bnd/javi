"""SERBITO-467: retention and purge of recipient personal data (ZZPL, data minimisation).

Recipients never signed up with Javi, so we keep their data only while a delivery needs it.
`purge_recipient_pii` erases it RECIPIENT_PII_RETENTION_DAYS after the delivery is final:

- Delivery: recipient name, phone, address and coordinates become empty. Status, rating,
  dates, city, language and source stay, so shop stats and ratings keep working.
  `pii_purged_at` marks the row, so a second run skips it (idempotent).
- TrackingToken of a purged delivery: deleted (the /t/ link shows "expired").
- OutboundSend (send log): the phone becomes empty. Limits per phone use one day only.
- GeocodeCache: entries older than the limit are deleted (the key is a normalised address).

Kept on purpose: OptOut (an opt-out must keep blocking sends) and TelegramContact (the
recipient's own opt-in). Logs carry counts only, never the data.

When is a delivery final? Deleted: from `deleted_at`. Otherwise from `delivered_at`; for a
delivery never marked delivered (or delivered before `delivered_at` existed), from its last
known time: ETA, start or creation. A delivery not touched for the whole period is over.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.db.models.functions import Coalesce
from django.utils import timezone

from integrations.models import GeocodeCache
from notifications.models import OutboundSend

from .models import Delivery, TrackingToken

logger = logging.getLogger(__name__)


@dataclass
class PurgeResult:
    deliveries: int = 0
    tracking_tokens: int = 0
    outbound_phones: int = 0
    geocode_entries: int = 0
    complete: bool = True  # False: the time budget ran out; the next run continues

    def as_dict(self) -> dict:
        return asdict(self)


def retention_cutoff(now: datetime | None = None) -> datetime:
    now = now or timezone.now()
    return now - timedelta(days=settings.RECIPIENT_PII_RETENTION_DAYS)


def deliveries_due(cutoff: datetime) -> QuerySet[Delivery]:
    """Deliveries whose recipient data is past the retention limit and not erased yet."""
    final_at = Coalesce("delivered_at", "eta_at", "started_at", "created_at")
    return (
        Delivery.objects.filter(pii_purged_at__isnull=True)
        .annotate(final_at=final_at)
        .filter(
            Q(deleted_at__lt=cutoff) | Q(deleted_at__isnull=True, final_at__lt=cutoff),
        )
    )


def _outbound_due(cutoff: datetime) -> QuerySet[OutboundSend]:
    return OutboundSend.objects.filter(created_at__lt=cutoff).exclude(phone="")


def _geocode_due(cutoff: datetime) -> QuerySet[GeocodeCache]:
    return GeocodeCache.objects.filter(created_at__lt=cutoff)


def _ids(qs: QuerySet, batch_size: int) -> list[int]:
    return list(qs.order_by("pk").values_list("pk", flat=True)[:batch_size])


def purge_recipient_pii(
    *,
    apply: bool,
    now: datetime | None = None,
    batch_size: int | None = None,
    time_budget: float | None = None,
) -> PurgeResult:
    """Erase recipient data past the retention limit, in batches. Idempotent.

    apply=False (dry run) only counts what a real run would change. `time_budget` (seconds)
    stops between batches — an HTTP call has a timeout; the next run continues where this
    one stopped (`complete=False`).
    """
    now = now or timezone.now()
    cutoff = retention_cutoff(now)
    batch_size = batch_size or settings.RECIPIENT_PII_PURGE_BATCH_SIZE
    result = PurgeResult()

    if not apply:
        due = deliveries_due(cutoff)
        result.deliveries = due.count()
        result.tracking_tokens = TrackingToken.objects.filter(delivery__in=due.values("pk")).count()
        result.outbound_phones = _outbound_due(cutoff).count()
        result.geocode_entries = _geocode_due(cutoff).count()
        logger.info("recipient PII purge (dry run): %s", result.as_dict())
        return result

    deadline = time.monotonic() + time_budget if time_budget else None

    def out_of_time() -> bool:
        if deadline is not None and time.monotonic() >= deadline:
            result.complete = False
            return True
        return False

    while not out_of_time():
        ids = _ids(deliveries_due(cutoff), batch_size)
        if not ids:
            break
        with transaction.atomic():
            result.tracking_tokens += TrackingToken.objects.filter(delivery_id__in=ids).delete()[0]
            result.deliveries += Delivery.objects.filter(pk__in=ids).update(
                recipient_name="",
                recipient_phone="",
                dest_address="",
                dest_lat=None,
                dest_lng=None,
                pii_purged_at=now,
            )

    while not out_of_time():
        ids = _ids(_outbound_due(cutoff), batch_size)
        if not ids:
            break
        result.outbound_phones += OutboundSend.objects.filter(pk__in=ids).update(phone="")

    while not out_of_time():
        ids = _ids(_geocode_due(cutoff), batch_size)
        if not ids:
            break
        result.geocode_entries += GeocodeCache.objects.filter(pk__in=ids).delete()[0]

    logger.info("recipient PII purge: %s", result.as_dict())
    return result
