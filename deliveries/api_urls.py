from django.urls import path

from . import api

app_name = "api"

urlpatterns = [
    path("shop", api.ShopView.as_view(), name="shop"),
    path("deliveries", api.DeliveriesCollectionView.as_view(), name="deliveries"),
    path("deliveries/<int:pk>", api.DeliveryDetailView.as_view(), name="delivery_detail"),
    path("deliveries/<int:pk>/start", api.DeliveryStartView.as_view(), name="delivery_start"),
    # Алиас «dispatch» (паритет с UI «Dostava je počela»).
    path(
        "deliveries/<int:pk>/dispatch",
        api.DeliveryDispatchView.as_view(),
        name="delivery_dispatch",
    ),
    path("deliveries/<int:pk>/ready", api.DeliveryReadyView.as_view(), name="delivery_ready"),
    path(
        "deliveries/<int:pk>/delivered",
        api.DeliveryDeliveredView.as_view(),
        name="delivery_delivered",
    ),
    path(
        "deliveries/<int:pk>/restore",
        api.DeliveryRestoreView.as_view(),
        name="delivery_restore",
    ),
    path(
        "deliveries/<int:pk>/notifications/resend",
        api.DeliveryResendView.as_view(),
        name="delivery_resend",
    ),
]
