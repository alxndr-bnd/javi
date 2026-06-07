from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from common.phone import normalize_phone
from deliveries.models import Delivery, Shop
from deliveries.services import (
    create_delivery,
    resend_on_the_way,
    set_shop_origin,
    start_delivery,
)
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
    assert "No deliveries" in body
    assert "New delivery" in body


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
    resp = client.post("/app/prodavnica/", {"name": "Shop", "address": "Knez Mihailova 6"})
    assert resp.status_code == 302
    assert resp["Location"] == "/app/prodavnica/"
    shop.refresh_from_db()
    assert shop.origin_lat == pytest.approx(44.8167)


@override_settings(MAPS_PROVIDER=FAKE_FAIL)
def test_profile_post_miss_shows_hint(client):
    """AC#3: нераспознанный адрес → подсказка, координаты не сохранены."""
    _, shop = _make_shop("o5@shop.rs", "Shop O5")
    client.login(username="o5@shop.rs", password="pass12345")
    resp = client.post("/app/prodavnica/", {"name": "Shop", "address": "nepoznata"})
    assert resp.status_code == 200
    assert "could not recognize the address" in resp.content.decode()
    shop.refresh_from_db()
    assert shop.origin_lat is None


def test_profile_user_without_shop_no_500(client):
    """Залогиненный без магазина (напр. суперюзер) не падает с 500."""
    get_user_model().objects.create_user(email="noshop@x.rs", password="pass12345")
    client.login(username="noshop@x.rs", password="pass12345")
    resp = client.get("/app/prodavnica/")
    assert resp.status_code == 200
    assert "Account is not linked to a store" in resp.content.decode()


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_profile_isolation_only_own_shop(client):
    """AC#5: магазин меняет только свой Shop."""
    _, shop_a = _make_shop("ia@shop.rs", "Iso A")
    _, shop_b = _make_shop("ib@shop.rs", "Iso B")
    client.login(username="ia@shop.rs", password="pass12345")
    client.post("/app/prodavnica/", {"name": "Shop", "address": "Knez Mihailova 6"})
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
    assert delivery.dest_city == "Beograd"
    assert delivery.status == Delivery.Status.NEW


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
def test_create_view_success_appears_in_novo(client):
    """Валидная форма → доставка в БД и в группе «Novo» (новый заказ)."""
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
    d = list_resp.context["novo"][0]
    assert d.recipient_name == "Ana"
    body = list_resp.content.decode()
    assert "New" in body
    assert f"#{d.id}" in body  # id заказа на карточке


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
    assert "Invalid number" in resp.content.decode()
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
    assert "Arriving approximately by" in text and "/t/" in text


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
    assert delivery.status == Delivery.Status.NEW
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
def test_start_view_preview_shows_computed_eta(client):
    """Шаг 1: «Dostava je počela» показывает рассчитанное время, ещё НЕ шлёт."""
    FakeMessagingProvider.sent = []
    _, delivery = _geocoded_delivery("pv@shop.rs", "Preview Shop")
    client.login(username="pv@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{delivery.pk}/start/")
    assert resp.status_code == 200
    assert "Estimated arrival time" in resp.content.decode()
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.NEW  # ещё не стартовала
    assert len(FakeMessagingProvider.sent) == 0


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_view_confirm_moves_to_u_dostavi(client):
    """Шаг 2: подтверждение с временем → старт, карточка в U dostavi, сообщение ушло."""
    FakeMessagingProvider.sent = []
    shop, delivery = _geocoded_delivery("ok@shop.rs", "OK Shop")
    client.login(username="ok@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{delivery.pk}/start/", {"eta_time": "16:00"}, follow=True)
    assert resp.status_code == 200
    assert resp.context["u_dostavi"][0].pk == delivery.pk
    assert resp.context["spremno"] == []
    assert len(FakeMessagingProvider.sent) == 1


@override_settings(ROUTES_PROVIDER=ROUTES_OK)
def test_compute_eta_includes_buffer(settings):
    """ETA = now + время в пути (фейк 900с) + запас (минуты)."""
    from datetime import timedelta

    from deliveries.services import compute_eta

    settings.ETA_BUFFER_MINUTES = 10
    _, delivery = _geocoded_delivery("eb@shop.rs", "Buffer Shop")
    before = timezone.now()
    eta = compute_eta(delivery)
    # 900с в пути + 10 мин запаса = 1500с; с запасом на время выполнения теста.
    assert eta is not None
    assert eta >= before + timedelta(seconds=1500)
    assert eta <= before + timedelta(seconds=1500 + 30)


