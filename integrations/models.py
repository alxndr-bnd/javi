from django.db import models


class GeocodeCache(models.Model):
    """Кэш геокодинга по нормализованному адресу (AR-6: срезает стоимость Maps).

    Персистентный (Cloud SQL) — переживает scale-to-zero Cloud Run.
    """

    normalized_address = models.CharField("нормализованный адрес", max_length=512, unique=True)
    lat = models.FloatField("широта")
    lng = models.FloatField("долгота")
    formatted_address = models.CharField("formatted адрес", max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.normalized_address
