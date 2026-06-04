import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from deliveries.models import Shop
from deliveries.services import set_shop_origin

pytestmark = pytest.mark.django_db

FAKE_OK = "integrations.testing.FakeMapsProvider"
FAKE_FAIL = "integrations.testing.FailingMapsProvider"


def _make_shop(email, name):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    shop = Shop.objects.create(owner=user, name=name)
    return user, shop


def test_app_requires_login(client):
    """AC#3: аноним на /app/ редиректится на вход."""
    resp = client.get("/app/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_shop_sees_empty_cabinet(client):
    """AC#2: магазин входит и видит пустой кабинет + кнопку «Nova dostava»."""
    _make_shop("milan@pizza.rs", "Pizza Napoli")
    assert client.login(username="milan@pizza.rs", password="pass12345")
    resp = client.get("/app/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Nema dostava" in body
    assert "Nova dostava" in body


def test_tenant_isolation(client):
    """AC#4: каждый магазин видит свой кабинет (скоуп по shop)."""
    _make_shop("a@shop.rs", "Shop A")
    _make_shop("b@shop.rs", "Shop B")
    client.login(username="a@shop.rs", password="pass12345")
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert resp.context["shop"].name == "Shop A"
    assert list(resp.context["deliveries"]) == []


# --- Story 1.2: origin магазина ---


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_set_shop_origin_success_saves_coords():
    """AC#2: успешный геокод сохраняет formatted-адрес и координаты."""
    _, shop = _make_shop("o1@shop.rs", "Shop O1")
    assert set_shop_origin(shop, "Knez Mihailova 6, Beograd") is True
    shop.refresh_from_db()
    assert shop.origin_address == "Knez Mihailova 6, Beograd, Srbija"
    assert shop.origin_lat == pytest.approx(44.8167)
    assert shop.origin_lng == pytest.approx(20.4592)


@override_settings(MAPS_PROVIDER=FAKE_FAIL)
def test_set_shop_origin_miss_keeps_existing_coords():
    """AC#3: при miss координаты не затираются, возвращается False."""
    _, shop = _make_shop("o2@shop.rs", "Shop O2")
    shop.origin_address = "Stari validan, Beograd"
    shop.origin_lat = 45.0
    shop.origin_lng = 21.0
    shop.save()

    assert set_shop_origin(shop, "nepoznata adresa") is False
    shop.refresh_from_db()
    assert shop.origin_address == "Stari validan, Beograd"
    assert shop.origin_lat == 45.0
    assert shop.origin_lng == 21.0


def test_profile_requires_login(client):
    """AC#5: аноним на профиле редиректится на вход."""
    resp = client.get("/app/prodavnica/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_profile_prefills_existing_origin(client):
    """AC#1/#4: текущий origin предзаполнен в форме."""
    _, shop = _make_shop("o3@shop.rs", "Shop O3")
    shop.origin_address = "Trg Republike 1, Beograd"
    shop.save()
    client.login(username="o3@shop.rs", password="pass12345")
    resp = client.get("/app/prodavnica/")
    assert resp.status_code == 200
    assert "Trg Republike 1, Beograd" in resp.content.decode()


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_profile_post_success_redirects_and_saves(client):
    """AC#2: валидный адрес → координаты в БД + PRG-редирект."""
    _, shop = _make_shop("o4@shop.rs", "Shop O4")
    client.login(username="o4@shop.rs", password="pass12345")
    resp = client.post("/app/prodavnica/", {"address": "Knez Mihailova 6"})
    assert resp.status_code == 302
    assert resp["Location"] == "/app/prodavnica/"
    shop.refresh_from_db()
    assert shop.origin_lat == pytest.approx(44.8167)


@override_settings(MAPS_PROVIDER=FAKE_FAIL)
def test_profile_post_miss_shows_hint(client):
    """AC#3: нераспознанный адрес → подсказка, координаты не сохранены."""
    _, shop = _make_shop("o5@shop.rs", "Shop O5")
    client.login(username="o5@shop.rs", password="pass12345")
    resp = client.post("/app/prodavnica/", {"address": "nepoznata"})
    assert resp.status_code == 200
    assert "Nismo prepoznali adresu" in resp.content.decode()
    shop.refresh_from_db()
    assert shop.origin_lat is None


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_profile_isolation_only_own_shop(client):
    """AC#5: магазин меняет только свой Shop."""
    _, shop_a = _make_shop("ia@shop.rs", "Iso A")
    _, shop_b = _make_shop("ib@shop.rs", "Iso B")
    client.login(username="ia@shop.rs", password="pass12345")
    client.post("/app/prodavnica/", {"address": "Knez Mihailova 6"})
    shop_a.refresh_from_db()
    shop_b.refresh_from_db()
    assert shop_a.origin_lat == pytest.approx(44.8167)
    assert shop_b.origin_lat is None
