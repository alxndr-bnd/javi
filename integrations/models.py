from django.db import models
from django.db.models import F
from django.utils import timezone


class GeocodeCache(models.Model):
    """Кэш геокодинга по нормализованному адресу (AR-6: срезает стоимость Maps).

    Персистентный (Cloud SQL) — переживает scale-to-zero Cloud Run.
    """

    normalized_address = models.CharField("нормализованный адрес", max_length=512, unique=True)
    lat = models.FloatField("широта")
    lng = models.FloatField("долгота")
    formatted_address = models.CharField("formatted адрес", max_length=512)
    city = models.CharField("город", max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.normalized_address


# Метрики глобального учёта расхода провайдеров (квоты free-tier).
METRIC_VIBER = "viber"
METRIC_SMS = "sms"
METRIC_MAPS_GEOCODE = "maps_geocode"
METRIC_MAPS_ROUTE = "maps_route"


def usage_period(now=None) -> str:
    """Бакет периода (UTC-месяц) `YYYY-MM` для помесячного сброса квоты."""
    return (now or timezone.now()).strftime("%Y-%m")


class ProviderUsage(models.Model):
    """Глобальный (account-wide) счётчик реальных вызовов провайдера за период.

    Одна строка на `(metric, period)`. Считаем НА СВОЕЙ стороне (без billing-API и без
    раздачи кредов магазинам). period — UTC-месяц `YYYY-MM`; для lifetime-метрик периоды
    суммируются. Магазины видят только агрегат, не сами вызовы.
    """

    metric = models.CharField("метрика", max_length=32)
    period = models.CharField("период (YYYY-MM)", max_length=7)
    count = models.PositiveIntegerField("счётчик", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["metric", "period"], name="uniq_usage_metric_period")
        ]

    def __str__(self):
        return f"{self.metric}@{self.period}={self.count}"

    @classmethod
    def record(cls, metric: str, n: int = 1, *, now=None) -> None:
        """Атомарно увеличить счётчик метрики за текущий период на `n` (F-выражение)."""
        period = usage_period(now)
        cls.objects.get_or_create(metric=metric, period=period)
        cls.objects.filter(metric=metric, period=period).update(count=F("count") + n)
