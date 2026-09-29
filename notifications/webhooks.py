"""Входящие вебхуки Infobip: delivery/seen receipts → Notification.status."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from common.phone import InvalidPhone, normalize_phone
from common.secrets import request_has_secret, secret_matches

from .models import Notification, TelegramContact
from .services import opt_out

logger = logging.getLogger(__name__)


WEBHOOK_SECRET_HEADER = "X-Webhook-Secret"


def _check_secret(request) -> bool:
    # Заголовок / Basic auth (подписка Infobip) / ?secret= (URL отчёта в сообщении), constant-time.
    return request_has_secret(
        request, settings.INFOBIP_WEBHOOK_SECRET, header=WEBHOOK_SECRET_HEADER
    )


# Порядок прогресса статуса — не понижаем (idempotent, без даунгрейда read→delivered).
_ORDER = [
    Notification.Status.QUEUED,
    Notification.Status.SENT,
    Notification.Status.DELIVERED,
    Notification.Status.READ,
]
_FAILED_GROUPS = {"UNDELIVERABLE", "REJECTED", "EXPIRED"}


def _resolve_status(result: dict) -> str | None:
    if result.get("seen"):
        return Notification.Status.READ
    group = (result.get("status") or {}).get("groupName")
    if group == "DELIVERED":
        return Notification.Status.DELIVERED
    if group in _FAILED_GROUPS:
        return Notification.Status.FAILED
    return None  # PENDING/неизвестно — без изменения


def _apply(notif: Notification, new_status: str) -> bool:
    """Применяет новый статус с защитой от даунгрейда. Возвращает True, если статус изменился."""
    if new_status == Notification.Status.FAILED:
        # failed применяем только если ещё не доставлено/прочитано.
        if notif.status in (Notification.Status.QUEUED, Notification.Status.SENT):
            notif.status = new_status
            notif.save(update_fields=["status"])
            return True
        return False
    cur = notif.status if notif.status in _ORDER else Notification.Status.QUEUED
    if _ORDER.index(new_status) > _ORDER.index(cur):
        notif.status = new_status
        notif.save(update_fields=["status"])
        return True
    return False


# Маппинг статуса уведомления → событие исходящего вебхука мерчанту.
_NOTIF_EVENT = {
    Notification.Status.DELIVERED: "notification.delivered",
    Notification.Status.READ: "notification.read",
    Notification.Status.FAILED: "notification.failed",
}


def _emit_notification_event(notif: Notification) -> None:
    """Вебхук мерчанту о смене статуса доставки уведомления (безопасно)."""
    from deliveries.services import emit_delivery_event

    event = _NOTIF_EVENT.get(notif.status)
    if event:
        emit_delivery_event(
            notif.delivery,
            event,
            {"notification_status": notif.status, "channel": notif.channel},
        )


@csrf_exempt
def infobip_reports(request):
    """POST от Infobip с delivery/seen receipts. Защита — общий секрет."""
    if not _check_secret(request):
        return HttpResponseForbidden("forbidden")

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)

    for result in payload.get("results", []):
        mid = result.get("messageId")
        if not mid:
            continue
        notif = Notification.objects.filter(provider_message_id=mid).first()
        if notif is None:
            continue  # неизвестный messageId — тихо пропускаем
        new_status = _resolve_status(result)
        if new_status and _apply(notif, new_status):
            _emit_notification_event(notif)

    return HttpResponse(status=200)


@csrf_exempt
def infobip_optout(request):
    """POST от Infobip с opt-out (STOP) → зеркалим номера в блоклист. Защита — секрет."""
    if not _check_secret(request):
        return HttpResponseForbidden("forbidden")

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)

    for result in payload.get("results", []):
        phone = result.get("to") or result.get("phoneNumber") or result.get("destination")
        if phone:
            opt_out(phone if str(phone).startswith("+") else f"+{phone}")

    return HttpResponse(status=200)


@csrf_exempt
def telegram_webhook(request):
    """POST от Telegram (updates бота). Захватывает opt-in: когда пользователь делится
    своим контактом (кнопка «поделиться телефоном»), сохраняем chat_id по нормализованному
    номеру → потом TelegramProvider сможет писать ему первым в цепочке.

    Защита — секрет в заголовке `X-Telegram-Bot-Api-Secret-Token` (Telegram шлёт его сам,
    если задан при setWebhook). К нерелевантным апдейтам толерантны: игнор + 200.
    """
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not secret_matches(header, settings.TELEGRAM_WEBHOOK_SECRET):
        return HttpResponseForbidden("forbidden")

    try:
        update = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)

    message = update.get("message") or update.get("edited_message") or {}
    contact = message.get("contact")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    raw_phone = contact.get("phone_number") if isinstance(contact, dict) else None

    # Только СВОЙ контакт (SERBITO-362, JAVI-4): переслать можно любую карточку, и тогда
    # уведомления чужого номера ушли бы в этот чат. Своя — contact.user_id == from.id.
    sender_id = (message.get("from") or {}).get("id")
    if raw_phone and (sender_id is None or contact.get("user_id") != sender_id):
        logger.info("Telegram: ignored a contact card that is not the sender's own")
        return HttpResponse(status=200)

    if raw_phone and chat_id is not None:
        try:
            normalized = normalize_phone(raw_phone).e164
        except InvalidPhone:
            return HttpResponse(status=200)  # неразборчивый номер — тихо игнорируем
        TelegramContact.objects.update_or_create(
            phone=normalized, defaults={"chat_id": str(chat_id)}
        )

    return HttpResponse(status=200)
