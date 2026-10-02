"""Защищённые колбэки Cloud Tasks (HTTP). Здесь — отправка запроса оценки."""

from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from common.secrets import request_has_secret
from common.timewindow import rating_send_time
from deliveries.models import Delivery
from deliveries.services import escalate_delivery, send_rating_request

from .scheduler import TASKS_SECRET_HEADER

# Cloud Tasks может прийти чуть раньше срока — столько раньше ещё считается «вовремя».
_EARLY = timedelta(minutes=5)


def _secret_ok(request) -> bool:
    # Заголовок X-Tasks-Secret, constant-time; ?secret= — только для задач до SERBITO-362.
    return request_has_secret(request, settings.TASKS_SECRET, header=TASKS_SECRET_HEADER)


@csrf_exempt
def send_rating(request, delivery_id):
    """POST от Cloud Tasks по ETA+30 → запрос оценки. Защита — общий секрет (fail-closed)."""
    if not _secret_ok(request):
        return HttpResponseForbidden("forbidden")
    delivery = get_object_or_404(Delivery, pk=delivery_id)
    # ETA перенесли (правка доставки, SERBITO-356) — эта задача по старому времени рано;
    # по новому времени запланирована своя.
    if delivery.eta_at and rating_send_time(delivery.eta_at) > timezone.now() + _EARLY:
        return HttpResponse(status=200)
    send_rating_request(delivery)  # идемпотентно
    return HttpResponse(status=200)


@csrf_exempt
def escalate(request, delivery_id):
    """P4: POST от Cloud Tasks через FALLBACK_ESCALATION_DELAY_MINUTES. Если on_the_way не
    подтверждён доставкой — шлём следующим каналом цепочки. Защита — общий секрет."""
    if not _secret_ok(request):
        return HttpResponseForbidden("forbidden")
    delivery = get_object_or_404(Delivery, pk=delivery_id)
    escalate_delivery(delivery)  # no-op, если уже доставлено / каналы исчерпаны / флаг off
    return HttpResponse(status=200)
