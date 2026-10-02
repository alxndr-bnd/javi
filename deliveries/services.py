"""Бизнес-логика deliveries. Views тонкие — вся логика здесь."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext

from common.i18n import DEFAULT_CUSTOMER_LANGUAGE
from common.phone import PhoneResult
from common.text import sanitize_shop_name
from common.timewindow import format_eta_label, rating_send_time
from integrations.providers import (
    chain_channel_paths,
    get_maps_provider,
    get_messaging_provider,
    get_messaging_provider_for,
    get_routes_provider,
)
from notifications.models import Notification, NotificationAttempt, OutboundSend
from notifications.quotas import QuotaExceeded, reserve_send
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
    language: str = DEFAULT_CUSTOMER_LANGUAGE,
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
        recipient_language=language,
    )
    return delivery, geo is not None


def compute_eta(delivery: Delivery) -> datetime | None:
    """ETA = сейчас + время в пути (origin→получатель) + запас. None если маршрут недоступен."""
    from django.conf import settings

    shop = delivery.shop
    have_coords = None not in (
        shop.origin_lat,
        shop.origin_lng,
        delivery.dest_lat,
        delivery.dest_lng,
    )
    if not have_coords:
        logger.warning(
            "ETA: нет координат для доставки %s (origin=%s,%s dest=%s,%s)",
            delivery.id, shop.origin_lat, shop.origin_lng, delivery.dest_lat, delivery.dest_lng,
        )
        return None
    seconds = get_routes_provider().route_duration_seconds(
        (shop.origin_lat, shop.origin_lng), (delivery.dest_lat, delivery.dest_lng)
    )
    if seconds is None:
        logger.warning("ETA: Routes вернул None для доставки %s", delivery.id)
        return None
    return timezone.now() + timedelta(seconds=seconds) + timedelta(
        minutes=settings.ETA_BUFFER_MINUTES
    )


def eta_unavailable_reason(delivery: Delivery) -> str:
    """Человеко-понятная причина, почему ETA не рассчитан (для UI)."""
    shop = delivery.shop
    if shop.origin_lat is None or shop.origin_lng is None:
        return gettext("Store address is not geocoded — open “Store” and save the address.")
    if delivery.dest_lat is None or delivery.dest_lng is None:
        return gettext("We could not recognize the delivery address — check the recipient address.")
    return gettext("The map can't compute a route right now — enter the time manually.")


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


def delivery_event_payload(delivery: Delivery, extra: dict | None = None) -> dict:
    """Базовый payload вебхука по доставке: id, статус, получатель, tracking_url + extra."""
    token_obj = getattr(delivery, "tracking_token", None)
    payload = {
        "id": delivery.id,
        "external_id": "",  # задел: внешний id мерчанта (когда появится на модели)
        "status": delivery.status,
        "recipient": {
            "name": delivery.recipient_name,
            "phone": delivery.recipient_phone,
        },
        "tracking_url": _tracking_link(token_obj.token) if token_obj else "",
    }
    if extra:
        payload.update(extra)
    return payload


def emit_delivery_event(delivery: Delivery, event: str, extra: dict | None = None) -> None:
    """Собрать payload доставки и отправить вебхук мерчанту (безопасно, без падений)."""
    from notifications.outbound import notify_merchant

    notify_merchant(delivery.shop, event, delivery_event_payload(delivery, extra))


def _message_shop_name(shop: Shop) -> str:
    """Название магазина для текста сообщения: без ссылок/номеров/кавычек, ≤40 символов.

    В шаблоне оно стоит в кавычках — явно отделено от нашего текста (SERBITO-345).
    Пустое после очистки (старые данные) → нейтральное «Javi».
    """
    return sanitize_shop_name(shop.name) or "Javi"


def customer_language(delivery: Delivery):
    """Context: the recipient's language for text they get (SERBITO-356).

    Every customer message is built inside it — not in the shop's UI language and not in
    whatever a Cloud Tasks callback happens to run with (that was English).
    """
    return translation.override(delivery.recipient_language or DEFAULT_CUSTOMER_LANGUAGE)


def _on_the_way_text(delivery: Delivery, token: str) -> str:
    with customer_language(delivery):
        return gettext(
            'Your order from "%(shop)s" is on its way. '
            "Arriving approximately by %(time)s. Track: %(link)s"
        ) % {
            "shop": _message_shop_name(delivery.shop),
            "time": format_eta_label(delivery.eta_at),
            "link": _tracking_link(token),
        }


def _rating_request_text(delivery: Delivery, token: str) -> str:
    with customer_language(delivery):
        return gettext('How did the delivery from "%(shop)s" go? Rate it: %(link)s') % {
            "shop": _message_shop_name(delivery.shop),
            "link": _tracking_link(token),
        }


def _record_attempts(notification: Notification, result) -> None:
    """Пишет по строке NotificationAttempt на каждую попытку канала из SendResult.

    Цепочка fallback → result.attempts (по одной на канал, в порядке попыток).
    Одноканальный провайдер (текущие фейки) → attempts пуст: зеркалим верхний
    уровень SendResult одной строкой, чтобы таблица попыток всегда была заполнена.
    Идемпотентно при повторной отправке: старые попытки этого Notification стираем.
    """
    attempts = getattr(result, "attempts", ()) or ()
    if not attempts:
        # Синтетическая единственная попытка из самого SendResult.
        attempts = (
            _AttemptView(
                channel=result.channel,
                ok=result.ok,
                provider_message_id=result.provider_message_id,
            ),
        )
    # Resend переиспользует Notification — чистим прежние попытки, не плодим дубли.
    notification.attempts.all().delete()
    NotificationAttempt.objects.bulk_create(
        [
            NotificationAttempt(
                notification=notification,
                channel=a.channel or "",
                ok=bool(a.ok),
                provider_message_id=a.provider_message_id or "",
                attempt_no=i + 1,
            )
            for i, a in enumerate(attempts)
        ]
    )


@dataclass(frozen=True)
class _AttemptView:
    """Лёгкий вид на одну попытку (для одноканального SendResult без attempts)."""

    channel: str
    ok: bool
    provider_message_id: str | None = None


def _send_and_record(notification: Notification, delivery: Delivery, text: str):
    """Отправляет текст и фиксирует исход на Notification + per-channel попытки.

    Если провайдер вернул цепочку (result.attempts), победитель — первая ok-попытка:
    её канал/provider_message_id попадают на Notification. Если ok нет — FAILED.
    Одноканальный SendResult (attempts пуст) сохраняет прежнее поведение.
    """
    result = get_messaging_provider().send_text(delivery.recipient_phone, text)

    attempts = getattr(result, "attempts", ()) or ()
    winner = next((a for a in attempts if a.ok), None)

    if attempts:
        # Цепочка fallback: победитель определяет канал/id; ok = есть ли победитель.
        ok = winner is not None
        channel = winner.channel if winner else ""
        provider_message_id = winner.provider_message_id if winner else ""
    else:
        # Одноканальный провайдер — поведение как раньше, из верхнего уровня SendResult.
        ok = result.ok
        channel = result.channel
        provider_message_id = result.provider_message_id or ""

    notification.status = Notification.Status.SENT if ok else Notification.Status.FAILED
    notification.channel = channel
    notification.provider_message_id = provider_message_id or ""
    notification.sent_at = timezone.now() if ok else None
    notification.save(update_fields=["status", "channel", "provider_message_id", "sent_at"])

    _record_attempts(notification, result)

    if not ok:
        logger.error("notification send failed for delivery %s", delivery.id)
    return result


# --- P4: async-эскалация по delivery-receipt -------------------------------


def _on_the_way_notification(delivery: Delivery) -> Notification | None:
    return delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).first()


def _untried_chain_paths(notification: Notification) -> list[str]:
    """Пути провайдеров цепочки, чьи каналы ещё НЕ пробовали для этого сообщения."""
    tried = {a.channel for a in notification.attempts.all()}
    return [path for ch, path in chain_channel_paths() if ch not in tried]


def _schedule_escalation_if_pending(delivery: Delivery, notification: Notification) -> None:
    from django.conf import settings

    if not getattr(settings, "FALLBACK_ESCALATION_ENABLED", False):
        return
    if not _untried_chain_paths(notification):
        return  # неиспробованных каналов нет — эскалировать некуда
    run_at = timezone.now() + timedelta(
        minutes=getattr(settings, "FALLBACK_ESCALATION_DELAY_MINUTES", 10)
    )
    try:
        get_task_scheduler().schedule_escalation(delivery.id, run_at)
    except Exception:
        logger.exception("failed to schedule escalation for delivery %s", delivery.id)


def _append_attempts(notification: Notification, result) -> None:
    """Дописывает попытки эскалации к существующим (НЕ затирает — продолжение того же
    логического сообщения), продолжая нумерацию attempt_no."""
    attempts = getattr(result, "attempts", ()) or ()
    if not attempts:
        attempts = (_AttemptView(result.channel, result.ok, result.provider_message_id),)
    start_no = max((a.attempt_no for a in notification.attempts.all()), default=0)
    NotificationAttempt.objects.bulk_create(
        [
            NotificationAttempt(
                notification=notification,
                channel=a.channel or "",
                ok=bool(a.ok),
                provider_message_id=a.provider_message_id or "",
                attempt_no=start_no + i + 1,
            )
            for i, a in enumerate(attempts)
        ]
    )


def escalate_delivery(delivery: Delivery) -> bool:
    """Если on_the_way НЕ подтверждён доставкой — отправить следующим неиспробованным каналом
    цепочки. No-op при выключенном флаге, уже доставленном сообщении или исчерпанных каналах.
    Возвращает True, если эскалация ушла (принята провайдером)."""
    from django.conf import settings

    if not getattr(settings, "FALLBACK_ESCALATION_ENABLED", False):
        return False
    notification = _on_the_way_notification(delivery)
    if notification is None:
        return False
    if notification.status in (Notification.Status.DELIVERED, Notification.Status.READ):
        return False  # доставлено/прочитано — эскалация не нужна
    paths = _untried_chain_paths(notification)
    token = getattr(delivery, "tracking_token", None)
    if not paths or token is None:
        return False  # каналы исчерпаны или нет токена трекинга

    text = _on_the_way_text(delivery, token.token)
    result = get_messaging_provider_for(paths).send_text(delivery.recipient_phone, text)
    _append_attempts(notification, result)

    if result.ok:
        # Победитель эскалации становится «текущим» каналом/id (для будущих receipts).
        notification.channel = result.channel
        notification.provider_message_id = result.provider_message_id or ""
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
        notification.save(update_fields=["channel", "provider_message_id", "status", "sent_at"])
        # Остались ещё неиспробованные каналы → планируем следующую проверку.
        _schedule_escalation_if_pending(delivery, notification)
    return result.ok


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
        eta_at = compute_eta(delivery)
        if eta_at is None:
            return StartResult(needs_manual_eta=True)
        eta_source = "auto"

    # Лимиты — ДО смены статуса и отправки: упёрлись → доставка остаётся «готова»,
    # магазин видит причину (QuotaExceeded летит в view/API).
    reserve_send(
        delivery.shop,
        delivery.recipient_phone,
        kind=OutboundSend.Kind.ON_THE_WAY,
        delivery=delivery,
        risky=delivery.phone_risk,
    )

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

    # P4: если включена эскалатция и остались неиспробованные каналы — запланировать проверку
    # доставки. Сбой планировщика не ломает старт (сообщение уже ушло).
    _schedule_escalation_if_pending(delivery, notification)

    # Исходящий вебхук мерчанту (декуплено, безопасно — notify_merchant сам глушит сбои).
    emit_delivery_event(delivery, "delivery.started")
    return StartResult(ok=True, sent=result.ok, eta_at=eta_at)


def mark_ready(delivery: Delivery) -> bool:
    """Перевод new → created (Spremno). Идемпотентно: возвращает True, если перевёл.

    Из любого другого статуса — no-op (False), статус не трогаем.
    """
    if delivery.status == Delivery.Status.NEW:
        delivery.status = Delivery.Status.CREATED
        delivery.save(update_fields=["status"])
        return True
    return False


def mark_delivered(delivery: Delivery) -> bool:
    """Ручная отметка «доставлено» (FR-26, опц.). Идемпотентно.

    Возвращает True, если статус изменился на delivered, иначе False.
    """
    if delivery.status != Delivery.Status.DELIVERED:
        delivery.status = Delivery.Status.DELIVERED
        delivery.save(update_fields=["status"])
        emit_delivery_event(delivery, "delivery.delivered")  # вебхук — и из UI, и из API
        return True
    return False


def soft_delete(delivery: Delivery) -> bool:
    """Мягкое удаление: проставляет `deleted_at`. Идемпотентно (уже удалена → False)."""
    if delivery.deleted_at is None:
        delivery.deleted_at = timezone.now()
        delivery.save(update_fields=["deleted_at"])
        return True
    return False


def restore(delivery: Delivery) -> bool:
    """Восстановление мягко удалённой доставки. Идемпотентно (не удалена → False)."""
    if delivery.deleted_at is not None:
        delivery.deleted_at = None
        delivery.save(update_fields=["deleted_at"])
        return True
    return False


def resend_on_the_way(delivery: Delivery, new_phone: PhoneResult | None = None):
    """Переотправка уведомления «в пути» (FR-25). Явное действие, без дублей записей.

    Опционально правит номер. Переиспользует существующий on_the_way-Notification
    (новый logical_message_id), статус → queued → sent/failed.

    Лимиты (SERBITO-345): каждая переотправка — новая отправка во всех лимитах (магазин,
    номер, глобальный) плюс не больше SEND_LIMIT_RESENDS_PER_DELIVERY на доставку; новый
    номер проверяется как новый получатель. Упёрлись → QuotaExceeded, номер не меняем.
    """
    notification = delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).first()
    token_obj = getattr(delivery, "tracking_token", None)
    if notification is None or token_obj is None:
        return None

    phone = new_phone.e164 if new_phone is not None else delivery.recipient_phone
    risky = new_phone.is_risky if new_phone is not None else delivery.phone_risk
    reserve_send(
        delivery.shop, phone, kind=OutboundSend.Kind.RESEND, delivery=delivery, risky=risky
    )

    if new_phone is not None:
        delivery.recipient_phone = new_phone.e164
        delivery.phone_risk = new_phone.is_risky
        delivery.save(update_fields=["recipient_phone", "phone_risk"])

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
    try:
        reserve_send(
            delivery.shop,
            delivery.recipient_phone,
            kind=OutboundSend.Kind.RATING_REQUEST,
            delivery=delivery,
            risky=delivery.phone_risk,
        )
    except QuotaExceeded as exc:
        # Не-критичное сообщение: упёрлись в лимит — молча пропускаем (без ретраев задачи).
        logger.info("rating request skipped for delivery %s: %s", delivery.id, exc.code)
        return None
    notification = Notification.objects.create(
        delivery=delivery,
        kind=Notification.Kind.RATING_REQUEST,
        status=Notification.Status.QUEUED,
    )
    return _send_and_record(
        notification, delivery, _rating_request_text(delivery, token_obj.token)
    )
