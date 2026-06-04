"""Бизнес-логика deliveries. Views тонкие — вся логика здесь."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone

from common.phone import PhoneResult
from common.timewindow import format_eta, rating_send_time
from integrations.providers import get_maps_provider, get_messaging_provider, get_routes_provider
from notifications.models import Notification
from notifications.services import is_opted_out
from tasks.scheduler import get_task_scheduler

from .models import Delivery, Shop, TrackingToken

logger = logging.getLogger(__name__)


def set_shop_origin(shop: Shop, raw_address: str) -> bool:
    """Геокодит адрес и сохраняет origin магазина.

    Успех → сохраняет formatted-адрес + координаты, возвращает True.
    Сбой/не распознан → НЕ трогает существующий origin, возвращает False
    (origin без координат бесполезен для ETA — просим исправить).
    """
    provider = get_maps_provider()
    result = provider.geocode(raw_address)
    if result is None:
        return False

    shop.origin_address = result.formatted_address
    shop.origin_lat = result.lat
    shop.origin_lng = result.lng
    shop.save(update_fields=["origin_address", "origin_lat", "origin_lng"])
    return True


def create_delivery(
    shop: Shop,
    *,
    recipient_name: str,
    phone: PhoneResult,
    dest_address: str,
    description: str = "",
) -> tuple[Delivery, bool]:
    """Создаёт доставку дня. Геокодит адрес; при неудаче создаёт без координат (FR-5/9).

    Возвращает (delivery, geocoded_ok). Поток не блокируется на сбое геокода.
    """
    geo = get_maps_provider().geocode(dest_address)
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name=recipient_name,
        recipient_phone=phone.e164,
        phone_risk=phone.is_risky,
        dest_address=geo.formatted_address if geo else dest_address,
        dest_city=geo.city if geo else "",
        dest_lat=geo.lat if geo else None,
        dest_lng=geo.lng if geo else None,
        description=description,
    )
    return delivery, geo is not None


@dataclass
class StartResult:
    ok: bool = False
    already: bool = False  # уже стартовала (идемпотентность)
    needs_manual_eta: bool = False  # маршрут недоступен → нужен ручной ETA
    sent: bool = False  # сообщение ушло
    eta_at: datetime | None = None


def _tracking_link(token: str) -> str:
    from django.conf import settings

    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{reverse('tracking:status', args=[token])}"


def _on_the_way_text(delivery: Delivery, token: str) -> str:
    return (
        f"Vaša porudžbina iz {delivery.shop.name} je u dostavi. "
        f"Stiže okvirno do {format_eta(delivery.eta_at)}. Pratite: {_tracking_link(token)}"
    )


def _send_and_record(notification: Notification, delivery: Delivery, text: str):
    """Отправляет текст и фиксирует исход на Notification (канал/статус/id/время)."""
    result = get_messaging_provider().send_text(delivery.recipient_phone, text)
    notification.status = Notification.Status.SENT if result.ok else Notification.Status.FAILED
    notification.channel = result.channel
    notification.provider_message_id = result.provider_message_id or ""
    notification.sent_at = timezone.now() if result.ok else None
    notification.save(update_fields=["status", "channel", "provider_message_id", "sent_at"])
    if not result.ok:
        logger.error("notification send failed for delivery %s", delivery.id)
    return result


def start_delivery(delivery: Delivery, *, manual_eta: datetime | None = None) -> StartResult:
    """«Доставка началась»: рассчитать ETA, уведомить получателя. Идемпотентно.

    Маршрут недоступен/нет координат и нет manual_eta → StartResult(needs_manual_eta=True),
    ничего не меняем (FR-9: поток не рвётся, магазин вводит ETA вручную).
    """
    # Идемпотентность: повторный старт — no-op.
    if delivery.status == Delivery.Status.ON_THE_WAY or delivery.notifications.filter(
        kind=Notification.Kind.ON_THE_WAY
    ).exists():
        return StartResult(already=True, eta_at=delivery.eta_at)

    now = timezone.now()
    if manual_eta is not None:
        eta_at, eta_source = manual_eta, "manual"
    else:
        shop = delivery.shop
        have_coords = None not in (
            shop.origin_lat,
            shop.origin_lng,
            delivery.dest_lat,
            delivery.dest_lng,
        )
        seconds = (
            get_routes_provider().route_duration_seconds(
                (shop.origin_lat, shop.origin_lng), (delivery.dest_lat, delivery.dest_lng)
            )
            if have_coords
            else None
        )
        if seconds is None:
            return StartResult(needs_manual_eta=True)
        eta_at, eta_source = now + timedelta(seconds=seconds), "auto"

    delivery.status = Delivery.Status.ON_THE_WAY
    delivery.started_at = now
    delivery.eta_at = eta_at
    delivery.eta_source = eta_source
    delivery.save(update_fields=["status", "started_at", "eta_at", "eta_source"])

    from django.conf import settings

    token_obj, _ = TrackingToken.objects.get_or_create(
        delivery=delivery,
        defaults={"expires_at": now + timedelta(days=settings.TRACKING_TOKEN_TTL_DAYS)},
    )

    notification = Notification.objects.create(
        delivery=delivery,
        kind=Notification.Kind.ON_THE_WAY,
        status=Notification.Status.QUEUED,
    )

    result = _send_and_record(notification, delivery, _on_the_way_text(delivery, token_obj.token))

    # Планируем запрос оценки на ETA+30 (прижатый к окну 08:00–22:00) — AR-4/FR-16/21.
    # Сбой планировщика НЕ должен ломать старт (сообщение уже ушло) — деградируем мягко.
    try:
        get_task_scheduler().schedule_rating_request(delivery.id, rating_send_time(eta_at))
    except Exception:
        logger.exception("failed to schedule rating request for delivery %s", delivery.id)
    return StartResult(ok=True, sent=result.ok, eta_at=eta_at)


def resend_on_the_way(delivery: Delivery, new_phone: PhoneResult | None = None):
    """Переотправка уведомления «в пути» (FR-25). Явное действие, без дублей записей.

    Опционально правит номер. Переиспользует существующий on_the_way-Notification
    (новый logical_message_id), статус → queued → sent/failed.
    """
    if new_phone is not None:
        delivery.recipient_phone = new_phone.e164
        delivery.phone_risk = new_phone.is_risky
        delivery.save(update_fields=["recipient_phone", "phone_risk"])

    notification = delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).first()
    token_obj = getattr(delivery, "tracking_token", None)
    if notification is None or token_obj is None:
        return None

    notification.logical_message_id = uuid.uuid4()
    notification.status = Notification.Status.QUEUED
    notification.save(update_fields=["logical_message_id", "status"])
    return _send_and_record(notification, delivery, _on_the_way_text(delivery, token_obj.token))


def send_rating_request(delivery: Delivery):
    """Колбэк ETA+30: шлёт запрос оценки получателю. Идемпотентно (один rating_request)."""
    if delivery.notifications.filter(kind=Notification.Kind.RATING_REQUEST).exists():
        return None
    token_obj = getattr(delivery, "tracking_token", None)
    if token_obj is None:
        return None
    if is_opted_out(delivery.recipient_phone):
        return None  # не-критичное сообщение отписавшимся не шлём (FR-23)
    notification = Notification.objects.create(
        delivery=delivery,
        kind=Notification.Kind.RATING_REQUEST,
        status=Notification.Status.QUEUED,
    )
    text = (
        f"Kako je prošla dostava iz {delivery.shop.name}? "
        f"Ocenite: {_tracking_link(token_obj.token)}"
    )
    return _send_and_record(notification, delivery, text)
