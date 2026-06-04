from django.urls import path

from .webhooks import infobip_reports

app_name = "notifications"

urlpatterns = [
    path("infobip/reports/", infobip_reports, name="infobip_reports"),
]
