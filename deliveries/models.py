import secrets

from django.conf import settings
from django.db import models


def _new_tracking_token() -> str:
    """Непредсказуемый URL-safe токен для публичной страницы статуса."""
    return secrets.token_urlsafe(24)


class Shop(models.Model):
    """Магазин — арендатор Javi. 1:1 с пользователем."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shop",
    )
    name = models.CharField("название", max_length=200)

    # origin (адрес магазина) — точка отсчёта ETA. Заполняется в Story 1.2.
    origin_address = models.CharField("адрес магазина", max_length=300, blank=True)
    origin_lat = models.FloatField("широта", null=True, blank=True)
    origin_lng = models.FloatField("долгота", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Delivery(models.Model):
    """Доставка дня: один получатель, адрес назначения, телефон, статус."""

    class Status(models.TextChoices):
        CREATED = "created", "Spremno"  # готово к старту
        ON_THE_WAY = "on_the_way", "U dostavi"
        DELIVERED = "delivered", "Završeno"

    class Source(models.TextChoices):
        MANUAL = "manual", "manual"
        API = "api", "api"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="deliveries")
    recipient_name = models.CharField("имя получателя", max_length=200)
    recipient_phone = models.CharField("телефон (E.164)", max_length=20)
    # Немобильный/иностранный номер — пометка флагом риска (FR-4).
    phone_risk = models.BooleanField("флаг риска номера", default=False)
    dest_address = models.CharField("адрес назначения", max_length=300)
    dest_lat = models.FloatField("широта", null=True, blank=True)
    dest_lng = models.FloatField("долгота", null=True, blank=True)
    description = models.CharField("описание", max_length=300, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CREATED)
    # ETA/старт (Story 2.1): рассчитывается при «Dostava je počela».
    eta_at = models.DateTimeField("ETA (UTC)", null=True, blank=True)
    eta_source = models.CharField("источник ETA", max_length=6, blank=True)  # auto | manual
    started_at = models.DateTimeField("старт доставки", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient_name} — {self.dest_address}"


class TrackingToken(models.Model):
    """Непредсказуемый токен для публичной страницы статуса (без логина)."""

    delivery = models.OneToOneField(
        Delivery, on_delete=models.CASCADE, related_name="tracking_token"
    )
    token = models.CharField(max_length=64, unique=True, default=_new_tracking_token)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.token
