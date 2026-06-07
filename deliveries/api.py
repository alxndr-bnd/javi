"""Публичный API v1 для магазинов на Django REST Framework (тонкий слой над сервисами).

Контракт URL и форма ответов сохранены 1:1 с прежней реализацией на «голом» Django,
чтобы текущие интеграторы не сломались. Вся логика — в `deliveries.services` (как и UI).

Единый конверт ошибок: `{"error": {"code", "message"}}` — через `exception_handler`.
Industry-standard статусы (`pending`/`ready_for_pickup`/`out_for_delivery`/`delivered`)
отдаются в поле `status`, внутренний код — в `status_internal`.
"""

from __future__ import annotations

from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, ParseError
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from common.phone import InvalidPhone, normalize_phone
from common.timewindow import BELGRADE, format_eta
from notifications.models import Notification

from .models import ApiIdempotencyKey, Delivery
from .services import (
    _tracking_link,
    create_delivery,
    mark_delivered,
    mark_ready,
    resend_on_the_way,
    restore,
    set_shop_origin,
    soft_delete,
    start_delivery,
)

# --- Industry-standard статусы -------------------------------------------
# Внутренний код → стандартное значение (ориентир: AfterShip 7-status model).
STATUS_MAP = {
    Delivery.Status.NEW: "pending",
    Delivery.Status.CREATED: "ready_for_pickup",
    Delivery.Status.ON_THE_WAY: "out_for_delivery",
    Delivery.Status.DELIVERED: "delivered",
}
STANDARD_STATUSES = list(dict.fromkeys(STATUS_MAP.values()))
# Обратное: стандартное значение → внутренний код (для фильтра ?status=).
STATUS_MAP_REVERSE = {v: k for k, v in STATUS_MAP.items()}


def standard_status(delivery: Delivery) -> str:
    return STATUS_MAP.get(delivery.status, delivery.status)


# --- Единый конверт ошибок ------------------------------------------------


class ApiError(APIException):
    """Доменная ошибка API: несёт `code`, человеко-понятный `message` и HTTP-статус."""

    def __init__(self, code: str, message: str, status_code: int):
        self.error_code = code
        self.status_code = status_code
        super().__init__(detail=message)


def exception_handler(exc, context):
    """Любую DRF-ошибку приводим к конверту `{"error": {"code", "message"}}`."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ApiError):
        code, message = exc.error_code, str(exc.detail)
    elif isinstance(exc, ParseError):
        code = "invalid_json"
        message = _("Request body must be a JSON object.")
    else:
        code = _default_code(response.status_code)
        message = _flatten_message(response.data)
    response.data = {"error": {"code": code, "message": message}}
    return response


def _default_code(status_code: int) -> str:
    return {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "unprocessable_entity",
        429: "rate_limited",
    }.get(status_code, "error")


def _flatten_message(data) -> str:
    """DRF-ошибки бывают вложенными — вытаскиваем первое читаемое сообщение."""
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        for value in data.values():
            return _flatten_message(value)
    if isinstance(data, (list, tuple)) and data:
        return _flatten_message(data[0])
    return str(data)


# --- Сериализаторы --------------------------------------------------------


class RecipientSerializer(serializers.Serializer):
    name = serializers.CharField(help_text=_("Recipient full name."))
    phone = serializers.CharField(help_text=_("Recipient phone in E.164 (e.g. +381641234567)."))


class NotificationSerializer(serializers.Serializer):
    channel = serializers.CharField(
        allow_blank=True, help_text=_("Delivery channel: viber or sms.")
    )
    status = serializers.ChoiceField(
        choices=[s for s, _l in Notification.Status.choices],
        help_text=_("Receipt status: queued/sent/delivered/read/failed."),
    )


class DeliverySerializer(serializers.Serializer):
    """Delivery in API responses.

    `status` is industry-standard; `status_internal` is the Javi code.
    """

    id = serializers.IntegerField(read_only=True)
    status = serializers.ChoiceField(
        choices=STANDARD_STATUSES,
        help_text=_(
            "Industry-standard status: pending (new), ready_for_pickup (ready), "
            "out_for_delivery (in delivery), delivered."
        ),
    )
    status_internal = serializers.CharField(
        help_text=_("Internal Javi status code: new / created / on_the_way / delivered.")
    )
    tracking_url = serializers.CharField(
        allow_null=True, help_text=_("Public tracking page (set once delivery starts).")
    )
    recipient = RecipientSerializer()
    description = serializers.CharField(allow_blank=True)
    dest_address = serializers.CharField()
    dest_city = serializers.CharField(allow_blank=True)
    eta = serializers.CharField(
        allow_null=True, help_text=_("Estimated arrival, local HH:MM (set on start).")
    )
    notification = NotificationSerializer(
        allow_null=True, help_text=_("Latest 'on the way' notification receipt, if any.")
    )
    source = serializers.CharField(help_text=_("manual | api."))
    created_at = serializers.DateTimeField()


class DeliveryCreateSerializer(serializers.Serializer):
    recipient_name = serializers.CharField(help_text=_("Recipient full name."))
    recipient_phone = serializers.CharField(
        help_text=_("Recipient phone (any common Serbian format, normalized to E.164).")
    )
    address = serializers.CharField(help_text=_("Delivery address (geocoded server-side)."))
    description = serializers.CharField(
        required=False, allow_blank=True, default="", help_text=_("Optional order description.")
    )


class StartSerializer(serializers.Serializer):
    eta = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=_("Optional manual ETA in HH:MM (used when no route is available)."),
    )


class ResendSerializer(serializers.Serializer):
    recipient_phone = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=_("Optional new recipient phone to correct and resend."),
    )


# --- Сериализация доставки в dict (форма ответа — стабильный контракт) ----


def _on_the_way_notif(delivery: Delivery):
    return delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).first()


def _tracking_url(delivery: Delivery) -> str | None:
    token = getattr(delivery, "tracking_token", None)
    return _tracking_link(token.token) if token is not None else None


def serialize_delivery(delivery: Delivery) -> dict:
    notif = _on_the_way_notif(delivery)
    return {
        "id": delivery.id,
        "status": standard_status(delivery),
        "status_internal": delivery.status,
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


# --- Базовая вьюха с доступом к магазину ----------------------------------


class _ShopScopedView(GenericAPIView):
    """Base view: the API key's shop is `request.user`; all data is scoped to it."""

    @property
    def shop(self):
        return self.request.user

    def get_owned_delivery(self, pk: int) -> Delivery:
        """Доставка по pk в пределах магазина ключа. Иначе — 404 единым конвертом."""
        delivery = self.shop.deliveries.filter(pk=pk).first()
        if delivery is None:
            raise ApiError("not_found", _("Delivery not found."), status.HTTP_404_NOT_FOUND)
        return delivery


