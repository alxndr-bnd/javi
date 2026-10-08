"""SERBITO-467: recipient name/phone/address are erased RECIPIENT_PII_RETENTION_DAYS after the
delivery is final; status, rating, dates and city stay; opt-outs keep blocking sends."""

import logging
import re
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from deliveries import retention
from deliveries.models import ApiKey, Delivery, Rating, Shop, TrackingToken
from deliveries.retention import purge_recipient_pii
from deliveries.services import mark_delivered, restore, send_rating_request
from integrations.models import GeocodeCache
from notifications.models import Notification, OptOut, OutboundSend

pytestmark = pytest.mark.django_db

PHONE = "+381641234567"
ADDRESS = "Knez Mihailova 1"
NAME = "Ana Test"
SECRET = "t0ken"
MSG_OK = "integrations.testing.FakeMessagingProvider"
DAYS = settings.RECIPIENT_PII_RETENTION_DAYS


def _ago(days: float):
    return timezone.now() - timedelta(days=days)


def _shop(email="r@shop.rs"):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    return Shop.objects.create(owner=user, name="Shop", origin_lat=44.8, origin_lng=20.45)


def _delivery(shop, *, created_days=0, **fields):
    d = Delivery.objects.create(
        shop=shop,
        recipient_name=NAME,
        recipient_phone=PHONE,
        dest_address=ADDRESS,
        dest_city="Beograd",
        dest_lat=44.81,
        dest_lng=20.46,
        description="2 pizzas",
        **fields,
    )
    Delivery.objects.filter(pk=d.pk).update(created_at=_ago(created_days))
    TrackingToken.objects.create(delivery=d)
    d.refresh_from_db()
    return d


def _is_purged(d) -> bool:
    d.refresh_from_db()
    return d.pii_purged_at is not None


def _assert_erased(d):
    d.refresh_from_db()
    assert (d.recipient_name, d.recipient_phone, d.dest_address) == ("", "", "")
    assert (d.dest_lat, d.dest_lng) == (None, None)
    assert d.pii_purged_at is not None
    assert not TrackingToken.objects.filter(delivery=d).exists()


def test_old_delivered_delivery_is_erased_and_keeps_its_stats():
    shop = _shop()
    old = _delivery(
        shop,
        created_days=DAYS + 5,
        status=Delivery.Status.DELIVERED,
        delivered_at=_ago(DAYS + 1),
        started_at=_ago(DAYS + 2),
        eta_at=_ago(DAYS + 2),
    )
    Rating.objects.create(delivery=old, value=5)

    result = purge_recipient_pii(apply=True)

    _assert_erased(old)
    assert result.deliveries == 1 and result.tracking_tokens == 1
    # Non-personal data for the shop's stats and ratings stays.
    assert old.status == Delivery.Status.DELIVERED
    assert old.dest_city == "Beograd"
    assert old.delivered_at and old.started_at and old.eta_at and old.created_at
    assert old.rating.value == 5
    assert old.description == "2 pizzas"


def test_fresh_deliveries_are_kept():
    shop = _shop()
    fresh_delivered = _delivery(
        shop,
        created_days=DAYS + 30,  # created long ago, but delivered recently
        status=Delivery.Status.DELIVERED,
        delivered_at=_ago(DAYS - 1),
    )
    fresh_new = _delivery(shop, created_days=1)
    # Deleted recently: the period runs from the deletion, not from the creation.
    fresh_deleted = _delivery(shop, created_days=DAYS + 30, deleted_at=_ago(3))

    result = purge_recipient_pii(apply=True)

    assert result.deliveries == 0
    for d in (fresh_delivered, fresh_new, fresh_deleted):
        d.refresh_from_db()
        assert (d.recipient_name, d.recipient_phone, d.dest_address) == (NAME, PHONE, ADDRESS)
        assert d.pii_purged_at is None
        assert TrackingToken.objects.filter(delivery=d).exists()


def test_deleted_and_legacy_delivered_deliveries_count_as_final():
    shop = _shop()
    deleted = _delivery(shop, created_days=DAYS + 10, deleted_at=_ago(DAYS + 1))
    # Deleted while on the way: deleted is final, whatever the status.
    deleted_active = _delivery(
        shop,
        created_days=DAYS + 10,
        status=Delivery.Status.ON_THE_WAY,
        deleted_at=_ago(DAYS + 1),
    )
    # Delivered before delivered_at existed: falls back to the ETA.
    legacy = _delivery(
        shop, created_days=DAYS + 3, status=Delivery.Status.DELIVERED, eta_at=_ago(DAYS + 2)
    )
    # Delivered long ago by creation, but the ETA is inside the period: still kept.
    late_eta = _delivery(
        shop,
        created_days=DAYS + 3,
        status=Delivery.Status.DELIVERED,
        started_at=_ago(DAYS + 2),
        eta_at=_ago(DAYS - 2),
    )

    purge_recipient_pii(apply=True)

    for d in (deleted, deleted_active, legacy):
        _assert_erased(d)
    assert not _is_purged(late_eta)


