import uuid

from django.db import models
from django.utils import timezone


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


class TelegramContact(models.Model):
    """Opt-in получателя в Telegram: бот не может писать первым, поэтому Telegram —
    канал только для тех, кто сам нажал /start (поделился контактом). Храним chat_id
    по нормализованному номеру (E.164) — `TelegramProvider` ищет по нему получателя.
    """

    phone = models.CharField("телефон (E.164)", max_length=20, unique=True)
    chat_id = models.CharField("Telegram chat id", max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.phone} → {self.chat_id}"


class OptOut(models.Model):
    """Блоклист: номер, отписавшийся от не-критичных сообщений (зеркалит Infobip)."""

    phone = models.CharField("телефон (E.164)", max_length=20, unique=True)
    scope = models.CharField(max_length=10, default="number")  # number | shop (later)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.phone


class OutboundSend(models.Model):
    """Журнал отправок получателям — основа лимитов (SERBITO-345, см. notifications/quotas.py).

    Строка пишется ДО вызова провайдера, когда отправка прошла все лимиты: считаем попытки,
    а не только успешные (иначе сбойные номера жгли бы квоту бесплатно). Notification
    переиспользуется при resend, поэтому считать по нему нельзя — нужен отдельный журнал.
    SET_NULL: удаление магазина/доставки не обнуляет глобальный счётчик и счётчик номера.
    """

    class Kind(models.TextChoices):
        ON_THE_WAY = "on_the_way", "on_the_way"
        RESEND = "resend", "resend"
        RATING_REQUEST = "rating_request", "rating_request"

    shop = models.ForeignKey(
        "deliveries.Shop", on_delete=models.SET_NULL, null=True, related_name="outbound_sends"
    )
    delivery = models.ForeignKey(
        "deliveries.Delivery", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    phone = models.CharField("телефон (E.164)", max_length=20)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shop", "created_at"], name="outbound_shop_created"),
            models.Index(fields=["phone", "created_at"], name="outbound_phone_created"),
            models.Index(fields=["delivery", "kind"], name="outbound_delivery_kind"),
        ]

    def __str__(self):
        return f"{self.kind} → {self.phone} (shop {self.shop_id})"
