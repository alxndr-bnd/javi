from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from .forms import DeliveryForm, ShopOriginForm
from .models import Delivery
from .services import create_delivery, set_shop_origin


class DeliveryListView(LoginRequiredMixin, TemplateView):
    """Кабинет магазина: доставки дня, сгруппированы по статусу, скоуплены по магазину."""

    template_name = "deliveries/delivery_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        shop = getattr(self.request.user, "shop", None)
        # Изоляция арендаторов: только доставки текущего магазина.
        deliveries = list(shop.deliveries.all()) if shop is not None else []
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
