from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from deliveries.models import Delivery, Shop, TrackingToken

pytestmark = pytest.mark.django_db


def _delivery_on_the_way():
    user = get_user_model().objects.create_user(email="t@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pizza Napoli")
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Tajna adresa 5, Beograd",
        status=Delivery.Status.ON_THE_WAY,
        eta_at=timezone.now() + timedelta(minutes=20),
    )
    return TrackingToken.objects.create(delivery=delivery)


def test_status_page_shows_eta_no_private_data(client):
    """AC#7: публичная страница показывает магазин+статус+ETA, без телефона/полного адреса."""
    token = _delivery_on_the_way()
    resp = client.get(f"/t/{token.token}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Pizza Napoli" in body
    assert "Stiže okvirno do" in body
    assert "+381641234567" not in body
    assert "Tajna adresa" not in body


def test_status_page_unknown_token_404(client):
    resp = client.get("/t/nonexistent-token/")
    assert resp.status_code == 404


def test_status_page_expired_link_410(client):
    token = _delivery_on_the_way()
    token.expires_at = timezone.now() - timedelta(hours=1)
    token.save()
    resp = client.get(f"/t/{token.token}/")
    assert resp.status_code == 410
    assert "istekao" in resp.content.decode()
