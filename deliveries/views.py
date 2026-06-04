from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from .forms import ShopOriginForm
from .services import set_shop_origin


class DeliveryListView(LoginRequiredMixin, TemplateView):
    """Кабинет магазина: список доставок дня (в 1.1 — пустой, скоуплен по магазину)."""

    template_name = "deliveries/delivery_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        shop = getattr(self.request.user, "shop", None)
        # Изоляция арендаторов: показываем только доставки текущего магазина.
        # Модель Delivery появится в Story 1.3 — пока список пуст.
        ctx["shop"] = shop
        ctx["deliveries"] = []
        return ctx


class ShopProfileView(LoginRequiredMixin, View):
    """Профиль «Prodavnica»: магазин задаёт/правит адрес (origin), он геокодируется."""

    template_name = "deliveries/shop_profile.html"

    def get(self, request):
        shop = request.user.shop  # изоляция: только свой магазин
        form = ShopOriginForm(initial={"address": shop.origin_address})
        return render(request, self.template_name, {"form": form, "shop": shop})

    def post(self, request):
        shop = request.user.shop
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
