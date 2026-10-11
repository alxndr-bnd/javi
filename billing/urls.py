from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("pretplata/", views.SubscribeView.as_view(), name="subscribe"),
    path("pretplata/povratak/", views.ReturnView.as_view(), name="return"),
    # Server to server: no login, no CSRF, a Whop signature. Also reachable on the run.app host
    # (common/run_app_guard.py): Cloudflare Bot Fight Mode challenges Whop on javi.serbito.rs.
    path("whop/webhook/", views.whop_webhook, name="whop_webhook"),
]
