import hashlib
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from common.phone import InvalidPhone, normalize_phone
from common.timewindow import BELGRADE, format_eta
from notifications.models import Notification, OptOut

from .forms import DeliveryForm, ManualEtaForm, RecipientPhoneForm, ShopOriginForm
from .models import ApiKey, Delivery
from .services import (
    compute_eta,
    create_delivery,
    eta_unavailable_reason,
    resend_on_the_way,
    set_shop_origin,
    start_delivery,
)


def _deliveries_signature(shop) -> str:
    """Сигнатура активных доставок магазина: меняется при новом/удалённом заказе и смене статуса."""
    if shop is None:
        return ""
    rows = shop.deliveries.filter(deleted_at__isnull=True).values_list("id", "status", "deleted_at")
    raw = ";".join(f"{i}:{s}" for i, s, _ in rows)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class DeliveryFeedView(LoginRequiredMixin, View):
    """Лёгкий поллинг: возвращает сигнатуру списка для авто-обновления без перезагрузки."""

    def get(self, request):
        shop = getattr(request.user, "shop", None)
        return JsonResponse({"sig": _deliveries_signature(shop)})


class DeliveryListView(LoginRequiredMixin, TemplateView):
    """Кабинет магазина: список или канбан-доска (по предпочтению магазина)."""

    def get_template_names(self):
        shop = getattr(self.request.user, "shop", None)
        if shop is not None and shop.kanban_view:
            return ["deliveries/delivery_board.html"]
        return ["deliveries/delivery_list.html"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        shop = getattr(self.request.user, "shop", None)
        # Изоляция арендаторов: только доставки текущего магазина.
        deliveries = (
            list(
                shop.deliveries.filter(deleted_at__isnull=True)
                .select_related("rating")
                .prefetch_related("notifications")
            )
            if shop is not None
            else []
        )
        # Чип статуса уведомления «в пути» (для карточки) — без N+1.
        for d in deliveries:
            d.on_the_way_notif = next(
                (n for n in d.notifications.all() if n.kind == Notification.Kind.ON_THE_WAY), None
            )
        # Отписавшиеся номера среди доставок магазина — одним запросом.
        phones = {d.recipient_phone for d in deliveries}
        opted = (
            set(OptOut.objects.filter(phone__in=phones).values_list("phone", flat=True))
            if phones
            else set()
        )
        for d in deliveries:
            d.opted_out = d.recipient_phone in opted
        ctx["shop"] = shop
        ctx["deliveries"] = deliveries
        ctx["novo"] = [d for d in deliveries if d.status == Delivery.Status.NEW]
        ctx["u_dostavi"] = [d for d in deliveries if d.status == Delivery.Status.ON_THE_WAY]
        ctx["spremno"] = [d for d in deliveries if d.status == Delivery.Status.CREATED]
        ctx["zavrseno"] = [d for d in deliveries if d.status == Delivery.Status.DELIVERED]
        ctx["completed_expanded"] = bool(shop and shop.completed_expanded)
        ctx["kanban_view"] = bool(shop and shop.kanban_view)
        ctx["feed_sig"] = _deliveries_signature(shop)
        return ctx


class ShopProfileView(LoginRequiredMixin, View):
    """Профиль «Prodavnica»: магазин задаёт/правит адрес (origin), он геокодируется."""

    template_name = "deliveries/shop_profile.html"

    def _context(self, shop, form):
        api_keys = list(shop.api_keys.all()) if shop is not None else []
        return {"form": form, "shop": shop, "api_keys": api_keys}

    def get(self, request):
        shop = getattr(request.user, "shop", None)  # изоляция: только свой магазин
        if shop is None:
            return render(request, self.template_name, self._context(None, None))
        form = ShopOriginForm(initial={"name": shop.name, "address": shop.origin_address})
        return render(request, self.template_name, self._context(shop, form))

    def post(self, request):
        shop = getattr(request.user, "shop", None)
        if shop is None:
            return render(request, self.template_name, self._context(None, None))
        form = ShopOriginForm(request.POST)
        if form.is_valid():
            # Название сохраняем всегда (независимо от геокода адреса).
            shop.name = form.cleaned_data["name"]
            shop.save(update_fields=["name"])
            if set_shop_origin(shop, form.cleaned_data["address"]):
                messages.success(request, _("Saved."))
                return redirect("deliveries:profile")  # PRG
            messages.error(
                request,
                _(
                    "Name saved, but we could not recognize the address. "
                    "Please check and try again."
                ),
            )
        return render(request, self.template_name, self._context(shop, form))


class ApiKeyCreateView(LoginRequiredMixin, View):
    """Генерация API-ключа. Полный ключ показывается ОДИН раз через message."""

    def post(self, request):
        shop = getattr(request.user, "shop", None)
        if shop is None:
            messages.error(request, _("Account is not linked to a store."))
            return redirect("deliveries:profile")
        _key_obj, full_key = ApiKey.generate(shop)
        messages.success(
            request,
            _("API key created. Copy it now — it will not be shown again: %(key)s")
            % {"key": full_key},
        )
        return redirect("deliveries:profile")


class ApiKeyRevokeView(LoginRequiredMixin, View):
    """Отзыв API-ключа (скоуп по магазину)."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        api_key = get_object_or_404(ApiKey, pk=pk, shop=shop)  # изоляция
        api_key.revoke()
        messages.success(request, _("API key revoked."))
        return redirect("deliveries:profile")


class DeliveryCreateView(LoginRequiredMixin, View):
    """Форма «Nova dostava»: завести доставку (телефон → E.164, адрес → геокод)."""

    template_name = "deliveries/delivery_form.html"

    def get(self, request):
        redirect_resp = self._require_origin(request)
        if redirect_resp is not None:
            return redirect_resp
        return render(request, self.template_name, {"form": DeliveryForm()})

    def post(self, request):
        redirect_resp = self._require_origin(request)
        if redirect_resp is not None:
            return redirect_resp

        form = DeliveryForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data["phone_result"]
            _new, geocoded = create_delivery(
                request.user.shop,
                recipient_name=form.cleaned_data["recipient_name"],
                phone=phone,
                dest_address=form.cleaned_data["dest_address"],
                description=form.cleaned_data["description"],
            )
            messages.success(request, _("Delivery added."))
            if phone.is_risky:
                messages.warning(request, _("The number is not a Serbian mobile — please check."))
            if not geocoded:
                messages.warning(
                    request,
                    _("We could not recognize the address — please check it later."),
                )
            return redirect("deliveries:list")
        return render(request, self.template_name, {"form": form})

    def _require_origin(self, request):
        """Без заданного origin доставку не завести — отправляем в профиль."""
        shop = getattr(request.user, "shop", None)
        if shop is None or shop.origin_lat is None:
            messages.info(request, _("First set your store address."))
            return redirect("deliveries:profile")
        return None


class RecipientLookupView(LoginRequiredMixin, View):
    """Автоподстановка клиента по номеру: имя + адрес из последней доставки магазина."""

    def get(self, request):
        shop = getattr(request.user, "shop", None)
        if shop is None:
            return JsonResponse({"found": False})
        try:
            e164 = normalize_phone(request.GET.get("phone", "")).e164
        except InvalidPhone:
            return JsonResponse({"found": False})
        # Изоляция: ищем только среди (не удалённых) доставок своего магазина.
        last = (
            shop.deliveries.filter(recipient_phone=e164, deleted_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if last is None:
            return JsonResponse({"found": False})
        return JsonResponse(
            {"found": True, "name": last.recipient_name, "address": last.dest_address}
        )


class DeliveryStartView(LoginRequiredMixin, View):
    """«Dostava je počela»: 1) показать рассчитанное время → 2) подтверждение шлёт уведомление."""

    template_name = "deliveries/delivery_confirm_eta.html"

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop)  # изоляция

        # Шаг 2: подтверждение (с временем) → фиксируем статус + шлём.
        if "eta_time" in request.POST:
            form = ManualEtaForm(request.POST)
            if not form.is_valid():
                return render(request, self.template_name, {"form": form, "delivery": delivery})
            today = timezone.now().astimezone(BELGRADE).date()
            manual_eta = datetime.combine(today, form.cleaned_data["eta_time"], tzinfo=BELGRADE)
            result = start_delivery(delivery, manual_eta=manual_eta)
            if result.already:
                messages.info(request, _("Delivery is already in progress."))
            elif result.ok:
                messages.success(
                    request,
                    _("Customer notified · arriving by %(time)s")
                    % {"time": format_eta(result.eta_at)},
                )
                if not result.sent:
                    messages.warning(request, _("Message not sent — try again later."))
            return redirect("deliveries:list")

        # Шаг 1: уже стартовала? — не дублируем.
        if delivery.status == Delivery.Status.ON_THE_WAY:
            messages.info(request, _("Delivery is already in progress."))
            return redirect("deliveries:list")

        # Шаг 1: считаем ETA (now + время в пути + запас) и показываем экран подтверждения.
        eta = compute_eta(delivery)
        computed = format_eta(eta) if eta else None
        initial = {"eta_time": computed} if computed else {}
        reason = None if computed else eta_unavailable_reason(delivery)
        return render(
            request,
            self.template_name,
            {
                "form": ManualEtaForm(initial=initial),
                "delivery": delivery,
                "computed_eta": computed,
                "eta_reason": reason,
            },
        )


class DeliveryResendView(LoginRequiredMixin, View):
    """Переотправка уведомления при сбое (FR-25): правка номера + «Pošalji ponovo»."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop)
        form = RecipientPhoneForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Invalid number. E.g. 064 123 4567"))
            return redirect("deliveries:list")
        result = resend_on_the_way(delivery, new_phone=form.cleaned_data["phone_result"])
        if result is None:
            messages.error(request, _("Unable to resend."))
        elif result.ok:
            messages.success(request, _("Message resent."))
        else:
            messages.warning(request, _("Message not sent — check the number."))
        return redirect("deliveries:list")


