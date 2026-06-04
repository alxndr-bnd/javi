from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from common.timewindow import BELGRADE, format_eta
from notifications.models import Notification

from .forms import DeliveryForm, ManualEtaForm, RecipientPhoneForm, ShopOriginForm
from .models import Delivery
from .services import create_delivery, resend_on_the_way, set_shop_origin, start_delivery


class DeliveryListView(LoginRequiredMixin, TemplateView):
    """Кабинет магазина: доставки дня, сгруппированы по статусу, скоуплены по магазину."""

    template_name = "deliveries/delivery_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        shop = getattr(self.request.user, "shop", None)
        # Изоляция арендаторов: только доставки текущего магазина.
        deliveries = (
            list(shop.deliveries.prefetch_related("notifications")) if shop is not None else []
        )
        # Чип статуса уведомления «в пути» (для карточки) — без N+1.
        for d in deliveries:
            d.on_the_way_notif = next(
                (n for n in d.notifications.all() if n.kind == Notification.Kind.ON_THE_WAY), None
            )
        ctx["shop"] = shop
        ctx["deliveries"] = deliveries
        ctx["u_dostavi"] = [d for d in deliveries if d.status == Delivery.Status.ON_THE_WAY]
        ctx["spremno"] = [d for d in deliveries if d.status == Delivery.Status.CREATED]
        ctx["zavrseno"] = [d for d in deliveries if d.status == Delivery.Status.DELIVERED]
        return ctx


class ShopProfileView(LoginRequiredMixin, View):
    """Профиль «Prodavnica»: магазин задаёт/правит адрес (origin), он геокодируется."""

    template_name = "deliveries/shop_profile.html"

    def get(self, request):
        shop = getattr(request.user, "shop", None)  # изоляция: только свой магазин
        if shop is None:
            return render(request, self.template_name, {"form": None, "shop": None})
        form = ShopOriginForm(initial={"address": shop.origin_address})
        return render(request, self.template_name, {"form": form, "shop": shop})

    def post(self, request):
        shop = getattr(request.user, "shop", None)
        if shop is None:
            return render(request, self.template_name, {"form": None, "shop": None})
        form = ShopOriginForm(request.POST)
        if form.is_valid():
            if set_shop_origin(shop, form.cleaned_data["address"]):
                messages.success(request, "Adresa je sačuvana.")
                return redirect("deliveries:profile")  # PRG
            messages.error(
                request,
                "Nismo prepoznali adresu. Proverite i pokušajte ponovo.",
            )
        return render(request, self.template_name, {"form": form, "shop": shop})


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
            _, geocoded = create_delivery(
                request.user.shop,
                recipient_name=form.cleaned_data["recipient_name"],
                phone=phone,
                dest_address=form.cleaned_data["dest_address"],
                description=form.cleaned_data["description"],
            )
            messages.success(request, "Dostava je dodata.")
            if phone.is_risky:
                messages.warning(request, "Broj nije srpski mobilni — proverite.")
            if not geocoded:
                messages.warning(request, "Adresu nismo prepoznali — proverite je kasnije.")
            return redirect("deliveries:list")
        return render(request, self.template_name, {"form": form})

    def _require_origin(self, request):
        """Без заданного origin доставку не завести — отправляем в профиль."""
        shop = getattr(request.user, "shop", None)
        if shop is None or shop.origin_lat is None:
            messages.info(request, "Prvo podesite adresu prodavnice.")
            return redirect("deliveries:profile")
        return None


class DeliveryStartView(LoginRequiredMixin, View):
    """«Dostava je počela»: расчёт ETA + уведомление получателю. При сбое — ручной ETA."""

    template_name = "deliveries/delivery_manual_eta.html"

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop)  # изоляция

        # Ветка ручного ETA (повторный POST с временем).
        if "eta_time" in request.POST:
            form = ManualEtaForm(request.POST)
            if not form.is_valid():
                return render(request, self.template_name, {"form": form, "delivery": delivery})
            today = timezone.now().astimezone(BELGRADE).date()
            manual_eta = datetime.combine(today, form.cleaned_data["eta_time"], tzinfo=BELGRADE)
            result = start_delivery(delivery, manual_eta=manual_eta)
        else:
            result = start_delivery(delivery)
            if result.needs_manual_eta:
                messages.info(request, "Ruta nije dostupna — unesite vreme dolaska ručno.")
                return render(
                    request, self.template_name, {"form": ManualEtaForm(), "delivery": delivery}
                )

        if result.already:
            messages.info(request, "Dostava je već u toku.")
        elif result.ok:
            messages.success(request, f"Kupac obavešten · stiže do {format_eta(result.eta_at)}")
            if not result.sent:
                messages.warning(request, "Poruka nije poslata — pokušajte ponovo kasnije.")
        return redirect("deliveries:list")


class DeliveryResendView(LoginRequiredMixin, View):
    """Переотправка уведомления при сбое (FR-25): правка номера + «Pošalji ponovo»."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop)
        form = RecipientPhoneForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Neispravan broj. Npr. 064 123 4567")
            return redirect("deliveries:list")
        result = resend_on_the_way(delivery, new_phone=form.cleaned_data["phone_result"])
        if result is None:
            messages.error(request, "Nije moguće ponovo poslati.")
        elif result.ok:
            messages.success(request, "Poruka je ponovo poslata.")
        else:
            messages.warning(request, "Poruka nije poslata — proverite broj.")
        return redirect("deliveries:list")


class DeliveryMarkDeliveredView(LoginRequiredMixin, View):
    """Ручная отметка «Доставлено» (FR-26, опц.). Система от неё не зависит."""

    def post(self, request, pk):
        shop = getattr(request.user, "shop", None)
        delivery = get_object_or_404(Delivery, pk=pk, shop=shop)
        delivery.status = Delivery.Status.DELIVERED
        delivery.save(update_fields=["status"])
        messages.success(request, "Označeno kao isporučeno.")
        return redirect("deliveries:list")