@pytest.mark.parametrize(
    "status",
    [Delivery.Status.NEW, Delivery.Status.CREATED, Delivery.Status.ON_THE_WAY],
)
def test_stale_active_deliveries_are_kept_and_counted(status):
    """An active delivery is never final: the shop may still need the phone and address."""
    shop = _shop()
    stale = _delivery(
        shop,
        created_days=DAYS + 30,
        status=status,
        started_at=_ago(DAYS + 20),
        eta_at=_ago(DAYS + 20),
    )
    _delivery(shop, created_days=1, status=status)  # fresh: neither purged nor counted

    dry = purge_recipient_pii(apply=False)
    result = purge_recipient_pii(apply=True)

    assert (dry.deliveries, dry.stale_active) == (0, 1)
    assert (result.deliveries, result.stale_active) == (0, 1)
    stale.refresh_from_db()
    assert (stale.recipient_name, stale.recipient_phone, stale.dest_address) == (
        NAME,
        PHONE,
        ADDRESS,
    )
    assert stale.pii_purged_at is None
    assert TrackingToken.objects.filter(delivery=stale).exists()


def test_command_reports_stale_active_deliveries_separately():
    shop = _shop()
    _delivery(shop, created_days=DAYS + 5, status=Delivery.Status.ON_THE_WAY)
    _delivery(shop, created_days=DAYS + 5, status=Delivery.Status.DELIVERED)
    out = StringIO()

    call_command("purge_recipient_pii", "--apply", stdout=out)

    assert "deliveries: 1" in out.getvalue()
    assert "Kept: 1 active deliveries" in out.getvalue()
    assert Delivery.objects.filter(pii_purged_at__isnull=True).count() == 1


def test_apply_skips_rows_that_stop_being_due_after_the_id_read(monkeypatch):
    """The update checks the rows again under a lock: a row changed between the id read and
    the update (here: restored to active) keeps its data."""
    shop = _shop()
    racing = _delivery(shop, created_days=DAYS + 10, deleted_at=_ago(DAYS + 1))
    real_ids = retention._ids
    calls = []

    def ids_then_restore(qs, batch_size):
        ids = real_ids(qs, batch_size)
        if qs.model is Delivery and not calls:
            calls.append(ids)
            Delivery.objects.filter(pk=racing.pk).update(deleted_at=None)
        return ids

    monkeypatch.setattr(retention, "_ids", ids_then_restore)
    result = purge_recipient_pii(apply=True)

    assert calls == [[racing.pk]]
    assert result.deliveries == 0
    assert not _is_purged(racing)
    assert racing.recipient_phone == PHONE


@pytest.mark.parametrize(
    ("days", "batch", "ok"),
    [(90, 500, True), (30, 1, True), (29, 500, False), (0, 500, False), (90, 0, False)],
)
def test_retention_settings_are_validated_at_startup(days, batch, ok):
    with override_settings(RECIPIENT_PII_RETENTION_DAYS=days, RECIPIENT_PII_PURGE_BATCH_SIZE=batch):
        app = apps.get_app_config("deliveries")
        if ok:
            app.ready()
        else:
            with pytest.raises(ImproperlyConfigured):
                app.ready()


def test_dry_run_counts_and_changes_nothing():
    shop = _shop()
    old = _delivery(shop, created_days=DAYS + 1, status=Delivery.Status.DELIVERED)
    _delivery(shop, created_days=1)
    OutboundSend.objects.create(
        shop=shop, phone=PHONE, kind="on_the_way", created_at=_ago(DAYS + 1)
    )
    GeocodeCache.objects.create(normalized_address="old", lat=1, lng=1, formatted_address="x")
    GeocodeCache.objects.filter(normalized_address="old").update(created_at=_ago(DAYS + 1))

    result = purge_recipient_pii(apply=False)

    assert result.as_dict() == {
        "deliveries": 1,
        "tracking_tokens": 1,
        "outbound_phones": 1,
        "geocode_entries": 1,
        "stale_active": 0,
        "complete": True,
    }
    assert not _is_purged(old)
    assert old.recipient_phone == PHONE
    assert OutboundSend.objects.get().phone == PHONE
    assert GeocodeCache.objects.count() == 1