# --- Story 2.4: статус уведомления + переотправка + ручная отметка ---


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_resend_updates_phone_and_reuses_notification():
    """AC#4: resend правит номер и переиспользует один Notification."""
    _, delivery = _geocoded_delivery()
    start_delivery(delivery)
    FakeMessagingProvider.sent = []
    new = normalize_phone("060 1234567")
    result = resend_on_the_way(delivery, new_phone=new)

    assert result.ok
    delivery.refresh_from_db()
    assert delivery.recipient_phone == "+381601234567"
    assert delivery.notifications.filter(kind=Notification.Kind.ON_THE_WAY).count() == 1
    assert len(FakeMessagingProvider.sent) == 1
    n = delivery.notifications.get(kind=Notification.Kind.ON_THE_WAY)
    assert n.status == Notification.Status.SENT


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_resend_view_success(client):
    shop, delivery = _geocoded_delivery("rs@shop.rs", "Resend Shop")
    start_delivery(delivery)
    client.login(username="rs@shop.rs", password="pass12345")
    resp = client.post(
        f"/app/dostava/{delivery.pk}/posalji-ponovo/", {"recipient_phone": "064 1112233"}
    )
    assert resp.status_code == 302
    delivery.refresh_from_db()
    assert delivery.recipient_phone == "+381641112233"


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_resend_view_other_shop_404(client):
    _make_shop_with_origin("att@shop.rs", "Att")
    _, victim = _geocoded_delivery("vic@shop.rs", "Vic")
    start_delivery(victim)
    client.login(username="att@shop.rs", password="pass12345")
    resp = client.post(
        f"/app/dostava/{victim.pk}/posalji-ponovo/", {"recipient_phone": "064 1112233"}
    )
    assert resp.status_code == 404


