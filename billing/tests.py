"""SERBITO-593: shop billing — trial, status, limits, Whop checkout and webhook, report.

No real HTTP: ``billing.whop.api_request`` refuses a real call under pytest, so every Whop
call here goes through a mocked ``requests.request``.
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from billing import services, whop
from billing.models import BillingPayment, ShopSubscription
from deliveries.models import Shop
from notifications.quotas import QuotaExceeded, reserve_send, shop_limits

pytestmark = pytest.mark.django_db

SECRET_BYTES = b"javi-test-webhook-key-32-bytes!!"
SECRET = "whsec_" + base64.b64encode(SECRET_BYTES).decode()
BIZ = "biz_TESTjavi000001"
PROD = "prod_TESTjavi0001"
WEBHOOK = "/billing/whop/webhook/"

_n = 0


def _shop(*, verified=True, age_days=0):
    global _n
    _n += 1
    user = get_user_model().objects.create_user(email=f"bill{_n}@example.com", password="x")
    shop = Shop.objects.create(owner=user, name=f"Shop {_n}", sending_verified=verified)
    if age_days:
        Shop.objects.filter(pk=shop.pk).update(created_at=timezone.now() - timedelta(days=age_days))
        shop.refresh_from_db()
    return shop


@pytest.fixture
def on(settings):
    settings.JAVI_BILLING_ENABLED = True
    settings.JAVI_BILLING_START_DATE = "2020-01-01"
    settings.WHOP_API_KEY = "test-key"
    settings.WHOP_WEBHOOK_SECRET = SECRET
    settings.WHOP_COMPANY_ID = BIZ
    settings.WHOP_PRODUCT_ID = PROD
    settings.PUBLIC_BASE_URL = "https://javi.serbito.rs"
    return settings


def _response(body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.headers = {}
    return resp


def _signed(body: bytes, *, secret_bytes=SECRET_BYTES, stamp=None):
    msg_id = "msg_test"
    stamp = str(stamp if stamp is not None else int(time.time()))
    sig = base64.b64encode(
        hmac.new(secret_bytes, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return {
        "HTTP_WEBHOOK_ID": msg_id,
        "HTTP_WEBHOOK_TIMESTAMP": stamp,
        "HTTP_WEBHOOK_SIGNATURE": f"v1,{sig}",
    }


def _post_event(client, event, data, **extra):
    body = json.dumps({"type": event, "account_id": BIZ, "data": data}).encode()
    return client.post(
        WEBHOOK, data=body, content_type="application/json", **_signed(body), **extra
    )


def _membership(shop, status="active", **fields):
    data = {
        "id": "mem_TEST0001",
        "status": status,
        "company": {"id": BIZ},
        "product": {"id": PROD},
        "metadata": {"shop_id": str(shop.pk), "shop_token": whop.shop_token(shop.pk)},
        "renewal_period_end": "2026-12-01T10:00:00Z",
        "cancel_at_period_end": False,
        "manage_url": "https://whop.com/billing/manage/mem_TEST0001",
    }
    data.update(fields)
    return data


# ---- trial, status, access --------------------------------------------------------------


def test_billing_off_never_restricts(settings):
    settings.JAVI_BILLING_ENABLED = False
    shop = _shop(age_days=400)
    assert services.has_access(shop)
    assert services.summary(shop) is None


def test_flag_on_without_start_date_does_not_restrict(settings, caplog):
    settings.JAVI_BILLING_ENABLED = True
    settings.JAVI_BILLING_START_DATE = ""
    assert services.has_access(_shop(age_days=400))


def test_new_shop_has_30_free_days(on):
    shop = _shop()
    assert services.shop_status(shop) == "trial"
    assert services.has_access(shop)
    assert services.trial_days_left(shop) == 30
    later = timezone.now() + timedelta(days=31)
    assert not services.has_access(shop, now=later)


def test_existing_shop_trial_starts_on_the_billing_start_date(on):
    on.JAVI_BILLING_START_DATE = str(timezone.localdate())
    shop = _shop(age_days=200)
    assert services.has_access(shop)
    assert 29 <= services.trial_days_left(shop) <= 30


def test_trial_ended_without_payment_loses_access(on):
    assert not services.has_access(_shop(age_days=31))


def test_staff_can_extend_the_trial(on):
    shop = _shop(age_days=40)
    ShopSubscription.objects.create(
        shop=shop, trial_ends_override=timezone.now() + timedelta(days=5)
    )
    shop.refresh_from_db()
    assert services.has_access(shop)


def test_active_and_past_due_grace(on):
    shop = _shop(age_days=60)
    sub = ShopSubscription.objects.create(shop=shop, status="active")
    shop.refresh_from_db()
    assert services.has_access(shop)
    sub.status = "past_due"
    sub.past_due_since = timezone.now() - timedelta(days=3)
    sub.save()
    shop.refresh_from_db()
    assert services.has_access(shop)
    sub.past_due_since = timezone.now() - timedelta(days=8)
    sub.save()
    shop.refresh_from_db()
    assert not services.has_access(shop)


def test_canceled_during_trial_keeps_the_trial(on):
    shop = _shop(age_days=5)
    ShopSubscription.objects.create(shop=shop, status="canceled")
    shop.refresh_from_db()
    assert services.has_access(shop)


# ---- limits ------------------------------------------------------------------------------


def test_unpaid_verified_shop_gets_the_unverified_limits(on):
    shop = _shop(verified=True, age_days=31)
    limits = shop_limits(shop)
    assert limits.trial and limits.unpaid
    assert (limits.day, limits.month) == (on.SEND_LIMIT_TRIAL_DAY, on.SEND_LIMIT_TRIAL_MONTH)


def test_paid_verified_shop_keeps_the_normal_limits(on):
    shop = _shop(verified=True, age_days=31)
    ShopSubscription.objects.create(shop=shop, status="active")
    shop.refresh_from_db()
    limits = shop_limits(shop)
    assert not limits.trial and not limits.unpaid


def test_payment_does_not_replace_verification(on):
    shop = _shop(verified=False)
    ShopSubscription.objects.create(shop=shop, status="active")
    shop.refresh_from_db()
    assert shop_limits(shop).trial


def test_unpaid_shop_cannot_send_abroad(on):
    shop = _shop(verified=True, age_days=31)
    with pytest.raises(QuotaExceeded) as exc:
        reserve_send(shop, "+4915123456789", kind="on_the_way", risky=True)
    assert exc.value.code == "destination_not_allowed"
    assert "Subscribe" in exc.value.message


# ---- signature ---------------------------------------------------------------------------


def test_signature_ok_bad_and_stale():
    body = b'{"type":"x"}'
    headers = {k[5:].lower().replace("_", "-"): v for k, v in _signed(body).items()}
    assert whop.verify_signature(body, headers, SECRET)
    assert not whop.verify_signature(body + b" ", headers, SECRET)
    assert not whop.verify_signature(body, headers, "whsec_" + base64.b64encode(b"other").decode())
    stale = {
        k[5:].lower().replace("_", "-"): v
        for k, v in _signed(body, stamp=int(time.time()) - 600).items()
    }
    assert not whop.verify_signature(body, stale, SECRET)


def test_ws_secret_is_used_as_given():
    secret = "ws_" + "ab" * 32
    body = b"{}"
    headers = {
        k[5:].lower().replace("_", "-"): v
        for k, v in _signed(body, secret_bytes=secret.encode()).items()
    }
    assert whop.verify_signature(body, headers, secret)


def test_real_whop_call_is_blocked_under_pytest(on):
    with pytest.raises(whop.WhopBlocked):
        whop.api_request("GET", "/memberships/mem_x")


# ---- webhook -----------------------------------------------------------------------------


def test_webhook_without_secret_is_500(client, on):
    on.WHOP_WEBHOOK_SECRET = ""
    assert client.post(WEBHOOK, data=b"{}", content_type="application/json").status_code == 500


def test_webhook_with_bad_signature_is_401(client, on):
    body = b'{"type":"membership.activated"}'
    headers = _signed(body)
    headers["HTTP_WEBHOOK_SIGNATURE"] = "v1,AAAA"
    r = client.post(WEBHOOK, data=body, content_type="application/json", **headers)
    assert r.status_code == 401


def test_membership_activated_makes_the_shop_active(client, on):
    shop = _shop(age_days=10)
    data = _membership(shop)
    with patch("billing.whop.requests.request", return_value=_response(data)) as req:
        r = _post_event(client, "membership.activated", data)
    assert r.status_code == 200
    assert req.call_args.args[:2] == (
        "GET",
        "https://sandbox-api.whop.com/api/v1/memberships/mem_TEST0001",
    )
    sub = ShopSubscription.objects.get(shop=shop)
    assert sub.status == "active" and sub.whop_membership_id == "mem_TEST0001"
    assert sub.manage_url.startswith("https://whop.com/")
    assert sub.current_period_end.year == 2026 and sub.activated_at is not None


def test_membership_read_failure_falls_back_to_event_data(client, on):
    shop = _shop()
    data = _membership(shop, status="trialing")
    with patch("billing.whop.requests.request", return_value=_response({}, status=500)):
        _post_event(client, "membership.activated", data)
    assert ShopSubscription.objects.get(shop=shop).status == "active"


def test_whop_api_state_wins_over_an_old_event(client, on):
    """Events can arrive out of order: the API read is the truth."""
    shop = _shop()
    old_event = _membership(shop, status="active")
    now_state = _membership(shop, status="canceled", canceled_at="2026-11-02T08:00:00Z")
    with patch("billing.whop.requests.request", return_value=_response(now_state)):
        _post_event(client, "membership.activated", old_event)
    assert ShopSubscription.objects.get(shop=shop).status == "canceled"


def test_past_due_then_paid(client, on):
    shop = _shop()
    for status, expected in (("past_due", "past_due"), ("active", "active")):
        data = _membership(shop, status=status)
        with patch("billing.whop.requests.request", return_value=_response(data)):
            _post_event(client, "membership.updated", data)
        sub = ShopSubscription.objects.get(shop=shop)
        assert sub.status == expected
    assert sub.past_due_since is None


def test_membership_without_token_matches_by_checkout_id(client, on):
    shop = _shop()
    ShopSubscription.objects.create(shop=shop, whop_checkout_id="ch_TEST1")
    data = _membership(shop, metadata={}, checkout_configuration_id="ch_TEST1")
    with patch("billing.whop.requests.request", return_value=_response(data)):
        _post_event(client, "membership.activated", data)
    assert ShopSubscription.objects.get(shop=shop).status == "active"


def test_serbito_payment_is_ignored(client, on):
    """Same Whop business: a serbito Auto-bump payment reaches this webhook too."""
    data = {
        "id": "pay_SERBITO1",
        "status": "paid",
        "company": {"id": BIZ},
        "product": {"id": "prod_SERBITOother"},
        "metadata": {"order_id": "12", "order_token": "x" * 32},
        "subtotal": 300,
        "currency": "rsd",
    }
    with patch("billing.whop.requests.request") as req:
        r = _post_event(client, "payment.succeeded", data)
    assert r.status_code == 200
    assert not req.called
    assert not BillingPayment.objects.exists()


def test_event_of_another_business_is_ignored(client, on):
    shop = _shop()
    data = _membership(shop)
    body = json.dumps(
        {"type": "membership.activated", "account_id": "biz_OTHER", "data": data}
    ).encode()
    with patch("billing.whop.requests.request") as req:
        client.post(WEBHOOK, data=body, content_type="application/json", **_signed(body))
    assert not req.called
    assert not ShopSubscription.objects.exists()


def test_payment_succeeded_is_recorded_and_refund_updates_it(client, on):
    shop = _shop()
    payment = {
        "id": "pay_JAVI1",
        "status": "paid",
        "company": {"id": BIZ},
        "product": {"id": PROD},
        "membership": {"id": "mem_TEST0001", "status": "active"},
        "metadata": {"shop_id": str(shop.pk), "shop_token": whop.shop_token(shop.pk)},
        "subtotal": 30,
        "currency": "eur",
        "billing_reason": "subscription_create",
        "paid_at": "2026-11-01T09:00:00Z",
    }
    with patch("billing.whop.requests.request", return_value=_response(_membership(shop))):
        assert _post_event(client, "payment.succeeded", payment).status_code == 200
        _post_event(client, "payment.succeeded", payment)  # redelivery: no duplicate
    p = BillingPayment.objects.get()
    assert (p.shop, p.amount, p.currency) == (shop, Decimal("30"), "EUR")
    assert ShopSubscription.objects.get(shop=shop).status == "active"

    refunded = dict(payment, refunded_amount=30, substatus="refunded")
    with patch("billing.whop.requests.request", return_value=_response(refunded)):
        _post_event(
            client,
            "refund.updated",
            {"id": "rf_1", "status": "succeeded", "payment": {"id": "pay_JAVI1"}},
        )
    p.refresh_from_db()
    assert p.refunded_amount == Decimal("30")


def test_renewal_without_metadata_matches_by_membership(client, on):
    shop = _shop()
    ShopSubscription.objects.create(shop=shop, whop_membership_id="mem_TEST0001", status="active")
    renewal = {
        "id": "pay_JAVI2",
        "status": "paid",
        "account_id": BIZ,
        "product_id": PROD,
        "membership_id": "mem_TEST0001",
        "line_items": [{"subtotal": {"amount": "30.00", "currency": "eur"}}],
        "paid_at": "2026-12-01T09:00:00Z",
    }
    with patch("billing.whop.requests.request", return_value=_response(_membership(shop))):
        _post_event(client, "payment.succeeded", renewal)
    assert BillingPayment.objects.get().shop == shop


def test_webhook_is_served_on_the_run_app_host(client, on):
    on.ALLOWED_HOSTS = ["javi.serbito.rs", ".run.app", "testserver"]
    body = b"{}"
    r = client.post(
        WEBHOOK,
        data=body,
        content_type="application/json",
        HTTP_HOST="javi-aay5lcpxha-ew.a.run.app",
        **_signed(body),
    )
    assert r.status_code == 200
    other = client.post("/accounts/login/", HTTP_HOST="javi-aay5lcpxha-ew.a.run.app")
    assert other.status_code == 403


# ---- checkout ----------------------------------------------------------------------------


def test_subscribe_is_404_when_billing_is_off(client, settings):
    settings.JAVI_BILLING_ENABLED = False
    shop = _shop()
    client.force_login(shop.owner)
    assert client.post(reverse("billing:subscribe")).status_code == 404


def test_subscribe_creates_a_renewal_checkout_with_the_rest_of_the_trial(client, on):
    shop = _shop(age_days=10)
    client.force_login(shop.owner)
    body = {"id": "ch_NEW1", "purchase_url": "/checkout/ch_NEW1/"}
    with patch("billing.whop.requests.request", return_value=_response(body)) as req:
        r = client.post(reverse("billing:subscribe"))
    assert r.status_code == 302
    assert r["Location"] == "https://sandbox.whop.com/checkout/ch_NEW1/"
    method, url = req.call_args.args[:2]
    assert (method, url) == ("POST", "https://sandbox-api.whop.com/api/v1/checkout_configurations")
    sent = req.call_args.kwargs["json"]
    plan = sent["plan"]
    assert plan["plan_type"] == "renewal" and plan["renewal_price"] == 30.0
    assert plan["initial_price"] == 0 and plan["billing_period"] == 30
    assert plan["currency"] == "eur" and plan["product_id"] == PROD
    assert plan["trial_period_days"] == 20
    assert sent["metadata"] == {"shop_id": str(shop.pk), "shop_token": whop.shop_token(shop.pk)}
    assert sent["redirect_url"] == "https://javi.serbito.rs/billing/pretplata/povratak/"
    assert req.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert ShopSubscription.objects.get(shop=shop).whop_checkout_id == "ch_NEW1"


def test_subscribe_after_the_trial_has_no_trial_days(client, on):
    shop = _shop(age_days=45)
    client.force_login(shop.owner)
    body = {"id": "ch_NEW2", "purchase_url": "https://whop.com/checkout/ch_NEW2/"}
    with patch("billing.whop.requests.request", return_value=_response(body)) as req:
        client.post(reverse("billing:subscribe"))
    assert "trial_period_days" not in req.call_args.kwargs["json"]["plan"]


def test_subscribe_refuses_a_non_whop_url(client, on):
    shop = _shop()
    client.force_login(shop.owner)
    body = {"id": "ch_X", "purchase_url": "https://evil.example.com/pay"}
    with patch("billing.whop.requests.request", return_value=_response(body)):
        r = client.post(reverse("billing:subscribe"))
    assert r["Location"] == reverse("deliveries:profile")


def test_subscribe_without_whop_settings_shows_an_error(client, on):
    on.WHOP_PRODUCT_ID = ""
    shop = _shop()
    client.force_login(shop.owner)
    with patch("billing.whop.requests.request") as req:
        r = client.post(reverse("billing:subscribe"))
    assert not req.called and r["Location"] == reverse("deliveries:profile")


def test_active_shop_goes_to_the_whop_manage_page(client, on):
    shop = _shop()
    ShopSubscription.objects.create(
        shop=shop, status="active", manage_url="https://whop.com/billing/manage/mem_1"
    )
    client.force_login(shop.owner)
    with patch("billing.whop.requests.request") as req:
        r = client.post(reverse("billing:subscribe"))
    assert not req.called and r["Location"] == "https://whop.com/billing/manage/mem_1"


# ---- pages, report -----------------------------------------------------------------------


def test_profile_shows_the_trial_and_the_subscribe_button(client, on):
    shop = _shop(age_days=2)
    client.force_login(shop.owner)
    html = client.get(reverse("deliveries:profile"), HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "Free trial" in html and "28 days left" in html
    assert reverse("billing:subscribe") in html


def test_profile_has_no_billing_block_when_off(client, settings):
    settings.JAVI_BILLING_ENABLED = False
    shop = _shop()
    client.force_login(shop.owner)
    html = client.get(reverse("deliveries:profile")).content.decode()
    assert reverse("billing:subscribe") not in html


def test_return_page_redirects_to_the_profile(client, on):
    shop = _shop()
    client.force_login(shop.owner)
    r = client.get(reverse("billing:return"))
    assert r["Location"] == reverse("deliveries:profile")


def test_monthly_report(on):
    paying, refunded = _shop(), _shop(age_days=40)
    _shop()  # in trial
    when = timezone.now()
    BillingPayment.objects.create(
        shop=paying, whop_payment_id="pay_1", amount=30, currency="EUR", paid_at=when
    )
    BillingPayment.objects.create(
        shop=refunded,
        whop_payment_id="pay_2",
        amount=30,
        currency="EUR",
        refunded_amount=30,
        paid_at=when,
    )
    ShopSubscription.objects.create(shop=paying, status="active")
    local = timezone.localdate()
    out = StringIO()
    call_command("billing_report", "--month", f"{local:%Y-%m}", stdout=out)
    text = out.getvalue()
    assert "paying shops: 1" in text
    assert "gross EUR: 60.00 | refunded: 30.00 | est. net after ~17% fee: 19.80" in text
    assert "active 1" in text and "trial_ended 1" in text
    assert "@" not in text  # no e-mails


def test_billing_sync_without_settings_does_nothing(settings):
    settings.WHOP_API_KEY = ""
    out = StringIO()
    call_command("billing_sync", stdout=out)
    assert "not configured" in out.getvalue()


def test_profile_billing_block_in_serbian(client, on):
    shop = _shop(age_days=2)
    client.force_login(shop.owner)
    client.cookies["django_language"] = "sr-latn"
    html = client.get(reverse("deliveries:profile")).content.decode()
    assert "Besplatni probni period" in html and "još 28 dana" in html
    assert "Pretplati se — 30 € / mesečno" in html