def test_apply_is_idempotent_and_batched():
    shop = _shop()
    olds = [
        _delivery(shop, created_days=DAYS + 1 + i, status=Delivery.Status.DELIVERED)
        for i in range(5)
    ]

    first = purge_recipient_pii(apply=True, batch_size=2)
    stamps = {d.pk: Delivery.objects.get(pk=d.pk).pii_purged_at for d in olds}
    second = purge_recipient_pii(apply=True, batch_size=2)

    assert first.deliveries == 5 and first.complete
    assert second.deliveries == 0 and second.tracking_tokens == 0
    for d in olds:
        _assert_erased(d)
        assert d.pii_purged_at == stamps[d.pk]  # the second run does not touch the row


def test_time_budget_stops_between_batches():
    shop = _shop()
    for i in range(3):
        _delivery(shop, created_days=DAYS + 1 + i, status=Delivery.Status.DELIVERED)

    result = purge_recipient_pii(apply=True, batch_size=1, time_budget=1e-9)

    assert result.complete is False
    assert result.deliveries < 3  # the next run continues
    assert purge_recipient_pii(apply=True).deliveries == 3 - result.deliveries


def test_send_log_phones_and_geocode_cache_follow_the_same_limit():
    shop = _shop()
    old_send = OutboundSend.objects.create(
        shop=shop, phone=PHONE, kind="on_the_way", created_at=_ago(DAYS + 1)
    )
    new_send = OutboundSend.objects.create(shop=shop, phone=PHONE, kind="on_the_way")
    GeocodeCache.objects.create(normalized_address="old", lat=1, lng=1, formatted_address="x")
    GeocodeCache.objects.create(normalized_address="new", lat=1, lng=1, formatted_address="y")
    GeocodeCache.objects.filter(normalized_address="old").update(created_at=_ago(DAYS + 1))

    result = purge_recipient_pii(apply=True)

    assert (result.outbound_phones, result.geocode_entries) == (1, 1)
    old_send.refresh_from_db()
    new_send.refresh_from_db()
    assert old_send.phone == "" and old_send.shop == shop  # the shop's counters stay
    assert new_send.phone == PHONE
    assert list(GeocodeCache.objects.values_list("normalized_address", flat=True)) == ["new"]


@override_settings(MESSAGING_PROVIDER=MSG_OK)
def test_opt_out_still_blocks_sends_after_the_purge():
    shop = _shop()
    _delivery(shop, created_days=DAYS + 1, status=Delivery.Status.DELIVERED)
    OptOut.objects.create(phone=PHONE)

    purge_recipient_pii(apply=True)

    assert OptOut.objects.filter(phone=PHONE).exists()
    again = _delivery(
        shop, status=Delivery.Status.DELIVERED, eta_at=_ago(0.1), started_at=_ago(0.2)
    )
    assert send_rating_request(again) is None
    assert not Notification.objects.filter(delivery=again).exists()
    assert not OutboundSend.objects.exists()


def test_logs_and_command_output_carry_counts_only(caplog):
    shop = _shop()
    _delivery(shop, created_days=DAYS + 1, status=Delivery.Status.DELIVERED)
    out = StringIO()

    with caplog.at_level(logging.INFO, logger="deliveries.retention"):
        call_command("purge_recipient_pii", stdout=out)
        assert "deliveries: 1" in out.getvalue()
        assert "Nothing changed" in out.getvalue()
        assert Delivery.objects.get().pii_purged_at is None
        call_command("purge_recipient_pii", "--apply", stdout=out)

    assert Delivery.objects.get().pii_purged_at is not None
    text = out.getvalue() + caplog.text
    assert "recipient PII purge" in caplog.text
    for secret in (PHONE, PHONE[1:], ADDRESS, NAME):
        assert secret not in text


@override_settings(TASKS_SECRET=SECRET)
def test_scheduler_endpoint_needs_the_secret_and_post(client):
    shop = _shop()
    old = _delivery(shop, created_days=DAYS + 1, status=Delivery.Status.DELIVERED)
    url = reverse("tasks:purge_recipient_pii")

    assert client.post(url).status_code == 403
    assert client.post(url, HTTP_X_TASKS_SECRET="wrong").status_code == 403
    assert client.get(url, HTTP_X_TASKS_SECRET=SECRET).status_code == 405
    assert not _is_purged(old)

    resp = client.post(url, HTTP_X_TASKS_SECRET=SECRET)
    assert resp.status_code == 200
    assert resp.json()["deliveries"] == 1 and resp.json()["complete"] is True
    assert PHONE not in resp.content.decode()
    _assert_erased(old)


