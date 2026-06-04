from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from common.phone import normalize_phone
from deliveries.models import Delivery, Shop
from deliveries.services import create_delivery, set_shop_origin, start_delivery
from integrations.testing import FakeMessagingProvider
from notifications.models import Notification

pytestmark = pytest.mark.django_db

FAKE_OK = "integrations.testing.FakeMapsProvider"
FAKE_FAIL = "integrations.testing.FailingMapsProvider"
ROUTES_OK = "integrations.testing.FakeRoutesProvider"
ROUTES_FAIL = "integrations.testing.FailingRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"
MSG_FAIL = "integrations.testing.FailingMessagingProvider"


def _geocoded_delivery(email="s@shop.rs", name="Shop S"):
    """Магазин с origin + доставка с геокодированными координатами (через фейк-карты)."""
    shop = _make_shop_with_origin(email, name)
    with override_settings(MAPS_PROVIDER=FAKE_OK):
        delivery, _ = create_delivery(
            shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"),
            dest_address="Neka adresa",
        )
    return shop, delivery


def _make_shop_with_origin(email, name):
    _, shop = _make_shop(email, name)
    shop.origin_address = "Origin, Beograd"
    shop.origin_lat = 44.8
    shop.origin_lng = 20.45
    shop.save()
    return shop


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


def test_profile_user_without_shop_no_500(client):
    """Залогиненный без магазина (напр. суперюзер) не падает с 500."""
    get_user_model().objects.create_user(email="noshop@x.rs", password="pass12345")
    client.login(username="noshop@x.rs", password="pass12345")
    resp = client.get("/app/prodavnica/")
    assert resp.status_code == 200
    assert "Nalog nije povezan sa prodavnicom" in resp.content.decode()


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


# --- Story 1.3: создание доставки ---


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_delivery_geocode_success():
    """AC#6: успешный геокод сохраняет координаты + formatted-адрес."""
    shop = _make_shop_with_origin("d1@shop.rs", "Shop D1")
    phone = normalize_phone("064 123 4567")
    delivery, geocoded = create_delivery(
        shop, recipient_name="Ana", phone=phone, dest_address="Neka adresa"
    )
    assert geocoded is True
    assert delivery.recipient_phone == "+381641234567"
    assert delivery.phone_risk is False
    assert delivery.dest_lat == pytest.approx(44.8167)
    assert delivery.dest_address == "Knez Mihailova 6, Beograd, Srbija"
    assert delivery.status == Delivery.Status.CREATED


@override_settings(MAPS_PROVIDER=FAKE_FAIL)
def test_create_delivery_geocode_miss_still_creates():
    """AC#6: при сбое геокода доставка создаётся без координат, поток не падает."""
    shop = _make_shop_with_origin("d2@shop.rs", "Shop D2")
    phone = normalize_phone("064 123 4567")
    delivery, geocoded = create_delivery(
        shop, recipient_name="Ana", phone=phone, dest_address="Nepoznata adresa"
    )
    assert geocoded is False
    assert delivery.dest_lat is None
    assert delivery.dest_address == "Nepoznata adresa"


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_delivery_foreign_phone_flags_risk():
    """AC#5: иностранный/немобильный номер помечается флагом риска."""
    shop = _make_shop_with_origin("d3@shop.rs", "Shop D3")
    phone = normalize_phone("+49 1512 3456789")
    delivery, _ = create_delivery(
        shop, recipient_name="Hans", phone=phone, dest_address="Neka adresa"
    )
    assert delivery.phone_risk is True


