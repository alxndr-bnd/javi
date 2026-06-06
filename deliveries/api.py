"""Публичный API v1 для магазинов (тонкий слой над доменными сервисами).

Без DRF — обычные Django JSON-вьюхи. Аутентификация по API-ключу в заголовке;
вся логика переиспользует `deliveries.services` (как и UI). Единый конверт ошибок.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import wraps

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from common.phone import InvalidPhone, normalize_phone
from common.timewindow import BELGRADE, format_eta
from notifications.models import Notification

from .models import ApiIdempotencyKey, ApiKey, Delivery, hash_api_key
from .services import _tracking_link, create_delivery, start_delivery

# --- Конверт ошибок -------------------------------------------------------


def error(code: str, message: str, status: int) -> JsonResponse:
    """Единый JSON-конверт ошибки: {"error": {"code", "message"}}."""
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


# --- Аутентификация по ключу ---------------------------------------------


def _read_key(request) -> str | None:
    """Достаёт ключ из `Authorization: Bearer …` или `X-Api-Key`."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    x_key = request.headers.get("X-Api-Key", "").strip()
    return x_key or None


def authenticate(request):
    """request → Shop (по валидному, не отозванному ключу) или None.

    Побочный эффект: обновляет `last_used_at` найденного ключа.
    """
    raw = _read_key(request)
    if not raw:
        return None
    try:
        api_key = ApiKey.objects.select_related("shop").get(
            key_hash=hash_api_key(raw), revoked_at__isnull=True
        )
    except ApiKey.DoesNotExist:
        return None
    ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())
    return api_key.shop


def require_api_key(view_func):
    """Декоратор: проверяет ключ, кладёт `request.shop`, иначе 401."""

    @csrf_exempt
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        shop = authenticate(request)
        if shop is None:
            return error("unauthorized", _("Missing or invalid API key."), 401)
        request.shop = shop
        return view_func(request, *args, **kwargs)

    return wrapper


# --- Сериализация ---------------------------------------------------------


def _on_the_way_notif(delivery: Delivery):
    return delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).first()


def _tracking_url(delivery: Delivery) -> str | None:
    token = getattr(delivery, "tracking_token", None)
    return _tracking_link(token.token) if token is not None else None


def serialize_delivery(delivery: Delivery) -> dict:
    notif = _on_the_way_notif(delivery)
    return {
        "id": delivery.id,
        "status": delivery.status,
        "tracking_url": _tracking_url(delivery),
        "recipient": {"name": delivery.recipient_name, "phone": delivery.recipient_phone},
        "description": delivery.description,
        "dest_address": delivery.dest_address,
        "dest_city": delivery.dest_city,
        "eta": format_eta(delivery.eta_at) if delivery.eta_at else None,
        "notification": {"channel": notif.channel, "status": notif.status} if notif else None,
        "source": delivery.source,
        "created_at": delivery.created_at.isoformat(),
    }


def _parse_body(request) -> dict | None:
    """JSON-тело запроса → dict (или None при битом JSON / не-объекте).

    Тело парсим только если оно есть и заявлено как JSON; пустой/не-JSON
    content-type трактуем как «без параметров» ({}), а не как ошибку.
    """
    content_type = (request.content_type or "").lower()
    if not request.body or "json" not in content_type:
        return {}
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _get_owned_delivery(request, pk: int) -> Delivery | None:
    """Доставка по pk, скоуп по магазину ключа. None → 404 у вызывающего."""
    return request.shop.deliveries.filter(pk=pk).first()


# --- Эндпоинты ------------------------------------------------------------


@require_api_key
def deliveries_collection(request):
    if request.method != "POST":
        return error("method_not_allowed", _("Method not allowed."), 405)

    data = _parse_body(request)
    if data is None:
        return error("invalid_json", _("Request body must be a JSON object."), 400)

    recipient_name = (data.get("recipient_name") or "").strip()
    recipient_phone = (data.get("recipient_phone") or "").strip()
    address = (data.get("address") or "").strip()
    description = (data.get("description") or "").strip()

    missing = [
        f
        for f, v in (
            ("recipient_name", recipient_name),
            ("recipient_phone", recipient_phone),
            ("address", address),
        )
        if not v
    ]
    if missing:
        return error(
            "invalid_request",
            _("Missing required fields: %(fields)s.") % {"fields": ", ".join(missing)},
            422,
        )

    try:
        phone = normalize_phone(recipient_phone)
    except InvalidPhone:
        return error("invalid_phone", _("Invalid recipient phone number."), 400)

    idem_key = request.headers.get("Idempotency-Key", "").strip()
    if idem_key:
        existing = (
            ApiIdempotencyKey.objects.filter(shop=request.shop, key=idem_key)
            .select_related("delivery")
            .first()
        )
        if existing is not None:
            return JsonResponse(serialize_delivery(existing.delivery), status=201)

    delivery, _geocoded = create_delivery(
        request.shop,
        recipient_name=recipient_name,
        phone=phone,
        dest_address=address,
        description=description,
    )
    if delivery.source != Delivery.Source.API:
        delivery.source = Delivery.Source.API
        delivery.save(update_fields=["source"])

    if idem_key:
        try:
            with transaction.atomic():
                ApiIdempotencyKey.objects.create(
                    shop=request.shop, key=idem_key, delivery=delivery
                )
        except IntegrityError:
            # Гонка: другой запрос с тем же ключом успел первым — вернём его доставку.
            existing = (
                ApiIdempotencyKey.objects.filter(shop=request.shop, key=idem_key)
                .select_related("delivery")
                .first()
            )
            if existing is not None:
                delivery.delete()
                return JsonResponse(serialize_delivery(existing.delivery), status=201)

    return JsonResponse(serialize_delivery(delivery), status=201)


@require_api_key
def delivery_detail(request, pk: int):
    if request.method != "GET":
        return error("method_not_allowed", _("Method not allowed."), 405)
    delivery = _get_owned_delivery(request, pk)
    if delivery is None:
        return error("not_found", _("Delivery not found."), 404)
    return JsonResponse(serialize_delivery(delivery), status=200)


@require_api_key
def delivery_start(request, pk: int):
    if request.method != "POST":
        return error("method_not_allowed", _("Method not allowed."), 405)
    delivery = _get_owned_delivery(request, pk)
    if delivery is None:
        return error("not_found", _("Delivery not found."), 404)

    data = _parse_body(request)
    if data is None:
        return error("invalid_json", _("Request body must be a JSON object."), 400)

    manual_eta = None
    eta_raw = (data.get("eta") or "").strip()
    if eta_raw:
        try:
            parsed = datetime.strptime(eta_raw, "%H:%M").time()
        except ValueError:
            return error("invalid_eta", _("eta must be in HH:MM format."), 400)
        today = timezone.now().astimezone(BELGRADE).date()
        manual_eta = datetime.combine(today, parsed, tzinfo=BELGRADE)

    result = start_delivery(delivery, manual_eta=manual_eta)
    if result.needs_manual_eta:
        return error(
            "eta_required",
            _("Route is unavailable — pass eta (HH:MM) to start the delivery."),
            422,
        )
    delivery.refresh_from_db()
    return JsonResponse(serialize_delivery(delivery), status=200)