def test_mark_delivered_starts_the_retention_clock(client):
    shop = _shop()
    d = _delivery(shop, status=Delivery.Status.ON_THE_WAY)
    assert mark_delivered(d) is True
    d.refresh_from_db()
    assert d.delivered_at is not None

    # The recipient's "received" button on /t/ sets it too.
    other = _delivery(shop, status=Delivery.Status.ON_THE_WAY)
    client.post(f"/t/{other.tracking_token.token}/primljeno/")
    other.refresh_from_db()
    assert other.status == Delivery.Status.DELIVERED and other.delivered_at is not None


def test_cabinet_hides_purged_deliveries_and_does_not_restore_them(client):
    shop = _shop()
    _delivery(shop, created_days=DAYS + 1, status=Delivery.Status.DELIVERED)
    deleted = _delivery(shop, created_days=DAYS + 10, deleted_at=_ago(DAYS + 1))
    purge_recipient_pii(apply=True)
    client.login(username="r@shop.rs", password="pass12345")

    assert len(client.get(reverse("deliveries:list")).context["deliveries"]) == 0
    assert client.get(reverse("deliveries:deleted")).context["deleted"] == []
    resp = client.post(reverse("deliveries:restore", args=[deleted.pk]))
    assert resp.status_code == 404
    deleted.refresh_from_db()
    assert restore(deleted) is False and deleted.deleted_at is not None


def test_privacy_page_states_the_configured_period():
    page = (Path(settings.BASE_DIR) / "landing" / "privacy.html").read_text(encoding="utf-8")
    for lang, word in (("sr", "dana"), ("en", "days"), ("ru", "дней")):
        para = re.search(rf'<p id="recipient-retention-{lang}">(.*?)</p>', page, re.S)
        assert para, lang
        assert f"<strong>{DAYS} {word}</strong>" in para.group(1), lang


# --- SERBITO-467: a purged delivery is read-only, in the cabinet and in the API ---------------


def _purged(shop, **fields):
    d = _delivery(shop, created_days=DAYS + 5, status=Delivery.Status.DELIVERED, **fields)
    purge_recipient_pii(apply=True)
    assert _is_purged(d)
    return d


@pytest.mark.parametrize(
    ("name", "method"),
    [
        ("deliveries:edit", "get"),
        ("deliveries:edit", "post"),
        ("deliveries:start", "post"),
        ("deliveries:resend", "post"),
        ("deliveries:mark_delivered", "post"),
        ("deliveries:mark_ready", "post"),
        ("deliveries:delete", "post"),
    ],
)
def test_cabinet_views_do_not_touch_a_purged_delivery(client, name, method):
    shop = _shop()
    d = _purged(shop)
    before = Delivery.objects.filter(pk=d.pk).values().get()
    client.login(username="r@shop.rs", password="pass12345")

    data = {"phone": "064 123 4567", "eta_time": "12:00"} if method == "post" else None
    resp = getattr(client, method)(reverse(name, args=[d.pk]), data)

    assert resp.status_code == 404
    assert Delivery.objects.filter(pk=d.pk).values().get() == before


@pytest.mark.parametrize(
    ("suffix", "method"),
    [
        ("", "get"),
        ("", "delete"),
        ("/start", "post"),
        ("/dispatch", "post"),
        ("/ready", "post"),
        ("/delivered", "post"),
        ("/restore", "post"),
        ("/notifications/resend", "post"),
    ],
)
def test_api_returns_404_for_a_purged_delivery(client, suffix, method):
    shop = _shop()
    d = _purged(shop)
    before = Delivery.objects.filter(pk=d.pk).values().get()
    _, key = ApiKey.generate(shop)

    url = f"/api/v1/deliveries/{d.pk}{suffix}"
    auth = {"HTTP_AUTHORIZATION": f"Bearer {key}"}
    if method == "post":
        resp = client.post(url, data="{}", content_type="application/json", **auth)
    else:
        resp = getattr(client, method)(url, **auth)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert Delivery.objects.filter(pk=d.pk).values().get() == before


def test_api_list_hides_purged_deliveries(client):
    shop = _shop()
    purged = _purged(shop)
    purged_deleted = _delivery(shop, created_days=DAYS + 10, deleted_at=_ago(DAYS + 1))
    purge_recipient_pii(apply=True)
    live = _delivery(shop, created_days=1)
    _, key = ApiKey.generate(shop)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {key}"}

    active = client.get("/api/v1/deliveries", **auth).json()
    deleted = client.get("/api/v1/deliveries?deleted=true", **auth).json()

    assert [row["id"] for row in active] == [live.pk]
    assert purged.pk not in [row["id"] for row in active]
    assert purged_deleted.pk not in [row["id"] for row in deleted]
