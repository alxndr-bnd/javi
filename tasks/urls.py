from django.urls import path

from .views import escalate, purge_recipient_pii_view, send_rating

app_name = "tasks"

urlpatterns = [
    path("send-rating/<int:delivery_id>/", send_rating, name="send_rating"),
    path("escalate/<int:delivery_id>/", escalate, name="escalate"),
    path("purge-recipient-pii/", purge_recipient_pii_view, name="purge_recipient_pii"),
]
