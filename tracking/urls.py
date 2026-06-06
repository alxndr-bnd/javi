from django.urls import path

from .views import mark_received, rate, status, unsubscribe

app_name = "tracking"

urlpatterns = [
    path("<str:token>/", status, name="status"),
    path("<str:token>/oceni/", rate, name="rate"),
    path("<str:token>/primljeno/", mark_received, name="mark_received"),
    path("<str:token>/odjava/", unsubscribe, name="unsubscribe"),
]
