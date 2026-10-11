"""Admin: paying shops and their Whop payments (SERBITO-593)."""

from django.contrib import admin
from django.db.models import Sum

from . import services
from .models import BillingPayment, ShopSubscription


@admin.register(ShopSubscription)
class ShopSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "shop",
        "status",
        "whop_status",
        "current_period_end",
        "cancel_at_period_end",
        "trial_ends",
        "paid_total",
        "updated_at",
    )
    list_filter = ("status", "cancel_at_period_end")
    search_fields = ("shop__name", "shop__owner__email", "whop_membership_id")
    list_select_related = ("shop",)
    readonly_fields = (
        "status",
        "whop_membership_id",
        "whop_checkout_id",
        "whop_status",
        "manage_url",
        "current_period_end",
        "cancel_at_period_end",
        "past_due_since",
        "activated_at",
        "canceled_at",
        "created_at",
        "updated_at",
    )

    @admin.display(description="trial ends")
    def trial_ends(self, obj):
        return services.trial_ends_at(obj.shop)

    @admin.display(description="paid (net of refunds)")
    def paid_total(self, obj):
        totals = obj.shop.billing_payments.values("currency").annotate(
            paid=Sum("amount"), refunded=Sum("refunded_amount")
        )
        return ", ".join(f"{t['paid'] - t['refunded']} {t['currency']}" for t in totals) or "—"

    def has_add_permission(self, request):
        return False  # rows come from checkouts and Whop events


@admin.register(BillingPayment)
class BillingPaymentAdmin(admin.ModelAdmin):
    list_display = ("whop_payment_id", "shop", "amount", "currency", "refunded_amount", "paid_at")
    list_filter = ("currency",)
    search_fields = ("whop_payment_id", "whop_membership_id", "shop__name")
    date_hierarchy = "paid_at"
    list_select_related = ("shop",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
