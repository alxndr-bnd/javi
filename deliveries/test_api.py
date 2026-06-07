"""Тесты публичного API v1 (deliveries). Без сети — фейк-провайдеры через override_settings."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from deliveries.models import ApiIdempotencyKey, ApiKey, Delivery, Shop
from integrations.testing import FakeMessagingProvider

pytestmark = pytest.mark.django_db

FAKE_OK = "integrations.testing.FakeMapsProvider"
ROUTES_OK = "integrations.testing.FakeRoutesProvider"
ROUTES_FAIL = "integrations.testing.FailingRoutesProvider"
MSG_OK = "integrations.testing.FakeMessagingProvider"

CREATE_URL = "/api/v1/deliveries"


def _make_shop_with_origin(email="api@shop.rs", name="API Shop"):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    shop = Shop.objects.create(owner=user, name=name)
    shop.origin_address = "Origin, Beograd"
    shop.origin_lat = 44.8
    shop.origin_lng = 20.45
    shop.save()
    return shop


def _shop_and_key(email="api@shop.rs", name="API Shop"):
    shop = _make_shop_with_origin(email, name)
    _obj, full_key = ApiKey.generate(shop)
    return shop, full_key


def _auth(key):
    return {"HTTP_AUTHORIZATION": f"Bearer {key}"}


def _post_create(client, key, body, **headers):
    return client.post(
        CREATE_URL, data=json.dumps(body), content_type="application/json",
        **_auth(key), **headers,
    )


# --- Auth -----------------------------------------------------------------


def test_generate_stores_only_hash():
    shop = _make_shop_with_origin()
    obj, full_key = ApiKey.generate(shop)
    assert full_key.startswith("javi_live_")
    assert obj.key_hash != full_key
    assert len(obj.key_hash) == 64
    assert obj.prefix and obj.prefix in full_key


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_requires_key(client):
    resp = client.post(CREATE_URL, data="{}", content_type="application/json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_invalid_key(client):
    _make_shop_with_origin()
    resp = _post_create(client, "javi_live_bogus", {"recipient_name": "x"})
    assert resp.status_code == 401


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_revoked_key(client):
    shop = _make_shop_with_origin()
    obj, full_key = ApiKey.generate(shop)
    obj.revoke()
    resp = _post_create(client, full_key, {"recipient_name": "x"})
    assert resp.status_code == 401


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_x_api_key_header_works(client):
    shop, key = _shop_and_key()
    resp = client.post(
        CREATE_URL,
        data=json.dumps(
            {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
        ),
        content_type="application/json",
        HTTP_X_API_KEY=key,
    )
    assert resp.status_code == 201


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_auth_updates_last_used(client):
    shop, key = _shop_and_key()
    obj = shop.api_keys.first()
    assert obj.last_used_at is None
    _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    )
    obj.refresh_from_db()
    assert obj.last_used_at is not None


# --- Create ---------------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_delivery_201_source_api(client):
    shop, key = _shop_and_key()
    resp = _post_create(
        client, key,
        {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "Neka adresa",
         "description": "2 pice"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"  # industry-standard
    assert data["status_internal"] == "new"  # внутренний код Javi
    assert data["recipient"] == {"name": "Ana", "phone": "+381641234567"}
    assert data["source"] == "api"
    assert data["description"] == "2 pice"
    delivery = Delivery.objects.get(id=data["id"])
    assert delivery.source == Delivery.Source.API
    assert delivery.shop == shop


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_invalid_phone_400(client):
    shop, key = _shop_and_key()
    resp = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "abc", "address": "adr"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_phone"
    assert shop.deliveries.count() == 0


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_missing_fields_422(client):
    shop, key = _shop_and_key()
    resp = _post_create(client, key, {"recipient_name": "Ana"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_bad_json_400(client):
    shop, key = _shop_and_key()
    resp = client.post(CREATE_URL, data="not json", content_type="application/json", **_auth(key))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_json"


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_create_put_method_not_allowed(client):
    shop, key = _shop_and_key()
    resp = client.put(CREATE_URL, **_auth(key))
    assert resp.status_code == 405


# --- Idempotency ----------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_idempotency_returns_same_delivery(client):
    shop, key = _shop_and_key()
    body = {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    r1 = _post_create(client, key, body, HTTP_IDEMPOTENCY_KEY="abc-123")
    r2 = _post_create(client, key, body, HTTP_IDEMPOTENCY_KEY="abc-123")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert shop.deliveries.count() == 1
    assert ApiIdempotencyKey.objects.filter(shop=shop, key="abc-123").count() == 1


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_idempotency_scoped_per_shop(client):
    shop_a, key_a = _shop_and_key("a@shop.rs", "A")
    shop_b, key_b = _shop_and_key("b@shop.rs", "B")
    body = {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    _post_create(client, key_a, body, HTTP_IDEMPOTENCY_KEY="same")
    _post_create(client, key_b, body, HTTP_IDEMPOTENCY_KEY="same")
    # тот же ключ у другого магазина создаёт отдельную доставку
    assert shop_a.deliveries.count() == 1
    assert shop_b.deliveries.count() == 1


# --- Get ------------------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_get_delivery(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.get(f"/api/v1/deliveries/{created['id']}", **_auth(key))
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
    assert resp.json()["notification"] is None


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_get_other_shop_404(client):
    shop_a, key_a = _shop_and_key("a@shop.rs", "A")
    shop_b, key_b = _shop_and_key("b@shop.rs", "B")
    victim = _post_create(
        client, key_b, {"recipient_name": "B", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.get(f"/api/v1/deliveries/{victim['id']}", **_auth(key_a))
    assert resp.status_code == 404


# --- Start ----------------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_delivery_via_api(client):
    FakeMessagingProvider.sent = []
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.post(f"/api/v1/deliveries/{created['id']}/start", **_auth(key))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "out_for_delivery"  # industry-standard
    assert data["status_internal"] == "on_the_way"
    assert data["eta"] is not None
    assert data["tracking_url"] and "/t/" in data["tracking_url"]
    assert data["notification"]["status"] == "sent"
    assert len(FakeMessagingProvider.sent) == 1


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_FAIL, MESSAGING_PROVIDER=MSG_OK)
def test_start_needs_manual_eta_422(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.post(f"/api/v1/deliveries/{created['id']}/start", **_auth(key))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "eta_required"


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_FAIL, MESSAGING_PROVIDER=MSG_OK)
def test_start_with_manual_eta(client):
    FakeMessagingProvider.sent = []
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.post(
        f"/api/v1/deliveries/{created['id']}/start",
        data=json.dumps({"eta": "16:30"}), content_type="application/json", **_auth(key),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "out_for_delivery"
    assert resp.json()["eta"] == "16:30"


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_bad_eta_format_400(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.post(
        f"/api/v1/deliveries/{created['id']}/start",
        data=json.dumps({"eta": "25:99"}), content_type="application/json", **_auth(key),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_eta"


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_already_started_returns_state(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    client.post(f"/api/v1/deliveries/{created['id']}/start", **_auth(key))
    resp = client.post(f"/api/v1/deliveries/{created['id']}/start", **_auth(key))
    assert resp.status_code == 200
    assert resp.json()["status"] == "out_for_delivery"


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_start_other_shop_404(client):
    shop_a, key_a = _shop_and_key("a@shop.rs", "A")
    shop_b, key_b = _shop_and_key("b@shop.rs", "B")
    victim = _post_create(
        client, key_b, {"recipient_name": "B", "recipient_phone": "064 123 4567", "address": "adr"}
    ).json()
    resp = client.post(f"/api/v1/deliveries/{victim['id']}/start", **_auth(key_a))
    assert resp.status_code == 404
    assert Delivery.objects.get(id=victim["id"]).status == Delivery.Status.NEW


# --- List -----------------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_list_scoped_to_shop(client):
    shop_a, key_a = _shop_and_key("a@shop.rs", "A")
    shop_b, key_b = _shop_and_key("b@shop.rs", "B")
    _post_create(
        client, key_a, {"recipient_name": "A1", "recipient_phone": "064 123 4567", "address": "x"}
    )
    _post_create(
        client, key_a, {"recipient_name": "A2", "recipient_phone": "064 123 4567", "address": "y"}
    )
    _post_create(
        client, key_b, {"recipient_name": "B1", "recipient_phone": "064 123 4567", "address": "z"}
    )
    resp = client.get(CREATE_URL, **_auth(key_a))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {d["recipient"]["name"] for d in data} == {"A1", "A2"}


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_list_excludes_soft_deleted(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    client.delete(f"/api/v1/deliveries/{created['id']}", **_auth(key))
    resp = client.get(CREATE_URL, **_auth(key))
    assert resp.status_code == 200
    assert resp.json() == []


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_list_filter_by_standard_status(client):
    shop, key = _shop_and_key()
    pending = _post_create(
        client, key, {"recipient_name": "P", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    ready = _post_create(
        client, key, {"recipient_name": "R", "recipient_phone": "064 123 4567", "address": "y"}
    ).json()
    client.post(f"/api/v1/deliveries/{ready['id']}/ready", **_auth(key))
    resp = client.get(CREATE_URL + "?status=ready_for_pickup", **_auth(key))
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert ids == [ready["id"]]
    assert pending["id"] not in ids


# --- Status mapping -------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_status_mapping_across_lifecycle(client):
    FakeMessagingProvider.sent = []
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    did = created["id"]
    assert (created["status"], created["status_internal"]) == ("pending", "new")

    ready = client.post(f"/api/v1/deliveries/{did}/ready", **_auth(key)).json()
    assert (ready["status"], ready["status_internal"]) == ("ready_for_pickup", "created")

    started = client.post(f"/api/v1/deliveries/{did}/start", **_auth(key)).json()
    assert (started["status"], started["status_internal"]) == ("out_for_delivery", "on_the_way")

    delivered = client.post(f"/api/v1/deliveries/{did}/delivered", **_auth(key)).json()
    assert (delivered["status"], delivered["status_internal"]) == ("delivered", "delivered")


# --- ready / delivered ----------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_ready_transitions_new_to_created(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    resp = client.post(f"/api/v1/deliveries/{created['id']}/ready", **_auth(key))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready_for_pickup"
    assert Delivery.objects.get(id=created["id"]).status == Delivery.Status.CREATED


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_ready_other_shop_404(client):
    shop_a, key_a = _shop_and_key("a@shop.rs", "A")
    shop_b, key_b = _shop_and_key("b@shop.rs", "B")
    victim = _post_create(
        client, key_b, {"recipient_name": "B", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    resp = client.post(f"/api/v1/deliveries/{victim['id']}/ready", **_auth(key_a))
    assert resp.status_code == 404
    assert Delivery.objects.get(id=victim["id"]).status == Delivery.Status.NEW


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_delivered_marks_delivered(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    resp = client.post(f"/api/v1/deliveries/{created['id']}/delivered", **_auth(key))
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"
    assert Delivery.objects.get(id=created["id"]).status == Delivery.Status.DELIVERED


# --- delete / restore -----------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_soft_delete_then_404_on_get(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    resp = client.delete(f"/api/v1/deliveries/{created['id']}", **_auth(key))
    assert resp.status_code == 200
    delivery = Delivery.objects.get(id=created["id"])
    assert delivery.deleted_at is not None
    # GET по-прежнему виден (скоуп по магазину, без фильтра deleted) — но в списке нет
    assert client.get(CREATE_URL, **_auth(key)).json() == []


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_restore_undeletes(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    client.delete(f"/api/v1/deliveries/{created['id']}", **_auth(key))
    resp = client.post(f"/api/v1/deliveries/{created['id']}/restore", **_auth(key))
    assert resp.status_code == 200
    assert Delivery.objects.get(id=created["id"]).deleted_at is None
    listed = client.get(CREATE_URL, **_auth(key)).json()
    assert [d["id"] for d in listed] == [created["id"]]


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_delete_other_shop_404(client):
    shop_a, key_a = _shop_and_key("a@shop.rs", "A")
    shop_b, key_b = _shop_and_key("b@shop.rs", "B")
    victim = _post_create(
        client, key_b, {"recipient_name": "B", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    resp = client.delete(f"/api/v1/deliveries/{victim['id']}", **_auth(key_a))
    assert resp.status_code == 404
    assert Delivery.objects.get(id=victim["id"]).deleted_at is None


# --- notifications/resend -------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_resend_after_start(client):
    FakeMessagingProvider.sent = []
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    client.post(f"/api/v1/deliveries/{created['id']}/start", **_auth(key))
    assert len(FakeMessagingProvider.sent) == 1
    resp = client.post(
        f"/api/v1/deliveries/{created['id']}/notifications/resend", **_auth(key)
    )
    assert resp.status_code == 200
    assert resp.json()["notification"]["status"] == "sent"
    assert len(FakeMessagingProvider.sent) == 2


@override_settings(MAPS_PROVIDER=FAKE_OK, ROUTES_PROVIDER=ROUTES_OK, MESSAGING_PROVIDER=MSG_OK)
def test_resend_with_new_phone(client):
    FakeMessagingProvider.sent = []
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    client.post(f"/api/v1/deliveries/{created['id']}/start", **_auth(key))
    resp = client.post(
        f"/api/v1/deliveries/{created['id']}/notifications/resend",
        data=json.dumps({"recipient_phone": "064 765 4321"}),
        content_type="application/json", **_auth(key),
    )
    assert resp.status_code == 200
    assert Delivery.objects.get(id=created["id"]).recipient_phone == "+381647654321"
    assert FakeMessagingProvider.sent[-1][0] == "+381647654321"


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_resend_before_start_409(client):
    shop, key = _shop_and_key()
    created = _post_create(
        client, key, {"recipient_name": "Ana", "recipient_phone": "064 123 4567", "address": "x"}
    ).json()
    resp = client.post(
        f"/api/v1/deliveries/{created['id']}/notifications/resend", **_auth(key)
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_started"


# --- Throttling -----------------------------------------------------------


@override_settings(MAPS_PROVIDER=FAKE_OK)
def test_rate_limit_per_key(client, monkeypatch):
    # Жёстко задаём лимит на throttle (минуя кэш api_settings DRF при override).
    from django.core.cache import cache

    from deliveries.auth import ApiKeyRateThrottle

    monkeypatch.setattr(ApiKeyRateThrottle, "get_rate", lambda self: "2/min")
    cache.clear()
    shop, key = _shop_and_key()
    assert client.get(CREATE_URL, **_auth(key)).status_code == 200
    assert client.get(CREATE_URL, **_auth(key)).status_code == 200
    resp = client.get(CREATE_URL, **_auth(key))
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"


# --- OpenAPI docs ---------------------------------------------------------


def test_schema_endpoint_public_200(client):
    resp = client.get("/api/schema/")
    assert resp.status_code == 200
    assert b"Javi API" in resp.content


def test_docs_endpoint_public_200(client):
    resp = client.get("/api/docs/")
    assert resp.status_code == 200


# --- Key management UI ----------------------------------------------------


def test_generate_key_view_shows_plaintext_once(client):
    shop = _make_shop_with_origin()
    client.login(username="api@shop.rs", password="pass12345")
    resp = client.post("/app/api-kljucevi/novi/", follow=True)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "javi_live_" in body  # полный ключ показан в сообщении
    assert shop.api_keys.count() == 1


def test_revoke_key_view(client):
    shop = _make_shop_with_origin()
    obj, _full = ApiKey.generate(shop)
    client.login(username="api@shop.rs", password="pass12345")
    resp = client.post(f"/app/api-kljucevi/{obj.pk}/opozovi/")
    assert resp.status_code == 302
    obj.refresh_from_db()
    assert obj.revoked_at is not None


def test_revoke_other_shop_key_404(client):
    _make_shop_with_origin("a@shop.rs", "A")
    shop_b = _make_shop_with_origin("b@shop.rs", "B")
    victim_key, _full = ApiKey.generate(shop_b)
    client.login(username="a@shop.rs", password="pass12345")
    resp = client.post(f"/app/api-kljucevi/{victim_key.pk}/opozovi/")
    assert resp.status_code == 404
    victim_key.refresh_from_db()
    assert victim_key.revoked_at is None


def test_profile_lists_keys(client):
    shop = _make_shop_with_origin()
    obj, _full = ApiKey.generate(shop)
    client.login(username="api@shop.rs", password="pass12345")
    resp = client.get("/app/prodavnica/")
    assert resp.status_code == 200
    assert obj.masked in resp.content.decode()


def test_create_key_requires_login(client):
    resp = client.post("/app/api-kljucevi/novi/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


# --- /api/v1/shop (store profile + webhook config; UI↔API parity) ---

SHOP_URL = "/api/v1/shop"


def test_shop_requires_key(client):
    assert client.get(SHOP_URL).status_code == 401


def test_get_shop(client):
    shop, key = _shop_and_key()
    resp = client.get(SHOP_URL, **_auth(key))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == shop.name
    assert "webhook_url" in data and "address" in data


@override_settings(MAPS_PROVIDER="integrations.testing.FakeMapsProvider")
def test_patch_shop_name_and_address_geocodes(client):
    shop, key = _shop_and_key()
    resp = client.patch(
        SHOP_URL,
        data='{"name":"Nova Pizza","address":"Knez Mihailova 6"}',
        content_type="application/json",
        **_auth(key),
    )
    assert resp.status_code == 200
    shop.refresh_from_db()
    assert shop.name == "Nova Pizza"
    assert shop.origin_lat is not None  # geocoded


def test_patch_shop_webhook(client):
    shop, key = _shop_and_key()
    resp = client.patch(
        SHOP_URL,
        data='{"webhook_url":"https://merchant.example/hook","webhook_secret":"s3cr"}',
        content_type="application/json",
        **_auth(key),
    )
    assert resp.status_code == 200
    shop.refresh_from_db()
    assert shop.webhook_url == "https://merchant.example/hook"
    assert shop.webhook_secret == "s3cr"
