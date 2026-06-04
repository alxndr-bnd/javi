from django.urls import path

from .views import DeliveryListView, ShopProfileView

app_name = "deliveries"

urlpatterns = [
    path("", DeliveryListView.as_view(), name="list"),
    path("prodavnica/", ShopProfileView.as_view(), name="profile"),
]
