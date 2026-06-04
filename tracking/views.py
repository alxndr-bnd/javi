from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from common.timewindow import format_eta
from deliveries.models import TrackingToken


def status(request, token):
    """Публичная страница статуса (без логина). Минимум данных (NFR-3): без телефона/полного адреса.

    Брендовая версия со степпером и rate-limit/сроком ссылки — Story 2.2.
    """
    token_obj = get_object_or_404(TrackingToken, token=token)
    if token_obj.expires_at and token_obj.expires_at < timezone.now():
        # Срок ссылки истёк — не раскрываем данные.
        return render(request, "tracking/status.html", {"expired": True}, status=410)

    delivery = token_obj.delivery
    ctx = {
        "shop_name": delivery.shop.name,
        "status": delivery.status,
        "eta": format_eta(delivery.eta_at) if delivery.eta_at else None,
    }
    return render(request, "tracking/status.html", ctx)
