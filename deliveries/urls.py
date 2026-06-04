from django.urls import path

from .views import (
    DeliveryCreateView,
    DeliveryListView,
    DeliveryMarkDeliveredView,
    DeliveryResendView,
    DeliveryStartView,
    ShopProfileView,
)

app_name = "deliveries"

urlpatterns = [
    path("", DeliveryListView.as_view(), name="list"),
    path("dostava/nova/", DeliveryCreateView.as_view(), name="create"),
    path("dostava/<int:pk>/start/", DeliveryStartView.as_view(), name="start"),
    path("dostava/<int:pk>/posalji-ponovo/", DeliveryResendView.as_view(), name="resend"),
    path(
        "dostava/<int:pk>/isporuceno/",
        DeliveryMarkDeliveredView.as_view(),
        name="mark_delivered",
    ),
    path("prodavnica/", ShopProfileView.as_view(), name="profile"),
]
