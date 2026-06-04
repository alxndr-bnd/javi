"""Входящие вебхуки Infobip: delivery/seen receipts → Notification.status."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from .models import Notification

logger = logging.getLogger(__name__)

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


def _apply(notif: Notification, new_status: str) -> None:
    if new_status == Notification.Status.FAILED:
        # failed применяем только если ещё не доставлено/прочитано.
        if notif.status in (Notification.Status.QUEUED, Notification.Status.SENT):
            notif.status = new_status
            notif.save(update_fields=["status"])
        return
    cur = notif.status if notif.status in _ORDER else Notification.Status.QUEUED
    if _ORDER.index(new_status) > _ORDER.index(cur):
        notif.status = new_status
        notif.save(update_fields=["status"])


@csrf_exempt
def infobip_reports(request):
    """POST от Infobip с delivery/seen receipts. Защита — общий секрет."""
    secret = request.GET.get("secret") or request.headers.get("X-Webhook-Secret", "")
    if not settings.INFOBIP_WEBHOOK_SECRET or secret != settings.INFOBIP_WEBHOOK_SECRET:
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
        if new_status:
            _apply(notif, new_status)

    return HttpResponse(status=200)
