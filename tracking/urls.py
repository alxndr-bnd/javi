from django.urls import path

from .views import status

app_name = "tracking"

urlpatterns = [
    path("<str:token>/", status, name="status"),
]
