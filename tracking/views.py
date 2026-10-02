from functools import wraps

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.views.decorators.http import require_POST

from common import ratelimit
from common.client_ip import client_ip
from common.timewindow import format_eta
from deliveries.models import Delivery, Rating, TrackingToken
from deliveries.services import customer_language

# Порядок шагов степпера и какой статус доставки на каком шаге.
_STEPS = [
    (_l("Received"), Delivery.Status.CREATED),
    (_l("In delivery"), Delivery.Status.ON_THE_WAY),
    (_l("Delivered"), Delivery.Status.DELIVERED),
]
_RATEABLE = (Delivery.Status.ON_THE_WAY, Delivery.Status.DELIVERED)


def _stepper(status: str) -> list[dict]:
    """Список шагов с состояниями done/active/future для серверного рендера.

    Финальный шаг (Isporučeno) в терминальном статусе — done (✓), а не active (●).
    current — шаг текущего статуса (aria-current="step", SERBITO-352), в т.ч. финальный.
    """
    order = [s for _, s in _STEPS]
    current = order.index(status) if status in order else 0
    is_terminal = status == Delivery.Status.DELIVERED
    steps = []
    for idx, (label, _s) in enumerate(_STEPS):
        if idx < current:
            state = "done"
        elif idx == current:
            state = "done" if is_terminal else "active"
        else:
            state = "future"
        steps.append({"label": label, "state": state, "current": idx == current})
    return steps


def rate_limited(view):
    """Лимит запросов с одного IP в минуту на ВСЕ страницы /t/ (SERBITO-362, JAVI-8).

    IP — реальный клиент (common.client_ip), не адрес фронтенда Google; счётчик — в БД,
    общий для воркеров и переживает холодный старт (common.ratelimit).
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        allowed = ratelimit.hit(
            "tracking",
            client_ip(request),
            limit=settings.TRACKING_RATE_LIMIT,
            window_seconds=60,
        )
        if not allowed:
            return HttpResponse(_("Too many requests. Try again later."), status=429)
        return view(request, *args, **kwargs)

    return wrapper


def _render(request, delivery, template, ctx, status=200):
    """Customer page in the customer's language — the one their SMS was sent in (SERBITO-356)."""
    with customer_language(delivery):
        response = render(request, template, ctx, status=status)
        response.headers["Content-Language"] = translation.get_language()
    return response


def _active_token(token: str):
    """TrackingToken или None если истёк."""
    token_obj = get_object_or_404(TrackingToken, token=token)
    if token_obj.expires_at and token_obj.expires_at < timezone.now():
        return None
    return token_obj


@rate_limited
def status(request, token):
    """Публичная брендовая страница статуса (без логина). Минимум данных (NFR-3)."""
    token_obj = _active_token(token)
    if token_obj is None:
        return render(request, "tracking/status.html", {"expired": True}, status=410)

    delivery = token_obj.delivery
    rating = getattr(delivery, "rating", None)
    ctx = {
        "shop_name": delivery.shop.name,
        "status": delivery.status,
        "steps": _stepper(delivery.status),
        "dest_city": delivery.dest_city,
        "eta": format_eta(delivery.eta_at) if delivery.eta_at else None,
        "token": token,
        "rating": rating.value if rating else None,
        "can_rate": delivery.status in _RATEABLE and rating is None,
    }
    return _render(request, delivery, "tracking/status.html", ctx)


@rate_limited
@require_POST
def mark_received(request, token):
    """Получатель подтверждает получение заказа → статус delivered (идемпотентно)."""
    token_obj = _active_token(token)
    if token_obj is None:
        return render(request, "tracking/status.html", {"expired": True}, status=410)
    delivery = token_obj.delivery
    if delivery.status != Delivery.Status.DELIVERED:
        delivery.status = Delivery.Status.DELIVERED
        delivery.save(update_fields=["status"])
        from deliveries.services import emit_delivery_event

        emit_delivery_event(delivery, "delivery.delivered")
    return redirect("tracking:status", token=token)


@rate_limited
def unsubscribe(request, token):
    """Отписка получателя по ссылке (без логина): номер → блоклист, «Odjavljeni ste».

    GET только показывает подтверждение, отписывает POST (SERBITO-362, JAVI-9): ссылку
    открывают и превью мессенджеров, и сканеры ссылок — они не должны отписывать клиента.
    """
    from notifications.services import opt_out

    token_obj = _active_token(token)
    if token_obj is None:
        return render(request, "tracking/status.html", {"expired": True}, status=410)
    delivery = token_obj.delivery
    if request.method != "POST":
        return _render(request, delivery, "tracking/unsubscribe_confirm.html", {"token": token})
    opt_out(delivery.recipient_phone)
    return _render(request, delivery, "tracking/unsubscribed.html", {})


@rate_limited
@require_POST
def rate(request, token):
    """Захват оценки 1–5 с публичной страницы (без логина, без дублей)."""
    token_obj = _active_token(token)
    if token_obj is None:
        return render(request, "tracking/status.html", {"expired": True}, status=410)
    try:
        value = int(request.POST.get("value", ""))
    except (TypeError, ValueError):
        value = 0
    if 1 <= value <= 5:
        delivery = token_obj.delivery
        _rating, created = Rating.objects.update_or_create(
            delivery=delivery, defaults={"value": value}
        )
        if created:
            from deliveries.services import emit_delivery_event

            emit_delivery_event(delivery, "rating.created", {"rating": value})
    return redirect("tracking:status", token=token)
