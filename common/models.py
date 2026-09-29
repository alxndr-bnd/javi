from django.db import models


class RateLimitCounter(models.Model):
    """One fixed-window counter of common.ratelimit (key = sha256 of scope/identity/window)."""

    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.key[:12]}… = {self.count}"
