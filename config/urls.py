"""URL configuration for Javi.

Корень `/` и ассеты лендинга отдаёт WhiteNoise (WHITENOISE_ROOT=landing).
Django обслуживает кабинет и служебные пути ниже.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("app/", include("deliveries.urls")),
    path("t/", include("tracking.urls")),  # публичная страница статуса (без логина)
    path("webhooks/", include("notifications.urls")),  # вебхуки Infobip (по секрету)
]
