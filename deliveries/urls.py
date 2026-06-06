from django.urls import path

from .views import (
    ApiDocsView,
    ApiKeyCreateView,
    ApiKeyRevokeView,
    DeletedDeliveriesView,
    DeliveryCreateView,
    DeliveryDeleteView,
    DeliveryFeedView,
    DeliveryListView,
    DeliveryMarkDeliveredView,
    DeliveryMarkReadyView,
    DeliveryResendView,
    DeliveryRestoreView,
    DeliveryStartView,
    RecipientLookupView,
    SetViewView,
    ShopProfileView,
    ToggleCompletedView,
)

app_name = "deliveries"

urlpatterns = [
    path("", DeliveryListView.as_view(), name="list"),
    path("dostava/nova/", DeliveryCreateView.as_view(), name="create"),
    path("klijent/", RecipientLookupView.as_view(), name="recipient_lookup"),
    path("feed/", DeliveryFeedView.as_view(), name="feed"),
    path("obrisane/", DeletedDeliveriesView.as_view(), name="deleted"),
    path("api/", ApiDocsView.as_view(), name="api_docs"),
    path("zavrseno/toggle/", ToggleCompletedView.as_view(), name="toggle_completed"),
    path("prikaz/", SetViewView.as_view(), name="set_view"),
    path("dostava/<int:pk>/spremno/", DeliveryMarkReadyView.as_view(), name="mark_ready"),
    path("dostava/<int:pk>/start/", DeliveryStartView.as_view(), name="start"),
    path("dostava/<int:pk>/obrisi/", DeliveryDeleteView.as_view(), name="delete"),
    path("dostava/<int:pk>/vrati/", DeliveryRestoreView.as_view(), name="restore"),
    path("dostava/<int:pk>/posalji-ponovo/", DeliveryResendView.as_view(), name="resend"),
    path(
        "dostava/<int:pk>/isporuceno/",
        DeliveryMarkDeliveredView.as_view(),
        name="mark_delivered",
    ),
    path("prodavnica/", ShopProfileView.as_view(), name="profile"),
    path("api-kljucevi/novi/", ApiKeyCreateView.as_view(), name="api_key_create"),
    path("api-kljucevi/<int:pk>/opozovi/", ApiKeyRevokeView.as_view(), name="api_key_revoke"),
]
