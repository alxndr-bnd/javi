"""Brute-force protection and the admin path (SERBITO-362, JAVI-2)."""

import importlib

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import clear_url_caches, reverse

import config.urls

pytestmark = pytest.mark.django_db

LOGIN = "/accounts/login/"
PASSWORD = "right-pass-123"


@pytest.fixture
def user():
    return get_user_model().objects.create_user(email="owner@shop.rs", password=PASSWORD)


def _login(client, password, email="owner@shop.rs", ip="203.0.113.7"):
    return client.post(LOGIN, {"username": email, "password": password}, REMOTE_ADDR=ip)


@override_settings(LOGIN_FAILURE_LIMIT_IP=3, LOGIN_FAILURE_LIMIT_ACCOUNT=100)
def test_ip_locked_after_failures_even_with_right_password(client, user):
    for _ in range(3):
        assert _login(client, "wrong").status_code == 200
    resp = _login(client, PASSWORD)
    assert resp.status_code == 200  # form again, not the redirect to /app/
    assert "Too many failed sign-in attempts" in resp.content.decode()
    assert "_auth_user_id" not in client.session
    # another client IP is not affected
    assert _login(client, PASSWORD, ip="198.51.100.9").status_code == 302


@override_settings(LOGIN_FAILURE_LIMIT_IP=100, LOGIN_FAILURE_LIMIT_ACCOUNT=3)
def test_account_locked_after_failures_from_many_ips(client, user):
    for n in range(3):
        _login(client, "wrong", ip=f"203.0.113.{n + 1}")
    resp = _login(client, PASSWORD, ip="198.51.100.9")
    assert resp.status_code == 200
    assert "Too many failed sign-in attempts" in resp.content.decode()
    # the account key is case-insensitive
    assert _login(client, PASSWORD, email="OWNER@shop.rs", ip="198.51.100.10").status_code == 200


@override_settings(LOGIN_FAILURE_LIMIT_IP=3, LOGIN_FAILURE_LIMIT_ACCOUNT=100)
def test_below_limit_right_password_signs_in(client, user):
    for _ in range(2):
        _login(client, "wrong")
    assert _login(client, PASSWORD).status_code == 302


@override_settings(LOGIN_FAILURE_LIMIT_IP=2, LOGIN_FAILURE_LIMIT_ACCOUNT=100)
def test_lock_uses_real_client_ip_not_spoofed_xff(client, user):
    front_end = {"REMOTE_ADDR": "169.254.1.1"}
    for spoof in ("1.1.1.1", "2.2.2.2"):
        client.post(
            LOGIN,
            {"username": "owner@shop.rs", "password": "wrong"},
            HTTP_X_FORWARDED_FOR=f"{spoof}, 203.0.113.7",
            **front_end,
        )
    resp = client.post(
        LOGIN,
        {"username": "owner@shop.rs", "password": PASSWORD},
        HTTP_X_FORWARDED_FOR="3.3.3.3, 203.0.113.7",
        **front_end,
    )
    assert "Too many failed sign-in attempts" in resp.content.decode()


@override_settings(LOGIN_FAILURE_LIMIT_IP=2, LOGIN_FAILURE_LIMIT_ACCOUNT=100)
def test_lock_behind_cloudflare_counts_per_visitor_not_per_edge(client, user):
    """SERBITO-420: all visitors of one Cloudflare edge share its address; CF-Connecting-IP
    tells them apart, so one noisy visitor does not lock out the others."""
    edge = {"REMOTE_ADDR": "169.254.1.1", "HTTP_X_FORWARDED_FOR": "203.0.113.7, 172.70.1.1"}
    for _ in range(2):
        client.post(
            LOGIN,
            {"username": "owner@shop.rs", "password": "wrong"},
            HTTP_CF_CONNECTING_IP="203.0.113.7",
            **edge,
        )
    locked = {"username": "owner@shop.rs", "password": PASSWORD}
    resp = client.post(LOGIN, locked, HTTP_CF_CONNECTING_IP="203.0.113.7", **edge)
    assert "Too many failed sign-in attempts" in resp.content.decode()
    resp = client.post(LOGIN, locked, HTTP_CF_CONNECTING_IP="198.51.100.9", **edge)
    assert resp.status_code == 302


# --- admin: moved off /admin/ and covered by the same lockout ---


@pytest.fixture
def admin_at():
    """Mount the admin at a given ADMIN_PATH (urls.py reads it at import)."""
    managers = []

    def mount(path):
        manager = override_settings(ADMIN_PATH=path)
        manager.enable()
        managers.append(manager)
        importlib.reload(config.urls)
        clear_url_caches()

    yield mount
    for manager in managers:
        manager.disable()
    importlib.reload(config.urls)
    clear_url_caches()


def test_admin_not_on_default_path(client):
    # Tests run with DEBUG off and no ADMIN_PATH: the admin is not mounted at all.
    assert client.get("/admin/").status_code == 404
    assert client.get("/admin/login/").status_code == 404


def test_admin_served_at_env_path(client, admin_at):
    admin_at("ops-7f3a/")
    assert client.get("/admin/login/").status_code == 404
    assert client.get("/ops-7f3a/login/").status_code == 200
    assert reverse("admin:index") == "/ops-7f3a/"


@override_settings(LOGIN_FAILURE_LIMIT_IP=2, LOGIN_FAILURE_LIMIT_ACCOUNT=100)
def test_admin_login_is_locked_too(client, admin_at):
    admin_at("ops-7f3a/")
    get_user_model().objects.create_superuser(email="staff@javi.rs", password=PASSWORD)
    url = "/ops-7f3a/login/"
    for _ in range(2):
        client.post(url, {"username": "staff@javi.rs", "password": "wrong"})
    resp = client.post(url, {"username": "staff@javi.rs", "password": PASSWORD})
    assert resp.status_code == 200  # refused although the password is right
    assert "_auth_user_id" not in client.session


@override_settings(LOGIN_FAILURE_LIMIT_IP=1, LOGIN_FAILURE_LIMIT_ACCOUNT=100)
def test_lockout_message_in_serbian(client, user):
    _login(client, "wrong")
    resp = client.post(
        LOGIN,
        {"username": "owner@shop.rs", "password": PASSWORD},
        REMOTE_ADDR="203.0.113.7",
        HTTP_ACCEPT_LANGUAGE="sr",
    )
    assert "Previše neuspešnih pokušaja prijave" in resp.content.decode()
