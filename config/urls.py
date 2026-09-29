"""URL configuration for Javi.

Корень `/` и ассеты лендинга отдаёт WhiteNoise (WHITENOISE_ROOT=landing).
Django обслуживает кабинет и служебные пути ниже.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.decorators.csp import csp_override, csp_report_only_override
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)


def _no_csp(view):
    """Swagger UI / Redoc (сторонние шаблоны с inline-скриптами) — без CSP; данных там нет."""
    return csp_override({})(csp_report_only_override({})(view))


urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),  # set_language
    path("accounts/", include("accounts.urls")),
    path("app/", include("deliveries.urls")),
    path("api/v1/", include("deliveries.api_urls")),  # публичный API по ключу
    # Публичная OpenAPI-документация (без логина) — для интеграторов.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        _no_csp(SpectacularSwaggerView.as_view(url_name="schema")),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        _no_csp(SpectacularRedocView.as_view(url_name="schema")),
        name="redoc",
    ),
    path("t/", include("tracking.urls")),  # публичная страница статуса (без логина)
    path("webhooks/", include("notifications.urls")),  # вебхуки Infobip (по секрету)
    path("tasks/", include("tasks.urls")),  # колбэки Cloud Tasks (по секрету)
]

# Админка — по неочевидному пути из env (SERBITO-362, JAVI-2); без ADMIN_PATH в проде её нет.
if settings.ADMIN_PATH:
    urlpatterns.append(path(settings.ADMIN_PATH, admin.site.urls))
