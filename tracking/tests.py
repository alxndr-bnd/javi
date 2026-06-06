from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from deliveries.models import Delivery, Shop, TrackingToken

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _token(status=Delivery.Status.ON_THE_WAY, *, eta_minutes=20, city="Beograd"):
    user = get_user_model().objects.create_user(email="t@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pizza Napoli")
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Tajna adresa 5, Beograd",
        dest_city=city,
        status=status,
        eta_at=timezone.now() + timedelta(minutes=eta_minutes) if eta_minutes else None,
    )
    return TrackingToken.objects.create(delivery=delivery)


def test_on_the_way_shows_eta_city_no_private_data(client):
    """AC#1/#3: статус U dostavi → ETA + город; без телефона/полного адреса."""
    token = _token(Delivery.Status.ON_THE_WAY)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "Pizza Napoli" in body
    assert "Stiže okvirno do" in body
    assert "Beograd" in body
    # степпер всегда рендерится целиком
    assert "Primljeno" in body and "U dostavi" in body and "Isporučeno" in body
    assert "+381641234567" not in body
    assert "Tajna adresa" not in body


def test_created_step_primljeno(client):
    token = _token(Delivery.Status.CREATED, eta_minutes=0)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "Porudžbina je primljena" in body


def test_delivered_step(client):
    token = _token(Delivery.Status.DELIVERED, eta_minutes=0)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "isporučena" in body


def test_unknown_token_404(client):
    assert client.get("/t/nonexistent-token/").status_code == 404


def test_expired_link_410(client):
    token = _token()
    token.expires_at = timezone.now() - timedelta(hours=1)
    token.save()
    resp = client.get(f"/t/{token.token}/")
    assert resp.status_code == 410
    assert "istekao" in resp.content.decode()


def test_rating_capture_and_thanks(client):
    """AC#4: тап звезды → Rating, страница показывает «Hvala!»; AC#5 — без дублей."""
    token = _token(Delivery.Status.ON_THE_WAY)
    url = f"/t/{token.token}/"
    # до оценки — видны звёзды
    assert "Kako je prošla dostava" in client.get(url).content.decode()
    # ставим оценку
    resp = client.post(f"{url}oceni/", {"value": "5"})
    assert resp.status_code == 302
    token.delivery.refresh_from_db()
    assert token.delivery.rating.value == 5
    # после оценки — «Hvala!», звёзд нет
    body = client.get(url).content.decode()
    assert "Hvala" in body
    assert "Kako je prošla dostava" not in body
    # повтор не плодит дубли (обновляет)
    client.post(f"{url}oceni/", {"value": "3"})
    token.delivery.refresh_from_db()
    assert token.delivery.rating.value == 3


def test_rating_invalid_value_ignored(client):
    from deliveries.models import Rating

    token = _token(Delivery.Status.ON_THE_WAY)
    client.post(f"/t/{token.token}/oceni/", {"value": "9"})
    assert Rating.objects.count() == 0


def test_recipient_can_mark_received(client):
    """Получатель подтверждает получение → статус delivered, появляется блок оценки."""
    token = _token(Delivery.Status.ON_THE_WAY)
    url = f"/t/{token.token}/"
    assert "Primio sam porudžbinu" in client.get(url).content.decode()
    resp = client.post(f"{url}primljeno/")
    assert resp.status_code == 302
    token.delivery.refresh_from_db()
    assert token.delivery.status == Delivery.Status.DELIVERED
    body = client.get(url).content.decode()
    assert "isporučena" in body
    assert "Primio sam porudžbinu" not in body
    assert "Kako je prošla dostava" in body  # оценку всё ещё можно поставить


def test_unsubscribe_adds_to_blocklist(client):
    """AC#1: ссылка отписки → OptOut + подтверждение."""
    from notifications.models import OptOut

    token = _token(Delivery.Status.ON_THE_WAY)
    resp = client.get(f"/t/{token.token}/odjava/")
    assert resp.status_code == 200
    assert "Odjavljeni ste" in resp.content.decode()
    assert OptOut.objects.filter(phone=token.delivery.recipient_phone).exists()


@override_settings(TRACKING_RATE_LIMIT=2)
def test_rate_limit_429(client):
    """AC#5: сверх лимита запросов с одного IP → 429."""
    token = _token()
    url = f"/t/{token.token}/"
    assert client.get(url, REMOTE_ADDR="9.9.9.9").status_code == 200
    assert client.get(url, REMOTE_ADDR="9.9.9.9").status_code == 200
    assert client.get(url, REMOTE_ADDR="9.9.9.9").status_code == 429
