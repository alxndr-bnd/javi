import uuid

from django.db import models


class Notification(models.Model):
    """Сообщение получателю по доставке. Идемпотентность — по logical_message_id."""

    class Kind(models.TextChoices):
        ON_THE_WAY = "on_the_way", "U dostavi"
        RATING_REQUEST = "rating_request", "Ocena"

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        VIBER = "viber", "Viber"
        WHATSAPP = "whatsapp", "WhatsApp"
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
    channel = models.CharField(max_length=16, choices=Channel.choices, blank=True)
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
            ),
            # Одно логическое сообщение на (delivery, kind, logical_message_id):
            # повторная отправка генерирует новый logical_message_id → новое сообщение,
            # но одну и ту же логическую отправку нельзя записать дважды.
            models.UniqueConstraint(
                fields=["delivery", "kind", "logical_message_id"],
                name="uniq_logical_message_per_delivery_kind",
            ),
        ]

    def __str__(self):
        return f"{self.kind} → delivery {self.delivery_id} ({self.status})"


class NotificationAttempt(models.Model):
    """Одна попытка отправки логического сообщения по конкретному каналу.

    Цепочка fallback (напр. Viber → SMS) даёт по одной строке на канал, в порядке
    попыток. Победившая попытка (ok=True) определяет канал/provider_message_id на
    родительском Notification.
    """

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="attempts"
    )
    channel = models.CharField(max_length=16, choices=Notification.Channel.choices)
    ok = models.BooleanField(default=False)
    provider_message_id = models.CharField(max_length=128, blank=True)
    attempt_no = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["attempt_no"]

    def __str__(self):
        outcome = "ok" if self.ok else "fail"
        return f"attempt {self.attempt_no} {self.channel} ({outcome})"


class OptOut(models.Model):
    """Блоклист: номер, отписавшийся от не-критичных сообщений (зеркалит Infobip)."""

    phone = models.CharField("телефон (E.164)", max_length=20, unique=True)
    scope = models.CharField(max_length=10, default="number")  # number | shop (later)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.phone