class DeliveryMarkDeliveredView(LoginRequiredMixin, View):
    """Ручная отметка «Доставлено» (FR-26, опц.). Система от неё не зависит."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop)
        delivery.status = Delivery.Status.DELIVERED
        delivery.save(update_fields=["status"])
        messages.success(request, _("Marked as delivered."))
        return redirect("deliveries:list")


class DeliveryMarkReadyView(LoginRequiredMixin, View):
    """Новый заказ → готов к старту (Novo → Spremno)."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop, deleted_at__isnull=True)
        if delivery.status == Delivery.Status.NEW:
            delivery.status = Delivery.Status.CREATED
            delivery.save(update_fields=["status"])
        return redirect("deliveries:list")


class SetViewView(LoginRequiredMixin, View):
    """Переключение вида кабинета: список / канбан-доска (сохраняется в профиле)."""

    def post(self, request):
        shop = getattr(request.user, "shop", None)
        if shop is not None:
            shop.kanban_view = request.POST.get("mode") == "board"
            shop.save(update_fields=["kanban_view"])
        return redirect("deliveries:list")


class DeliveryDeleteView(LoginRequiredMixin, View):
    """Мягкое удаление доставки (soft delete). Скоуп по магазину."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop, deleted_at__isnull=True)
        delivery.deleted_at = timezone.now()
        delivery.save(update_fields=["deleted_at"])
        messages.success(request, _("Delivery deleted."))
        return redirect("deliveries:list")


class DeletedDeliveriesView(LoginRequiredMixin, TemplateView):
    """Раздел «Obrisane»: мягко удалённые доставки (с возможностью восстановить)."""

    template_name = "deliveries/deleted_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        shop = getattr(self.request.user, "shop", None)
        ctx["deleted"] = (
            list(shop.deliveries.filter(deleted_at__isnull=False)) if shop else []
        )
        return ctx


class DeliveryRestoreView(LoginRequiredMixin, View):
    """Восстановление мягко удалённой доставки."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop, deleted_at__isnull=False)
        delivery.deleted_at = None
        delivery.save(update_fields=["deleted_at"])
        messages.success(request, _("Delivery restored."))
        return redirect("deliveries:deleted")


class ApiDocsView(LoginRequiredMixin, TemplateView):
    """Страница про API для интеграции (полноценная — в работе, см. план API)."""

    template_name = "deliveries/api_docs.html"


class ToggleCompletedView(LoginRequiredMixin, View):
    """Сохранить состояние секции «Завершённые» (развёрнута/свёрнута) в профиле."""

    def post(self, request):
        shop = getattr(request.user, "shop", None)
        if shop is not None:
            shop.completed_expanded = request.POST.get("expanded") == "1"
            shop.save(update_fields=["completed_expanded"])
        return JsonResponse({"ok": True})
