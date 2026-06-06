from django.urls import path

from . import api

app_name = "api"

urlpatterns = [
    path("deliveries", api.deliveries_collection, name="deliveries"),
    path("deliveries/<int:pk>", api.delivery_detail, name="delivery_detail"),
    path("deliveries/<int:pk>/start", api.delivery_start, name="delivery_start"),
]
