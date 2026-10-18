"""Shop billing rules (SERBITO-593): trial, status, access, Whop checkout and webhook sync.

Rules (owner decision 2026-10-09):

* 30 € per shop per month, a Whop subscription on the same Whop business as serbito.
* 30 days free from registration, no card. Shops that exist before billing goes live start
  their trial on ``JAVI_BILLING_START_DATE`` instead (computed, no data change).
* After the trial, an unpaid shop gets the unverified-shop limits (notifications/quotas.py).
* Everything is behind ``JAVI_BILLING_ENABLED`` (default off): off means no billing UI and no
  billing limits. The webhook still records Whop events, so the state is right when it is on.

A shop that subscribes during its trial is not charged before the trial ends: the Whop plan
gets the remaining trial days as ``trial_period_days``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from deliveries.models import Shop

from . import whop
from .models import BillingPayment, ShopSubscription

logger = logging.getLogger(__name__)

Status = ShopSubscription.Status

#: Whop membership status → our status. ``drafted`` (checkout not finished) changes nothing.
WHOP_STATUS_MAP = {
    "trialing": Status.ACTIVE,  # subscribed; Whop charges when our free trial ends
    "active": Status.ACTIVE,
    "canceling": Status.ACTIVE,  # canceled at period end: paid until then
    "past_due": Status.PAST_DUE,
    "unresolved": Status.PAST_DUE,
    "canceled": Status.CANCELED,
    "expired": Status.CANCELED,
    "completed": Status.CANCELED,
}

WHOP_PAID = "paid"

_missing_start_logged = False


class BillingError(Exception):
    """A checkout cannot start. The message is for logs, not for the shop."""


# ---- settings ----------------------------------------------------------------------------


def enabled() -> bool:
    return bool(getattr(settings, "JAVI_BILLING_ENABLED", False))


def trial_days() -> int:
    return int(getattr(settings, "JAVI_BILLING_TRIAL_DAYS", 30))


def price() -> Decimal:
    return Decimal(str(getattr(settings, "JAVI_BILLING_PRICE", "30.00")))


def currency() -> str:
    return str(getattr(settings, "JAVI_BILLING_CURRENCY", "EUR")).upper()


def period_days() -> int:
    return int(getattr(settings, "JAVI_BILLING_PERIOD_DAYS", 30))


def fee_rate() -> Decimal:
    return Decimal(str(getattr(settings, "JAVI_BILLING_FEE_RATE", "0.17")))


def past_due_grace() -> timedelta:
    return timedelta(days=int(getattr(settings, "JAVI_BILLING_PAST_DUE_GRACE_DAYS", 7)))


def start_date() -> date | None:
    """The day billing went live. Older shops start their trial on this day."""
    value = str(getattr(settings, "JAVI_BILLING_START_DATE", "") or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        # The value itself stays out of the log: settings values are never logged (SERBITO-638).
        logger.error("billing: JAVI_BILLING_START_DATE is not YYYY-MM-DD")
        return None


def _start_datetime() -> datetime | None:
    day = start_date()
    if day is None:
        return None
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_default_timezone())


def enforced() -> bool:
    """Billing limits apply: the flag is on and the start date is set.

    Without the start date every existing shop would lose its trial at once, so the limits
    stay off and an ERROR says why (fail open, as before billing).
    """
    global _missing_start_logged
    if not enabled():
        return False
    if start_date() is None:
        if not _missing_start_logged:
            _missing_start_logged = True
            logger.error(
                "billing: JAVI_BILLING_ENABLED is on, but JAVI_BILLING_START_DATE is not set — "
                "billing limits are off"
            )
        return False
    return True


# ---- state -------------------------------------------------------------------------------


def subscription_of(shop: Shop) -> ShopSubscription | None:
    try:
        return shop.subscription
    except ShopSubscription.DoesNotExist:
        return None


def trial_ends_at(shop: Shop) -> datetime:
    """Registration (or the billing start date, if later) + the trial days."""
    sub = subscription_of(shop)
    if sub is not None and sub.trial_ends_override:
        return sub.trial_ends_override
    start = shop.created_at or timezone.now()
    go_live = _start_datetime()
    if go_live is not None and go_live > start:
        start = go_live
    return start + timedelta(days=trial_days())


def shop_status(shop: Shop) -> str:
    sub = subscription_of(shop)
    return sub.status if sub is not None else Status.TRIAL


def has_access(shop: Shop, now: datetime | None = None) -> bool:
    """True when billing does not restrict the shop: paid, in trial, or billing not enforced."""
    if not enforced():
        return True
    now = now or timezone.now()
    sub = subscription_of(shop)
    status = sub.status if sub is not None else Status.TRIAL
    if status == Status.ACTIVE:
        return True
    if status == Status.PAST_DUE:
        since = (sub.past_due_since if sub else None) or now
        return now < since + past_due_grace()
    # trial or canceled: the free trial still counts.
    return now < trial_ends_at(shop)


def trial_days_left(shop: Shop, now: datetime | None = None) -> int:
    now = now or timezone.now()
    seconds = (trial_ends_at(shop) - now).total_seconds()
    return max(0, math.ceil(seconds / 86400))


@dataclass(frozen=True)
class Summary:
    """What the store profile shows."""

    status: str
    has_access: bool
    trial_ends_at: datetime
    trial_days_left: int
    price: Decimal
    currency: str
    current_period_end: datetime | None
    cancel_at_period_end: bool
    manage_url: str
    can_subscribe: bool


def summary(shop: Shop, now: datetime | None = None) -> Summary | None:
    """Billing block of the store profile, or None when billing is off."""
    if not enabled():
        return None
    now = now or timezone.now()
    sub = subscription_of(shop)
    status = shop_status(shop)
    return Summary(
        status=status,
        has_access=has_access(shop, now),
        trial_ends_at=trial_ends_at(shop),
        trial_days_left=trial_days_left(shop, now),
        price=price(),
        currency=currency(),
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
        manage_url=sub.manage_url if sub else "",
        can_subscribe=status in (Status.TRIAL, Status.CANCELED),
    )


# ---- checkout ----------------------------------------------------------------------------


def start_checkout(shop: Shop, now: datetime | None = None) -> str:
    """Create a Whop checkout for the shop and return its URL. Raises BillingError.

    An inline renewal plan on the javi product: ``renewal_price`` per ``billing_period`` days,
    no extra first charge, and the rest of the free trial as ``trial_period_days``.
    """
    if not enabled():
        raise BillingError("billing is off")
    if not whop.is_configured():
        raise BillingError(f"Whop is not configured: {', '.join(whop.missing_settings())}")
    now = now or timezone.now()
    left = trial_days_left(shop, now)
    plan: dict[str, object] = {
        "plan_type": "renewal",
        "initial_price": 0,
        "renewal_price": float(price()),
        "billing_period": period_days(),
        "currency": currency().lower(),
        "title": f"Javi — {price():.0f} € / month"[:80],
        "visibility": "hidden",
        "force_create_new_plan": True,
        "account_id": whop.company_id(),
        "product_id": whop.product_id(),
    }
    if left > 0:
        plan["trial_period_days"] = left
    payload = {
        "account_id": whop.company_id(),
        "plan": plan,
        "metadata": {"shop_id": str(shop.pk), "shop_token": whop.shop_token(shop.pk)},
        "redirect_url": settings.PUBLIC_BASE_URL.rstrip("/") + reverse("billing:return"),
    }
    try:
        body = whop.api_request(
            "POST",
            "/checkout_configurations",
            payload=payload,
            idempotency_key=f"javi-sub-{shop.pk}-{now:%Y%m%d}-{left}",
        )
    except whop.WhopError as exc:
        raise BillingError(str(exc)) from exc
    url = whop.is_whop_url(body.get("purchase_url"))
    if not url:
        raise BillingError("Whop returned a checkout without a Whop purchase URL")
    sub, _ = ShopSubscription.objects.get_or_create(shop=shop)
    sub.whop_checkout_id = str(body.get("id") or "")[:64]
    sub.save(update_fields=["whop_checkout_id", "updated_at"])
    logger.info(
        "billing: checkout %s for shop %s (trial days %s)", sub.whop_checkout_id, shop.pk, left
    )
    return url


# ---- webhook and sync --------------------------------------------------------------------


def is_ours(data: dict) -> bool:
    """Same Whop business and the javi product. Serbito payments fail the product check."""
    account = whop.account_of(data)
    if account and account != whop.company_id():
        return False
    product = whop.product_of(data)
    return not (product and product != whop.product_id())


def _shop_from_metadata(data: dict) -> Shop | None:
    meta = whop.metadata_of(data)
    shop_id = str(meta.get("shop_id") or "")
    if not shop_id.isdigit() or not whop.token_is_valid(shop_id, meta.get("shop_token")):
        return None
    return Shop.objects.filter(pk=int(shop_id)).first()


def find_shop(data: dict, *, membership_id: str = "") -> Shop | None:
    """The shop of a Whop membership or payment: metadata token, membership id, checkout id."""
    shop = _shop_from_metadata(data)
    if shop is not None:
        return shop
    if membership_id:
        sub = ShopSubscription.objects.filter(whop_membership_id=membership_id).first()
        if sub is not None:
            return sub.shop
    checkout = str(data.get("checkout_configuration_id") or "")
    if checkout:
        sub = ShopSubscription.objects.filter(whop_checkout_id=checkout).first()
        if sub is not None:
            return sub.shop
    return None


def apply_membership(data: dict, *, origin: str, now: datetime | None = None):
    """Store a Whop membership on its shop. Returns the subscription, or None if not ours."""
    membership_id = str(data.get("id") or "")
    if not membership_id.startswith("mem_") or not is_ours(data):
        return None
    shop = find_shop(data, membership_id=membership_id)
    if shop is None:
        logger.warning("%s: Whop membership %s matches no shop", origin, membership_id)
        return None
    whop_status = str(data.get("status") or "")
    new_status = WHOP_STATUS_MAP.get(whop_status)
    now = now or timezone.now()
    with transaction.atomic():
        sub, _ = ShopSubscription.objects.select_for_update().get_or_create(shop=shop)
        if sub.whop_membership_id and sub.whop_membership_id != membership_id:
            # A second membership (e.g. a new subscription after a cancel). The live one wins.
            if new_status != Status.ACTIVE and sub.status == Status.ACTIVE:
                logger.info(
                    "%s: old membership %s ignored for shop %s", origin, membership_id, shop.pk
                )
                return sub
        sub.whop_membership_id = membership_id
        sub.whop_status = whop_status[:20]
        sub.manage_url = whop.is_whop_url(data.get("manage_url"))[:500]
        sub.current_period_end = whop.when(data.get("renewal_period_end"))
        sub.cancel_at_period_end = bool(data.get("cancel_at_period_end"))
        if checkout := str(data.get("checkout_configuration_id") or ""):
            sub.whop_checkout_id = checkout[:64]
        if new_status is not None and new_status != sub.status:
            logger.info(
                "%s: shop %s %s -> %s (Whop %s)",
                origin,
                shop.pk,
                sub.status,
                new_status,
                whop_status,
            )
            sub.status = new_status
        if sub.status == Status.ACTIVE:
            sub.activated_at = sub.activated_at or now
            sub.past_due_since = None
        elif sub.status == Status.PAST_DUE:
            sub.past_due_since = sub.past_due_since or now
        elif sub.status == Status.CANCELED:
            sub.canceled_at = whop.when(data.get("canceled_at")) or sub.canceled_at or now
            sub.past_due_since = None
        sub.save()
    return sub


def sync_membership(membership_id: str, *, origin: str, fallback: dict | None = None):
    """Read the membership from Whop (events can arrive out of order) and store it.

    On a read error the event data is used, when there is one.
    """
    data = fallback
    if whop.api_key():
        try:
            data = whop.get_membership(membership_id, timeout=4)
        except whop.WhopError as exc:
            logger.warning("%s: membership %s read failed: %s", origin, membership_id, exc)
    if not data:
        return None
    return apply_membership(data, origin=origin)


def charged(payment: dict) -> tuple[Decimal | None, str]:
    """``(amount, currency)`` before tax, in the checkout currency (serbito's rule).

    Native shape: ``line_items[].subtotal`` money objects, else ``presentment_total``.
    Stable shape: bare ``subtotal`` in the top-level ``currency``.
    """
    items = payment.get("line_items")
    if isinstance(items, list) and items:
        subtotals = [
            i["subtotal"]
            for i in items
            if isinstance(i, dict) and isinstance(i.get("subtotal"), dict)
        ]
        if subtotals and len(subtotals) == len(items):
            currencies = {str(x.get("currency") or "").upper() for x in subtotals}
            amounts = [whop.money(x) for x in subtotals]
            if len(currencies) == 1 and all(a is not None for a in amounts):
                return sum(amounts, Decimal(0)), currencies.pop()
    presented = payment.get("presentment_total")
    if isinstance(presented, dict) and presented.get("currency"):
        return whop.money(presented), str(presented["currency"]).upper()
    value = payment.get("subtotal")
    if isinstance(value, dict) and value.get("currency"):
        return whop.money(value), str(value["currency"]).upper()
    return whop.money(value), str(payment.get("currency") or "").upper()


def record_payment(data: dict, *, origin: str):
    """Store a paid Whop payment of a shop subscription. Returns it, or None if not ours."""
    payment_id = str(data.get("id") or "")
    if not payment_id.startswith("pay_") or not is_ours(data):
        return None
    if str(data.get("status") or "") != WHOP_PAID:
        return None
    membership_id = whop.membership_of(data)
    shop = find_shop(data, membership_id=membership_id)
    if shop is None:
        logger.info("%s: Whop payment %s is not a javi subscription", origin, payment_id)
        return None
    amount, cur = charged(data)
    if amount is None or not cur:
        logger.error("%s: Whop payment %s has no readable amount", origin, payment_id)
        return None
    payment, created = BillingPayment.objects.update_or_create(
        whop_payment_id=payment_id,
        defaults={
            "shop": shop,
            "whop_membership_id": membership_id[:64],
            "amount": amount,
            "currency": cur[:3],
            "refunded_amount": whop.money(data.get("refunded_amount")) or Decimal(0),
            "billing_reason": str(data.get("billing_reason") or "")[:40],
            "paid_at": whop.when(data.get("paid_at")) or timezone.now(),
        },
    )
    if created:
        logger.info("%s: shop %s paid %s %s (%s)", origin, shop.pk, amount, cur, payment_id)
    if membership_id:
        sub, _ = ShopSubscription.objects.get_or_create(shop=shop)
        if not sub.whop_membership_id:
            sub.whop_membership_id = membership_id[:64]
            sub.save(update_fields=["whop_membership_id", "updated_at"])
    return payment


def record_refund(payment_id: str, *, origin: str):
    """Refresh the refunded amount of one of our payments from Whop."""
    payment = BillingPayment.objects.filter(whop_payment_id=payment_id).first()
    if payment is None:
        return None
    try:
        data = whop.get_payment(payment_id, timeout=4)
    except whop.WhopError as exc:
        logger.error("%s: refund of %s not read: %s", origin, payment_id, exc)
        return None
    refunded = whop.money(data.get("refunded_amount"))
    if refunded is not None and refunded != payment.refunded_amount:
        payment.refunded_amount = refunded
        payment.save(update_fields=["refunded_amount"])
        logger.warning(
            "%s: shop %s payment %s refunded %s", origin, payment.shop_id, payment_id, refunded
        )
    return payment


def sync_all() -> dict:
    """Re-read every known membership from Whop (lost webhooks). Returns counters."""
    counts = {"checked": 0, "changed": 0, "errors": 0}
    if not whop.is_configured():
        return counts
    for sub in ShopSubscription.objects.exclude(whop_membership_id=""):
        counts["checked"] += 1
        before = (sub.status, sub.whop_status, sub.current_period_end)
        try:
            data = whop.get_membership(sub.whop_membership_id)
        except whop.WhopError as exc:
            counts["errors"] += 1
            logger.warning("billing_sync: membership %s: %s", sub.whop_membership_id, exc)
            continue
        after = apply_membership(data, origin="billing_sync")
        if (
            after is not None
            and (after.status, after.whop_status, after.current_period_end) != before
        ):
            counts["changed"] += 1
    return counts


# ---- report ------------------------------------------------------------------------------


@dataclass
class MonthReport:
    month: str
    paying_shops: int
    payments: int
    gross: dict[str, Decimal]
    refunded: dict[str, Decimal]
    est_net: dict[str, Decimal]
    statuses: dict[str, int]


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    tz = timezone.get_default_timezone()
    start = timezone.make_aware(datetime(year, month, 1), tz)
    nxt = datetime(year + (month == 12), month % 12 + 1, 1)
    return start, timezone.make_aware(nxt, tz)


def monthly_report(year: int, month: int, now: datetime | None = None) -> MonthReport:
    """Paying shops and money of one month (Belgrade time). Est. net = gross − fee − refunds."""
    start, end = month_bounds(year, month)
    payments = list(BillingPayment.objects.filter(paid_at__gte=start, paid_at__lt=end))
    gross: dict[str, Decimal] = {}
    refunded: dict[str, Decimal] = {}
    paying = set()
    for p in payments:
        gross[p.currency] = gross.get(p.currency, Decimal(0)) + p.amount
        refunded[p.currency] = refunded.get(p.currency, Decimal(0)) + p.refunded_amount
        if p.amount > p.refunded_amount:
            paying.add(p.shop_id)
    rate = fee_rate()
    est_net = {
        cur: (amount * (1 - rate) - refunded.get(cur, Decimal(0))).quantize(Decimal("0.01"))
        for cur, amount in gross.items()
    }
    statuses = {"trial": 0, "trial_ended": 0, "active": 0, "past_due": 0, "canceled": 0}
    now = now or timezone.now()
    for shop in Shop.objects.select_related("subscription"):
        status = shop_status(shop)
        if status == Status.TRIAL and now >= trial_ends_at(shop):
            status = "trial_ended"
        statuses[status] += 1
    return MonthReport(
        month=f"{year:04d}-{month:02d}",
        paying_shops=len(paying),
        payments=len(payments),
        gross=gross,
        refunded=refunded,
        est_net=est_net,
        statuses=statuses,
    )
