from django.db import models


class RateLimitCounter(models.Model):
    """One fixed-window counter of common.ratelimit (key = sha256 of scope/identity/window)."""

    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.key[:12]}… = {self.count}"


class FunnelCount(models.Model):
    """Daily count of one request-funnel step (SERBITO-595). No visitor data: a number per day.

    Steps counted here are the ones that leave no row of their own: a landing page view
    (``landing_view``, per page language) and an open registration form (``signup_start``).
    Sign-ups and activated shops come from ``Shop`` and ``Delivery`` (common/funnel.py).
    """

    day = models.DateField()
    event = models.CharField(max_length=32)
    lang = models.CharField(max_length=8, blank=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["day", "event", "lang"], name="funnel_day_event_lang")
        ]

    def __str__(self):
        return f"{self.day} {self.event} {self.lang or '-'} = {self.count}"
