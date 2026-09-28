"""Лимиты исходящих сообщений получателям (SERBITO-345).

Открытая регистрация + отправка с доверенного sender ID = безлимитный Viber/SMS-отправитель
на любые номера (toll fraud по счёту Infobip, смишинг). Поэтому каждая отправка получателю
сначала проходит `reserve_send()`: проверки лимитов и запись в журнал `OutboundSend` —
ДО вызова провайдера. Не прошла → `QuotaExceeded`, провайдер не вызывается.

Проверки (в порядке):
1. переотправки одной доставки — не больше SEND_LIMIT_RESENDS_PER_DELIVERY;
2. пробный (непроверенный) магазин — только сербские мобильные;
3. один номер за день — по всем магазинам;
4. магазин за день и за месяц (пробные / обычные / индивидуальные лимиты);
5. весь сервис за день — предохранитель, упор логируется как ERROR (→ Sentry).

Считаются попытки, а не только успешные отправки. День и месяц — по Белграду.
Эскалация по delivery-receipt (P4) не проверяется: это то же сообщение другим каналом,
число попыток ограничено длиной цепочки, а исходная отправка уже прошла лимиты.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, ngettext

from deliveries.models import Shop

from .models import OutboundSend

logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    """Отправка запрещена лимитом. `code` — для API, `message` — для человека (i18n)."""

    def __init__(self, code: str, message: str, http_status: int = 429):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class ShopLimits:
    day: int
    month: int
    trial: bool


def shop_limits(shop: Shop) -> ShopLimits:
    """Лимиты магазина: индивидуальные из админки, иначе пробные или обычные."""
    trial = not shop.sending_verified
    day = settings.SEND_LIMIT_TRIAL_DAY if trial else settings.SEND_LIMIT_SHOP_DAY
    month = settings.SEND_LIMIT_TRIAL_MONTH if trial else settings.SEND_LIMIT_SHOP_MONTH
    if shop.daily_send_limit is not None:
        day = shop.daily_send_limit
    if shop.monthly_send_limit is not None:
        month = shop.monthly_send_limit
    return ShopLimits(day=day, month=month, trial=trial)


def _day_start(now: datetime) -> datetime:
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def shop_usage(shop: Shop, now: datetime | None = None) -> dict:
    """Расход и лимиты магазина — для страницы «Prodavnica»."""
    now = now or timezone.now()
    limits = shop_limits(shop)
    sends = OutboundSend.objects.filter(shop=shop)
    return {
        "trial": limits.trial,
        "day_used": sends.filter(created_at__gte=_day_start(now)).count(),
        "day_limit": limits.day,
        "month_used": sends.filter(created_at__gte=_month_start(now)).count(),
        "month_limit": limits.month,
    }


def _trial_suffix(limits: ShopLimits) -> str:
    if not limits.trial:
        return ""
    return " " + gettext("New stores have lower limits until the store is verified.")


def _check(shop: Shop, phone: str, *, kind: str, delivery, risky: bool, now: datetime) -> None:
    limits = shop_limits(shop)
    day_start = _day_start(now)

    if kind == OutboundSend.Kind.RESEND and delivery is not None:
        cap = settings.SEND_LIMIT_RESENDS_PER_DELIVERY
        resends = OutboundSend.objects.filter(
            delivery=delivery, kind=OutboundSend.Kind.RESEND
        ).count()
        if resends >= cap:
            raise QuotaExceeded(
                "resend_limit",
                ngettext(
                    "This notification has already been resent %(limit)d time.",
                    "This notification has already been resent %(limit)d times.",
                    cap,
                )
                % {"limit": cap},
            )

    if limits.trial and risky:
        raise QuotaExceeded(
            "destination_not_allowed",
            gettext(
                "New stores can send messages only to Serbian mobile numbers "
                "until the store is verified."
            ),
            http_status=403,
        )

    cap = settings.SEND_LIMIT_RECIPIENT_DAY
    if OutboundSend.objects.filter(phone=phone, created_at__gte=day_start).count() >= cap:
        logger.warning("send limit: recipient daily cap hit (shop %s)", shop.pk)
        raise QuotaExceeded(
            "recipient_daily_limit",
            gettext(
                "This number has already received the maximum number of messages today. "
                "Try again tomorrow."
            ),
        )

    sends = OutboundSend.objects.filter(shop=shop)
    if sends.filter(created_at__gte=day_start).count() >= limits.day:
        logger.warning("send limit: shop %s daily cap %s hit", shop.pk, limits.day)
        raise QuotaExceeded(
            "daily_limit",
            gettext(
                "Daily message limit reached (%(limit)d per day). You can send again tomorrow."
            )
            % {"limit": limits.day}
            + _trial_suffix(limits),
        )
    if sends.filter(created_at__gte=_month_start(now)).count() >= limits.month:
        logger.warning("send limit: shop %s monthly cap %s hit", shop.pk, limits.month)
        raise QuotaExceeded(
            "monthly_limit",
            gettext("Monthly message limit reached (%(limit)d per month).")
            % {"limit": limits.month}
            + _trial_suffix(limits),
        )

    cap = settings.SEND_LIMIT_GLOBAL_DAY
    total = OutboundSend.objects.filter(created_at__gte=day_start).count()
    if total >= cap:
        # Громко: ERROR уходит в Sentry как событие — это сигнал «кто-то жжёт Infobip».
        logger.error(
            "SEND GLOBAL DAILY CAP HIT: %s/%s messages today — all sending paused "
            "(blocked shop %s, kind %s)",
            total, cap, shop.pk, kind,
        )
        raise QuotaExceeded(
            "global_limit",
            gettext("Sending is paused for today. Please try again later."),
            http_status=503,
        )


def reserve_send(
    shop: Shop,
    phone: str,
    *,
    kind: str,
    delivery=None,
    risky: bool = False,
    now: datetime | None = None,
) -> OutboundSend:
    """Проверить все лимиты и записать отправку в журнал. Вызывать ДО провайдера.

    `risky` — номер не сербский мобильный (PhoneResult.is_risky / Delivery.phone_risk).
    Бросает `QuotaExceeded`; журнал при этом не меняется. Блокировка строки магазина
    сериализует параллельные отправки одного магазина (в Postgres; SQLite и так пишет
    по одному).
    """
    now = now or timezone.now()
    with transaction.atomic():
        locked = Shop.objects.select_for_update().filter(pk=shop.pk).first() or shop
        _check(locked, phone, kind=kind, delivery=delivery, risky=risky, now=now)
        return OutboundSend.objects.create(
            shop=locked, delivery=delivery, phone=phone, kind=kind, created_at=now
        )
