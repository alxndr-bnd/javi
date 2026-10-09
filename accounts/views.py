import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.generic import CreateView

from common import funnel, ratelimit
from common.client_ip import client_ip
from deliveries.models import Shop
from deliveries.services import set_shop_origin

from .forms import RegisterForm

logger = logging.getLogger(__name__)

_DAY = 24 * 60 * 60


class RegisterView(CreateView):
    """Self-service registration: create User + linked Shop, then log in.

    Signup is open, so (SERBITO-357): at most SIGNUP_LIMIT_PER_IP_DAY new stores per client
    IP a day, and every new store is logged as a WARNING (event "shop.signup") — the owner
    sees it in Cloud Logging and can verify the store or leave it on trial limits.
    """

    form_class = RegisterForm
    template_name = "accounts/register.html"

    def _signup_limit_reached(self) -> bool:
        return ratelimit.exceeded(
            "signup",
            client_ip(self.request),
            limit=settings.SIGNUP_LIMIT_PER_IP_DAY,
            window_seconds=_DAY,
        )

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if funnel.is_human(request):  # SERBITO-595: the sign-up form was opened
            funnel.record(funnel.SIGNUP_START, request.LANGUAGE_CODE[:2])
        return response

    def post(self, request, *args, **kwargs):
        if self._signup_limit_reached():
            self.object = None
            form = self.get_form()
            form.add_error(
                None, _("Too many new accounts from your network today. Try again tomorrow.")
            )
            logger.warning(
                "Signup refused: per-IP daily limit reached", extra={"event": "shop.signup_limit"}
            )
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()
            shop = Shop.objects.create(owner=user, name=form.cleaned_data["store_name"])
        ratelimit.hit(
            "signup",
            client_ip(self.request),
            limit=settings.SIGNUP_LIMIT_PER_IP_DAY,
            window_seconds=_DAY,
        )
        logger.warning(
            "New store signed up: %r (shop %s) — on trial limits until verified",
            shop.name,
            shop.pk,
            extra={"event": "shop.signup", "shop_id": shop.pk, "shop_name": shop.name},
        )
        login(self.request, user)
        funnel.queue_ga_event(self.request, "signup_complete")  # after login: new session
        address = form.cleaned_data.get("store_address", "").strip()
        if address and not set_shop_origin(shop, address):
            messages.warning(
                self.request,
                _("We could not recognize the store address. Check it in “Store”."),
            )
        return redirect(settings.LOGIN_REDIRECT_URL)
