import uuid

from django.db import models


class Notification(models.Model):
    """Сообщение получателю по доставке. Идемпотентность — по logical_message_id."""

    class Kind(models.TextChoices):
        ON_THE_WAY = "on_the_way", "U dostavi"
        RATING_REQUEST = "rating_request", "Ocena"

    class Channel(models.TextChoices):
        VIBER = "viber", "Viber"
        SMS = "sms", "SMS"

    class Status(models.TextChoices):
        QUEUED = "queued", "queued"
        SENT = "sent", "sent"
        DELIVERED = "delivered", "delivered"
        READ = "read", "read"
        FAILED = "failed", "failed"

    delivery = models.ForeignKey(
        "deliveries.Delivery", on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    channel = models.CharField(max_length=6, choices=Channel.choices, blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True)
    logical_message_id = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Один «в пути» на доставку — гарантия идемпотентности старта.
            models.UniqueConstraint(
                fields=["delivery"],
                condition=models.Q(kind="on_the_way"),
                name="uniq_on_the_way_per_delivery",
            )
        ]

    def __str__(self):
        return f"{self.kind} → delivery {self.delivery_id} ({self.status})"
