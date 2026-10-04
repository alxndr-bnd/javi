"""Open signup guard rails (SERBITO-357): per-IP signup limit and a WARNING per new store."""

import json
import logging

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from common.logging import JsonFormatter
from deliveries.models import Shop

pytestmark = pytest.mark.django_db

REGISTER = reverse("accounts:register")


def _signup(client, n, ip="203.0.113.7", **extra):
    return client.post(
        REGISTER,
        {
            "email": f"shop{n}@example.rs",
            "store_name": f"Shop {n}",
            "password1": "s3cret-pass-9",
            "password2": "s3cret-pass-9",
        },
        REMOTE_ADDR=ip,
        **extra,
    )


@override_settings(SIGNUP_LIMIT_PER_IP_DAY=2)
def test_signups_per_ip_are_limited(client):
    assert _signup(client, 1).status_code == 302
    client.logout()
    assert _signup(client, 2).status_code == 302
    client.logout()
    resp = _signup(client, 3)
    assert resp.status_code == 429
    assert "Too many new accounts from your network today" in resp.content.decode()
    assert not get_user_model().objects.filter(email="shop3@example.rs").exists()
    assert Shop.objects.count() == 2
    # another client IP still signs up
    assert _signup(client, 4, ip="198.51.100.9").status_code == 302


@override_settings(SIGNUP_LIMIT_PER_IP_DAY=1)
def test_signup_limit_ignores_spoofed_forwarded_for(client):
    front_end = "169.254.1.1"  # REMOTE_ADDR on Cloud Run: the Google front end
    xff = "1.1.1.1, 203.0.113.7"
    assert _signup(client, 1, ip=front_end, HTTP_X_FORWARDED_FOR=xff).status_code == 302
    client.logout()
    xff = "2.2.2.2, 203.0.113.7"
    assert _signup(client, 2, ip=front_end, HTTP_X_FORWARDED_FOR=xff).status_code == 429


@override_settings(SIGNUP_LIMIT_PER_IP_DAY=1)
def test_signup_limit_behind_cloudflare_uses_cf_connecting_ip(client):
    """SERBITO-420: the edge address is shared; CF-Connecting-IP is the visitor."""
    edge = {"ip": "169.254.1.1", "HTTP_X_FORWARDED_FOR": "203.0.113.7, 172.70.1.1"}
    assert _signup(client, 1, HTTP_CF_CONNECTING_IP="203.0.113.7", **edge).status_code == 302
    client.logout()
    assert _signup(client, 2, HTTP_CF_CONNECTING_IP="203.0.113.7", **edge).status_code == 429
    assert _signup(client, 3, HTTP_CF_CONNECTING_IP="198.51.100.9", **edge).status_code == 302


@override_settings(SIGNUP_LIMIT_PER_IP_DAY=1)
def test_signup_limit_ignores_spoofed_cf_connecting_ip(client):
    """Without a Cloudflare hop (DNS-only, or straight to *.run.app) the header is ignored."""
    real = {"ip": "169.254.1.1", "HTTP_X_FORWARDED_FOR": "203.0.113.7"}
    assert _signup(client, 1, HTTP_CF_CONNECTING_IP="1.1.1.1", **real).status_code == 302
    client.logout()
    assert _signup(client, 2, HTTP_CF_CONNECTING_IP="2.2.2.2", **real).status_code == 429


@override_settings(SIGNUP_LIMIT_PER_IP_DAY=5)
def test_failed_signup_does_not_use_up_the_limit(client):
    for _ in range(6):
        client.post(REGISTER, {"email": "bad", "store_name": "X"}, REMOTE_ADDR="203.0.113.7")
    assert _signup(client, 1).status_code == 302


def test_new_store_is_logged_as_warning_with_event(client, caplog):
    with caplog.at_level(logging.WARNING, logger="accounts.views"):
        assert _signup(client, 1).status_code == 302
    (record,) = [r for r in caplog.records if getattr(r, "event", None) == "shop.signup"]
    shop = Shop.objects.get()
    assert record.levelname == "WARNING"
    assert record.shop_id == shop.pk and record.shop_name == "Shop 1"
    entry = json.loads(JsonFormatter().format(record))  # what Cloud Logging receives
    assert entry["severity"] == "WARNING" and entry["event"] == "shop.signup"
    assert "shop1@example.rs" not in entry["message"]  # no email in logs
