"""Входящие вебхуки Infobip: delivery/seen receipts → Notification.status."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from .models import Notification
from .services import opt_out

logger = logging.getLogger(__name__)


def _check_secret(request) -> bool:
    secret = request.GET.get("secret") or request.headers.get("X-Webhook-Secret", "")
    return bool(settings.INFOBIP_WEBHOOK_SECRET) and secret == settings.INFOBIP_WEBHOOK_SECRET

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
