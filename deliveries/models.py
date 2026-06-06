import hashlib
import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

API_KEY_PREFIX = "javi_live_"
API_KEY_PREFIX_LEN = 8  # сколько символов токена храним в `prefix` для идентификации в UI/логах


def _new_tracking_token() -> str:
    """Непредсказуемый URL-safe токен для публичной страницы статуса."""
    return secrets.token_urlsafe(24)


def hash_api_key(full_key: str) -> str:
    """sha256-хэш полного ключа (храним только его, не сам ключ)."""
    return hashlib.sha256(full_key.encode()).hexdigest()


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

    # UI-предпочтения кабинета.
    completed_expanded = models.BooleanField("секция «завершённые» развёрнута", default=False)
    kanban_view = models.BooleanField("вид «канбан-доска»", default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Delivery(models.Model):
    """Доставка дня: один получатель, адрес назначения, телефон, статус."""

    class Status(models.TextChoices):
        NEW = "new", _("New")  # новый заказ (принят, ещё не готов)
        CREATED = "created", _("Ready")  # готов к старту
        ON_THE_WAY = "on_the_way", _("In delivery")
        DELIVERED = "delivered", _("Done")

    class Source(models.TextChoices):
        MANUAL = "manual", "manual"
        API = "api", "api"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="deliveries")
    recipient_name = models.CharField("имя получателя", max_length=200)
    recipient_phone = models.CharField("телефон (E.164)", max_length=20)
    # Немобильный/иностранный номер — пометка флагом риска (FR-4).
    phone_risk = models.BooleanField("флаг риска номера", default=False)
    dest_address = models.CharField("адрес назначения", max_length=300)
    dest_city = models.CharField("город назначения", max_length=120, blank=True)
    dest_lat = models.FloatField("широта", null=True, blank=True)
    dest_lng = models.FloatField("долгота", null=True, blank=True)
    description = models.CharField("описание", max_length=300, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    # ETA/старт (Story 2.1): рассчитывается при «Dostava je počela».
    eta_at = models.DateTimeField("ETA (UTC)", null=True, blank=True)
    eta_source = models.CharField("источник ETA", max_length=6, blank=True)  # auto | manual
    started_at = models.DateTimeField("старт доставки", null=True, blank=True)
    # Soft delete: удалённые скрыты из основного списка, видны в «Obrisane».
    deleted_at = models.DateTimeField("удалена", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient_name} — {self.dest_address}"


class Rating(models.Model):
    """Оценка доставки получателем (1–5), 1:1 с доставкой."""

    delivery = models.OneToOneField(Delivery, on_delete=models.CASCADE, related_name="rating")
    value = models.PositiveSmallIntegerField(
        "оценка", validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.value}★ — delivery {self.delivery_id}"


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


class ApiKey(models.Model):
    """Ключ доступа магазина к публичному API. Храним только sha256-хэш полного ключа.

    Полный ключ (`javi_live_<random>`) показывается ОДИН раз при генерации.
    `prefix` (первые ~8 симв. случайной части) — для идентификации в UI/логах.
    """

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="api_keys")
    prefix = models.CharField("префикс", max_length=16, db_index=True)
    key_hash = models.CharField("sha256 хэш ключа", max_length=64, unique=True)
    name = models.CharField("метка", max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField("последнее использование", null=True, blank=True)
    revoked_at = models.DateTimeField("отозван", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{API_KEY_PREFIX}{self.prefix}… ({self.shop_id})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    @property
    def masked(self) -> str:
        """Безопасное представление ключа для UI: `javi_live_xxxxxxxx…`."""
        return f"{API_KEY_PREFIX}{self.prefix}…"

    @classmethod
    def generate(cls, shop: Shop, *, name: str = "") -> tuple["ApiKey", str]:
        """Создаёт ключ. Возвращает (объект, полный_ключ_открытым_текстом).

        Полный ключ нигде не сохраняется — вернуть и показать его можно только сейчас.
        """
        token = secrets.token_urlsafe(32)
        full_key = f"{API_KEY_PREFIX}{token}"
        obj = cls.objects.create(
            shop=shop,
            prefix=token[:API_KEY_PREFIX_LEN],
            key_hash=hash_api_key(full_key),
            name=name,
        )
        return obj, full_key

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class ApiIdempotencyKey(models.Model):
    """Idempotency-Key для POST /deliveries: тот же ключ+магазин → та же доставка."""

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="idempotency_keys")
    key = models.CharField("Idempotency-Key", max_length=200)
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shop", "key"], name="uniq_idempotency_key_per_shop"),
        ]

    def __str__(self):
        return f"{self.key} → delivery {self.delivery_id}"
