"""Shop billing (SERBITO-593): one Whop subscription per shop, 30 € per month.

A shop without a ``ShopSubscription`` row is on the free trial. The trial is computed, not
stored (``billing.services.trial_ends_at``), so existing shops need no data change.
"""

from django.db import models

from deliveries.models import Shop


class ShopSubscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial", "trial"
        ACTIVE = "active", "active"
        PAST_DUE = "past_due", "past_due"
        CANCELED = "canceled", "canceled"

    shop = models.OneToOneField(Shop, on_delete=models.CASCADE, related_name="subscription")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    # Whop state, as the last webhook or sync saw it.
    whop_membership_id = models.CharField(max_length=64, blank=True, db_index=True)
    whop_checkout_id = models.CharField(max_length=64, blank=True, db_index=True)
    whop_status = models.CharField("Whop status", max_length=20, blank=True)
    manage_url = models.URLField("Whop manage URL", max_length=500, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    past_due_since = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    # Staff override: the free trial ends at this time instead of the computed one.
    trial_ends_override = models.DateTimeField(
        "trial ends (override)",
        null=True,
        blank=True,
        help_text="Empty: registration (or JAVI_BILLING_START_DATE) + JAVI_BILLING_TRIAL_DAYS.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "shop subscription"

    def __str__(self):
        return f"{self.shop} — {self.status}"


class BillingPayment(models.Model):
    """One Whop payment of a shop subscription (first charge or renewal). For the report."""

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="billing_payments")
    whop_payment_id = models.CharField(max_length=64, unique=True)
    whop_membership_id = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    billing_reason = models.CharField(max_length=40, blank=True)
    paid_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at"]

    def __str__(self):
        return f"{self.whop_payment_id} {self.amount} {self.currency}"