_DELIVERY_RESPONSES = {
    200: DeliverySerializer,
    404: OpenApiResponse(description=_("Delivery not found (or belongs to another shop).")),
}


# --- Эндпоинты ------------------------------------------------------------


class DeliveriesCollectionView(_ShopScopedView):
    serializer_class = DeliveryCreateSerializer

    @extend_schema(
        operation_id="deliveries_list",
        summary=_("List deliveries"),
        parameters=[
            OpenApiParameter(
                name="status",
                description=_(
                    "Filter by industry-standard status: pending, ready_for_pickup, "
                    "out_for_delivery, delivered."
                ),
                required=False,
                enum=STANDARD_STATUSES,
            ),
            OpenApiParameter(
                name="sort",
                description=_(
                    "Sort order. Default `created_at` (oldest first); use "
                    "`-created_at` for newest first."
                ),
                required=False,
                enum=["created_at", "-created_at"],
            ),
        ],
        responses={200: DeliverySerializer(many=True)},
    )
    def get(self, request):
        qs = self.shop.deliveries.filter(deleted_at__isnull=True)
        status_filter = request.query_params.get("status")
        if status_filter:
            internal = STATUS_MAP_REVERSE.get(status_filter, status_filter)
            qs = qs.filter(status=internal)
        # По умолчанию — старые → новые (Meta.ordering); ?sort=-created_at для обратного.
        if request.query_params.get("sort") == "-created_at":
            qs = qs.order_by("-created_at")
        data = [serialize_delivery(d) for d in qs]
        return Response(data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="deliveries_create",
        summary=_("Create a delivery"),
        description=_(
            "Creates a delivery (the address is geocoded server-side). Pass an "
            "`Idempotency-Key` header to safely retry — the same key returns the same "
            "delivery instead of creating a duplicate."
        ),
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description=_("Unique key to make creation idempotent (per shop)."),
            )
        ],
        request=DeliveryCreateSerializer,
        responses={
            201: DeliverySerializer,
            400: OpenApiResponse(description=_("Invalid phone or malformed JSON.")),
            422: OpenApiResponse(description=_("Missing required fields.")),
        },
        examples=[
            OpenApiExample(
                "Create",
                value={
                    "recipient_name": "Ana",
                    "recipient_phone": "064 123 4567",
                    "address": "Knez Mihailova 6, Beograd",
                    "description": "2 pizzas",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = DeliveryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            missing = [f for f in ("recipient_name", "recipient_phone", "address")
                       if f in serializer.errors]
            if missing:
                raise ApiError(
                    "invalid_request",
                    _("Missing required fields: %(fields)s.") % {"fields": ", ".join(missing)},
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            raise ApiError("invalid_request", _flatten_message(serializer.errors), 400)

        v = serializer.validated_data
        recipient_name = v["recipient_name"].strip()
        recipient_phone = v["recipient_phone"].strip()
        address = v["address"].strip()
        description = (v.get("description") or "").strip()

        missing = [
            f for f, val in (
                ("recipient_name", recipient_name),
                ("recipient_phone", recipient_phone),
                ("address", address),
            ) if not val
        ]
        if missing:
            raise ApiError(
                "invalid_request",
                _("Missing required fields: %(fields)s.") % {"fields": ", ".join(missing)},
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            phone = normalize_phone(recipient_phone)
        except InvalidPhone:
            raise ApiError("invalid_phone", _("Invalid recipient phone number."), 400) from None

        idem_key = request.headers.get("Idempotency-Key", "").strip()
        if idem_key:
            existing = (
                ApiIdempotencyKey.objects.filter(shop=self.shop, key=idem_key)
                .select_related("delivery")
                .first()
            )
            if existing is not None:
                return Response(serialize_delivery(existing.delivery), status=201)

        delivery, _geocoded = create_delivery(
            self.shop,
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
                        shop=self.shop, key=idem_key, delivery=delivery
                    )
            except IntegrityError:
                existing = (
                    ApiIdempotencyKey.objects.filter(shop=self.shop, key=idem_key)
                    .select_related("delivery")
                    .first()
                )
                if existing is not None:
                    delivery.delete()
                    return Response(serialize_delivery(existing.delivery), status=201)

        return Response(serialize_delivery(delivery), status=201)


class DeliveryDetailView(_ShopScopedView):
    serializer_class = DeliverySerializer

    @extend_schema(
        operation_id="deliveries_retrieve",
        summary=_("Get a delivery"),
        responses=_DELIVERY_RESPONSES,
    )
    def get(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        return Response(serialize_delivery(delivery), status=200)

    @extend_schema(
        operation_id="deliveries_delete",
        summary=_("Delete a delivery (soft)"),
        description=_("Soft-deletes the delivery; it can be restored via /restore."),
        responses={200: DeliverySerializer, 404: _DELIVERY_RESPONSES[404]},
    )
    def delete(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        soft_delete(delivery)
        return Response(serialize_delivery(delivery), status=200)


class DeliveryStartView(_ShopScopedView):
    serializer_class = StartSerializer

    @extend_schema(
        operation_id="deliveries_start",
        summary=_("Start delivery (dispatch)"),
        description=_(
            "Marks the delivery 'out for delivery': computes ETA, notifies the customer "
            "with a tracking link. If no route is available, pass `eta` (HH:MM)."
        ),
        request=StartSerializer,
        responses={
            200: DeliverySerializer,
            400: OpenApiResponse(description=_("Invalid eta format (expected HH:MM).")),
            404: _DELIVERY_RESPONSES[404],
            422: OpenApiResponse(description=_("Route unavailable — pass eta (HH:MM).")),
        },
    )
    def post(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        serializer = StartSerializer(data=request.data)
        serializer.is_valid(raise_exception=False)
        manual_eta = self._parse_eta((serializer.validated_data or {}).get("eta", ""))

        result = start_delivery(delivery, manual_eta=manual_eta)
        if result.needs_manual_eta:
            raise ApiError(
                "eta_required",
                _("Route is unavailable — pass eta (HH:MM) to start the delivery."),
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        delivery.refresh_from_db()
        return Response(serialize_delivery(delivery), status=200)

    @staticmethod
    def _parse_eta(eta_raw: str):
        eta_raw = (eta_raw or "").strip()
        if not eta_raw:
            return None
        try:
            parsed = datetime.strptime(eta_raw, "%H:%M").time()
        except ValueError:
            raise ApiError("invalid_eta", _("eta must be in HH:MM format."), 400) from None
        today = timezone.now().astimezone(BELGRADE).date()
        return datetime.combine(today, parsed, tzinfo=BELGRADE)


class DeliveryDispatchView(DeliveryStartView):
    """Алиас `/dispatch` для `/start` (паритет с UI «Dostava je počela»)."""

    @extend_schema(
        operation_id="deliveries_dispatch",
        summary=_("Dispatch (alias of start)"),
        description=_("Identical to POST /start; provided for naming parity with the UI."),
        request=StartSerializer,
        responses={200: DeliverySerializer, 404: _DELIVERY_RESPONSES[404]},
    )
    def post(self, request, pk: int):
        return super().post(request, pk)


class DeliveryReadyView(_ShopScopedView):
    serializer_class = DeliverySerializer

    @extend_schema(
        operation_id="deliveries_ready",
        summary=_("Mark ready for pickup"),
        description=_("Transitions a 'pending' delivery to 'ready_for_pickup' (new → ready)."),
        request=None,
        responses=_DELIVERY_RESPONSES,
    )
    def post(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        mark_ready(delivery)
        return Response(serialize_delivery(delivery), status=200)


class DeliveryDeliveredView(_ShopScopedView):
    serializer_class = DeliverySerializer

    @extend_schema(
        operation_id="deliveries_delivered",
        summary=_("Mark delivered"),
        description=_("Marks the delivery as delivered (optional manual confirmation)."),
        request=None,
        responses=_DELIVERY_RESPONSES,
    )
    def post(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        mark_delivered(delivery)
        return Response(serialize_delivery(delivery), status=200)


class DeliveryRestoreView(_ShopScopedView):
    serializer_class = DeliverySerializer

    @extend_schema(
        operation_id="deliveries_restore",
        summary=_("Restore a soft-deleted delivery"),
        request=None,
        responses=_DELIVERY_RESPONSES,
    )
    def post(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        restore(delivery)
        return Response(serialize_delivery(delivery), status=200)


class DeliveryResendView(_ShopScopedView):
    serializer_class = ResendSerializer

    @extend_schema(
        operation_id="deliveries_notifications_resend",
        summary=_("Resend the 'on the way' notification"),
        description=_(
            "Re-sends the 'on the way' notification (optionally to a corrected phone). "
            "Only valid after the delivery has started."
        ),
        request=ResendSerializer,
        responses={
            200: inline_serializer(
                name="ResendResult",
                fields={
                    "delivery": DeliverySerializer(),
                    "notification": NotificationSerializer(),
                },
            ),
            404: _DELIVERY_RESPONSES[404],
            409: OpenApiResponse(description=_("Delivery has not started — nothing to resend.")),
        },
    )
    def post(self, request, pk: int):
        delivery = self.get_owned_delivery(pk)
        serializer = ResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=False)
        raw_phone = (serializer.validated_data or {}).get("recipient_phone", "").strip()

        new_phone = None
        if raw_phone:
            try:
                new_phone = normalize_phone(raw_phone)
            except InvalidPhone:
                raise ApiError(
                    "invalid_phone", _("Invalid recipient phone number."), 400
                ) from None

        result = resend_on_the_way(delivery, new_phone=new_phone)
        if result is None:
            raise ApiError(
                "not_started",
                _("Delivery has not started — nothing to resend."),
                status.HTTP_409_CONFLICT,
            )
        delivery.refresh_from_db()
        body = serialize_delivery(delivery)
        return Response(
            {"delivery": body, "notification": body["notification"]}, status=200
        )


# --- Профиль магазина (паритет: редактирование магазина + вебхуки через API) ---


def serialize_shop(shop) -> dict:
    return {
        "name": shop.name,
        "address": shop.origin_address,
        "geocoded": shop.origin_lat is not None and shop.origin_lng is not None,
        "webhook_url": shop.webhook_url,
        "webhook_configured": bool(shop.webhook_url and shop.webhook_secret),
    }


class ShopSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, help_text=_("Store name."))
    address = serializers.CharField(
        required=False, allow_blank=True,
        help_text=_("Store address; geocoded server-side into the ETA origin."),
    )
    webhook_url = serializers.URLField(
        required=False, allow_blank=True,
        help_text=_("Merchant URL that receives signed event webhooks."),
    )
    webhook_secret = serializers.CharField(
        required=False, allow_blank=True,
        help_text=_("Secret for the Javi-Signature HMAC of webhook bodies."),
    )


class ShopView(_ShopScopedView):
    """Store profile: name, address (ETA origin) and webhook settings — GET and PATCH."""

    serializer_class = ShopSerializer

    @extend_schema(responses={200: ShopSerializer}, summary="Get store profile")
    def get(self, request):
        return Response(serialize_shop(self.shop), status=200)

    @extend_schema(
        request=ShopSerializer, responses={200: ShopSerializer},
        summary="Update store profile / webhook settings",
    )
    def patch(self, request):
        serializer = ShopSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            raise ApiError("invalid_request", _flatten_message(serializer.errors), 400)
        data = serializer.validated_data
        shop = self.shop
        fields = []
        for f in ("name", "webhook_url", "webhook_secret"):
            if f in data:
                setattr(shop, f, data[f])
                fields.append(f)
        if fields:
            shop.save(update_fields=fields)
        if data.get("address"):
            set_shop_origin(shop, data["address"])  # геокод origin (через сервис)
        return Response(serialize_shop(shop), status=200)