@override_settings(ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_mark_delivered(client):
    shop, delivery = _geocoded_delivery("md@shop.rs", "Mark Shop")
    start_delivery(delivery)
    client.login(username="md@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{delivery.pk}/isporuceno/")
    assert resp.status_code == 302
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.DELIVERED


def test_mark_delivered_other_shop_404(client):
    _make_shop_with_origin("a2@shop.rs", "A2")
    _, victim = _geocoded_delivery("v2@shop.rs", "V2")
    client.login(username="a2@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{victim.pk}/isporuceno/")
    assert resp.status_code == 404


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_delete_is_soft_and_hidden_from_list(client):
    """Soft delete: строка остаётся, но скрыта из основного списка, видна в «Obrisane»."""
    shop = _make_shop_with_origin("del@shop.rs", "Del Shop")
    delivery, _ = create_delivery(
        shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"), dest_address="adr"
    )
    client.login(username="del@shop.rs", password="pass12345")
    client.post(f"/app/dostava/{delivery.pk}/obrisi/")
    delivery.refresh_from_db()
    assert delivery.deleted_at is not None  # не удалена физически

    # в основном списке её нет
    assert list(client.get("/app/").context["deliveries"]) == []
    # в разделе «Obrisane» — есть
    assert client.get("/app/obrisane/").context["deleted"][0].pk == delivery.pk


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_restore_delivery(client):
    shop = _make_shop_with_origin("res@shop.rs", "Res Shop")
    delivery, _ = create_delivery(
        shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"), dest_address="adr"
    )
    client.login(username="res@shop.rs", password="pass12345")
    client.post(f"/app/dostava/{delivery.pk}/obrisi/")
    client.post(f"/app/dostava/{delivery.pk}/vrati/")
    delivery.refresh_from_db()
    assert delivery.deleted_at is None
    assert delivery.pk in [d.pk for d in client.get("/app/").context["deliveries"]]


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_feed_signature_changes_on_new_order(client):
    """Авто-обновление: сигнатура меняется при появлении нового заказа."""
    shop = _make_shop_with_origin("fd@shop.rs", "Feed Shop")
    client.login(username="fd@shop.rs", password="pass12345")
    sig1 = client.get("/app/feed/").json()["sig"]
    create_delivery(
        shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"), dest_address="adr"
    )
    sig2 = client.get("/app/feed/").json()["sig"]
    assert sig1 != sig2


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_mark_ready_moves_new_to_spremno(client):
    shop = _make_shop_with_origin("mr@shop.rs", "MR Shop")
    delivery, _ = create_delivery(
        shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"), dest_address="adr"
    )
    assert delivery.status == Delivery.Status.NEW
    client.login(username="mr@shop.rs", password="pass12345")
    client.post(f"/app/dostava/{delivery.pk}/spremno/")
    delivery.refresh_from_db()
    assert delivery.status == Delivery.Status.CREATED


def test_set_view_switches_to_board(client):
    shop = _make_shop_with_origin("sv@shop.rs", "SV Shop")
    client.login(username="sv@shop.rs", password="pass12345")
    client.post("/app/prikaz/", {"mode": "board"})
    shop.refresh_from_db()
    assert shop.kanban_view is True
    # на доске видны 4 колонки
    body = client.get("/app/").content.decode()
    assert "kanban" in body
    client.post("/app/prikaz/", {"mode": "list"})
    shop.refresh_from_db()
    assert shop.kanban_view is False


def test_toggle_completed_saves_state(client):
    shop = _make_shop_with_origin("tg@shop.rs", "Toggle Shop")
    client.login(username="tg@shop.rs", password="pass12345")
    client.post("/app/zavrseno/toggle/", {"expanded": "1"})
    shop.refresh_from_db()
    assert shop.completed_expanded is True
    client.post("/app/zavrseno/toggle/", {"expanded": "0"})
    shop.refresh_from_db()
    assert shop.completed_expanded is False


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_delete_other_shop_404(client):
    _make_shop_with_origin("da2@shop.rs", "DA2")
    _, victim = _geocoded_delivery("dv2@shop.rs", "DV2")
    client.login(username="da2@shop.rs", password="pass12345")
    resp = client.post(f"/app/dostava/{victim.pk}/obrisi/")
    assert resp.status_code == 404
    assert Delivery.objects.filter(pk=victim.pk).exists()


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_recipient_lookup_returns_known_client(client):
    """Автоподстановка: по номеру возвращаются имя+адрес последней доставки магазина."""
    shop = _make_shop_with_origin("lk@shop.rs", "Lookup Shop")
    create_delivery(
        shop, recipient_name="Ana Anić", phone=normalize_phone("064 123 4567"),
        dest_address="Knez Mihailova 6",
    )
    client.login(username="lk@shop.rs", password="pass12345")
    resp = client.get("/app/klijent/?phone=064 123 4567")
    data = resp.json()
    assert data["found"] is True
    assert data["name"] == "Ana Anić"
    assert "Knez Mihailova" in data["address"]


def test_recipient_lookup_unknown_returns_not_found(client):
    _make_shop_with_origin("lk2@shop.rs", "Lookup2")
    client.login(username="lk2@shop.rs", password="pass12345")
    assert client.get("/app/klijent/?phone=064 999 8877").json()["found"] is False


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_recipient_lookup_isolated_by_shop(client):
    """Магазин не видит клиентов другого магазина."""
    other = _make_shop_with_origin("other@shop.rs", "Other")
    create_delivery(
        other, recipient_name="Tuđ Klijent", phone=normalize_phone("064 123 4567"),
        dest_address="Negde",
    )
    _make_shop_with_origin("me@shop.rs", "Me")
    client.login(username="me@shop.rs", password="pass12345")
    assert client.get("/app/klijent/?phone=064 123 4567").json()["found"] is False


def test_recipient_lookup_requires_login(client):
    resp = client.get("/app/klijent/?phone=064 123 4567")
    assert resp.status_code == 302


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_cabinet_shows_opted_out(client):
    """Story 3.2 AC#4: магазин видит «otkazao obaveštenja» для отписанного."""
    from notifications.services import opt_out

    shop = _make_shop_with_origin("oo@shop.rs", "OptOut Shop")
    delivery, _ = create_delivery(
        shop, recipient_name="Ana", phone=normalize_phone("064 123 4567"), dest_address="adr"
    )
    opt_out(delivery.recipient_phone)
    client.login(username="oo@shop.rs", password="pass12345")
    body = client.get("/app/").content.decode()
    assert "opted out of notifications" in body
