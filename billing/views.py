"""Billing views (SERBITO-593): start a Whop checkout, the return page and the Whop webhook."""

from __future__ import annotations

import json
import logging
import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services, whop

logger = logging.getLogger(__name__)

#: The dashboard "Send test webhook" uses a placeholder business id: a WARNING, not an ERROR.
WHOP_TEST_ACCOUNT = re.compile(r"biz_x+")

MEMBERSHIP_PREFIX = "membership."
EVENT_PAID = "payment.succeeded"
EVENTS_PAYMENT_PROBLEM = {"payment.failed", "payment.requires_action"}
EVENTS_REFUND = {"refund.created", "refund.updated"}


def _shop_or_404(request):
    if not services.enabled():
        raise Http404
    shop = getattr(request.user, "shop", None)
    if shop is None:
        raise Http404
    return shop


class SubscribeView(LoginRequiredMixin, View):
    """POST: create a Whop checkout and send the shop there (or to Whop's manage page)."""

    def post(self, request):
        shop = _shop_or_404(request)
        info = services.summary(shop)
        if info is not None and not info.can_subscribe:
            if info.manage_url:
                return redirect(info.manage_url)
            messages.info(request, _("Your subscription is already active."))
            return redirect("deliveries:profile")
        try:
            url = services.start_checkout(shop)
        except services.BillingError as exc:
            logger.error("billing: checkout for shop %s failed: %s", shop.pk, exc)
            messages.error(
                request, _("We could not open the payment page. Please try again later.")
            )
            return redirect("deliveries:profile")
        return redirect(url)


class ReturnView(LoginRequiredMixin, View):
    """Whop sends the shop back here. The webhook, not this page, activates the subscription."""

    def get(self, request):
        _shop_or_404(request)
        messages.success(
            request,
            _(
                "Thank you! Your subscription becomes active as soon as Whop confirms it, "
                "usually within a minute."
            ),
        )
        return redirect("deliveries:profile")


def _whop_headers(request) -> dict:
    return {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
    }


@csrf_exempt
@require_POST
def whop_webhook(request):
    """Whop events for javi subscriptions. Works with the flag off too, so the state is right.

    The Whop business is shared with serbito, so serbito payments arrive here as well. They
    carry no javi shop token and another product: logged at INFO and answered 200.
    """
    secret = whop.webhook_secret()
    if not secret:
        logger.error("billing webhook: WHOP_WEBHOOK_SECRET is not set")
        return JsonResponse({"error": "not configured"}, status=500)
    if not whop.verify_signature(request.body, _whop_headers(request), secret):
        logger.warning("billing webhook: signature verification failed")
        return JsonResponse({"error": "bad signature"}, status=401)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "bad payload"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "bad payload"}, status=400)
    event = str(payload.get("type") or "")
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}

    account = str(payload.get("account_id") or payload.get("company_id") or whop.account_of(data))
    if account and account != whop.company_id():
        level = logging.WARNING if WHOP_TEST_ACCOUNT.fullmatch(account) else logging.ERROR
        logger.log(level, "billing webhook: %s for account %s — ignored", event, account)
        return JsonResponse({"ok": True})

    origin = "billing webhook"
    if event.startswith(MEMBERSHIP_PREFIX):
        membership_id = str(data.get("id") or "")
        if membership_id.startswith("mem_") and services.is_ours(data):
            services.sync_membership(membership_id, origin=origin, fallback=data)
    elif event == EVENT_PAID:
        payment = services.record_payment(data, origin=origin)
        if payment is not None and payment.whop_membership_id:
            services.sync_membership(payment.whop_membership_id, origin=origin)
    elif event in EVENTS_PAYMENT_PROBLEM:
        membership_id = whop.membership_of(data)
        if (
            membership_id
            and services.is_ours(data)
            and services.find_shop(data, membership_id=membership_id)
        ):
            logger.warning("billing webhook: %s for membership %s", event, membership_id)
            services.sync_membership(membership_id, origin=origin)
    elif event in EVENTS_REFUND:
        if str(data.get("status") or "succeeded") == "succeeded":
            payment_id = str(data.get("payment_id") or whop.nested_id(data, "payment"))
            if payment_id:
                services.record_refund(payment_id, origin=origin)
    return JsonResponse({"ok": True})