def test_create_view_requires_login(client):
    """AC#8: аноним на форме создания → вход."""
    resp = client.get("/app/dostava/nova/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_create_view_without_origin_redirects_to_profile(client):
    """AC#2: магазин без origin → редирект в профиль."""
    _make_shop("noorigin@shop.rs", "No Origin")
    client.login(username="noorigin@shop.rs", password="pass12345")
    resp = client.get("/app/dostava/nova/")
    assert resp.status_code == 302
    assert resp["Location"] == "/app/prodavnica/"


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_view_success_appears_in_spremno(client):
    """AC#7: валидная форма → доставка в БД и в группе Spremno списка."""
    shop = _make_shop_with_origin("d4@shop.rs", "Shop D4")
    client.login(username="d4@shop.rs", password="pass12345")
    resp = client.post(
        "/app/dostava/nova/",
        {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "dest_address": "Neka adresa"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == "/app/"
    assert shop.deliveries.count() == 1

    list_resp = client.get("/app/")
    assert list_resp.context["spremno"][0].recipient_name == "Ana"
    assert "Spremno" in list_resp.content.decode()


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_view_invalid_phone_blocks(client):
    """AC#4: невалидный телефон → ошибка формы, доставка не создаётся."""
    shop = _make_shop_with_origin("d5@shop.rs", "Shop D5")
    client.login(username="d5@shop.rs", password="pass12345")
    resp = client.post(
        "/app/dostava/nova/",
        {"recipient_name": "Ana", "recipient_phone": "abc", "dest_address": "Neka adresa"},
    )
    assert resp.status_code == 200
    assert "Neispravan broj" in resp.content.decode()
    assert shop.deliveries.count() == 0


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_delivery_isolation_between_shops(client):
    """AC#8: магазин видит только свои доставки."""
    shop_a = _make_shop_with_origin("da@shop.rs", "Iso DA")
    shop_b = _make_shop_with_origin("db@shop.rs", "Iso DB")
    create_delivery(
        shop_b, recipient_name="B-only", phone=normalize_phone("064 123 4567"),
        dest_address="adr",
    )
    client.login(username="da@shop.rs", password="pass12345")
    resp = client.get("/app/")
    assert list(resp.context["deliveries"]) == []
    assert shop_a.deliveries.count() == 0


# --- Story 2.1: старт доставки + ETA + уведомление ---


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_delivery_computes_eta_and_sends():
    """AC#1-3,6: ETA из маршрута, статус on_the_way, Notification sent, токен, текст со ссылкой."""
    FakeMessagingProvider.sent = []
    _, delivery = _geocoded_delivery()
    result = start_delivery(delivery)

    assert result.ok and result.sent
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.ON_THE_WAY
    assert delivery.eta_at is not None
    assert delivery.eta_source == "auto"
    assert hasattr(delivery, "tracking_token")
    n = delivery.notifications.get(kind=Notification.Kind.ON_THE_WAY)
    assert n.status == Notification.Status.SENT
    assert len(FakeMessagingProvider.sent) == 1
    to, text = FakeMessagingProvider.sent[0]
    assert to == "+381641234567"
    assert "Stiže okvirno do" in text and "/t/" in text


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_delivery_idempotent():
    """AC#4: повторный старт — no-op, без второй отправки."""
    FakeMessagingProvider.sent = []
    _, delivery = _geocoded_delivery()
    start_delivery(delivery)
    second = start_delivery(delivery)

    assert second.already is True
    assert delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).count() == 1
    assert len(FakeMessagingProvider.sent) == 1


@override_settings(ROUTES_PROVIDER=ROUTES_FAIL, MESSAGING_PROVIDER=MSG_OK)
def test_start_delivery_route_unavailable_needs_manual_eta():
    """AC#5: маршрут недоступен → сигнал ручного ETA, ничего не меняем."""
    FakeMessagingProvider.sent = []
    _, delivery = _geocoded_delivery()
    result = start_delivery(delivery)

    assert result.needs_manual_eta is True
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.CREATED
    assert delivery.notifications.count() == 0
    assert len(FakeMessagingProvider.sent) == 0


@override_settings(ROUTES_PROVIDER=ROUTES_FAIL, MESSAGING_PROVIDER=MSG_OK)
def test_start_delivery_manual_eta_sends():
    """AC#5: с ручным ETA отправка проходит, eta_source=manual."""
    FakeMessagingProvider.sent = []
    _, delivery = _geocoded_delivery()
    manual = timezone.now() + timedelta(hours=1)
    result = start_delivery(delivery, manual_eta=manual)

    assert result.ok and result.sent
    delivery.refresh_from_db()
    assert delivery.eta_source == "manual"
    assert len(FakeMessagingProvider.sent) == 1


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_FAIL)
def test_start_delivery_send_failure_marks_failed():
    """AC: сбой отправки → статус on_the_way, Notification=failed, sent=False."""
    _, delivery = _geocoded_delivery()
    result = start_delivery(delivery)

    assert result.ok and result.sent is False
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.ON_THE_WAY
    n = delivery.notifications.get(kind=Notification.Kind.ON_THE_WAY)
    assert n.status == Notification.Status.FAILED


def test_start_view_requires_login(client):
    _, delivery = _geocoded_delivery()
    resp = client.post(f"/app/dostava/{delivery.pk}/start/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_view_cannot_start_other_shop_delivery(client):
    """AC#8: чужую доставку стартовать нельзя."""
    _make_shop_with_origin("attacker@shop.rs", "Attacker")
    _, victim_delivery = _geocoded_delivery("victim@shop.rs", "Victim")
    client.login(username="attacker@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{victim_delivery.pk}/start/")
    assert resp.status_code == 404


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_view_success_moves_to_u_dostavi(client):
    """AC#6: успешный старт → карточка в группе U dostavi."""
    FakeMessagingProvider.sent = []
    shop, delivery = _geocoded_delivery("ok@shop.rs", "OK Shop")
    client.login(username="ok@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{delivery.pk}/start/", follow=True)
    assert resp.status_code == 200
    assert resp.context["u_dostavi"][0].pk == delivery.pk
    assert resp.context["spremno"] == []
