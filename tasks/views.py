"""Защищённые колбэки Cloud Tasks (HTTP). Здесь — отправка запроса оценки."""

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from common.secrets import request_has_secret
from deliveries.models import Delivery
from deliveries.services import escalate_delivery, send_rating_request

from .scheduler import TASKS_SECRET_HEADER


def _secret_ok(request) -> bool:
    # Заголовок X-Tasks-Secret, constant-time; ?secret= — только для задач до SERBITO-362.
    return request_has_secret(request, settings.TASKS_SECRET, header=TASKS_SECRET_HEADER)


@csrf_exempt
def send_rating(request, delivery_id):
    """POST от Cloud Tasks по ETA+30 → запрос оценки. Защита — общий секрет (fail-closed)."""
    if not _secret_ok(request):
        return HttpResponseForbidden("forbidden")
    delivery = get_object_or_404(Delivery, pk=delivery_id)
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
