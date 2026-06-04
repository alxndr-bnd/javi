from django.urls import path

from .views import (
    DeliveryCreateView,
    DeliveryListView,
    DeliveryStartView,
    ShopProfileView,
)

app_name = "deliveries"

urlpatterns = [
    path("", DeliveryListView.as_view(), name="list"),
    path("dostava/nova/", DeliveryCreateView.as_view(), name="create"),
    path("dostava/<int:pk>/start/", DeliveryStartView.as_view(), name="start"),
    path("prodavnica/", ShopProfileView.as_view(), name="profile"),
]
