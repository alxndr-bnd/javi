"""Профиль магазина: настройка webhook_url / webhook_secret (login-required, скоуп по shop)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from deliveries.models import Shop

pytestmark = pytest.mark.django_db

PROFILE = reverse("deliveries:profile")


def _user_shop(email="p@shop.rs"):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    shop = Shop.objects.create(owner=user, name="Shop P")
    return user, shop


def test_profile_shows_webhook_fields(client):
    user, _shop = _user_shop()
    client.force_login(user)
    resp = client.get(PROFILE)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "webhook_url" in content
    assert "webhook_secret" in content


def test_save_webhook_settings(client):
    user, shop = _user_shop()
    client.force_login(user)
    resp = client.post(
        PROFILE,
        {
            "name": shop.name,
            "address": "Knez Mihailova 6, Beograd",
            "webhook_url": "https://merchant.example/hook",
            "webhook_secret": "whsec_123",
        },
    )
    assert resp.status_code in (200, 302)
    shop.refresh_from_db()
    assert shop.webhook_url == "https://merchant.example/hook"
    assert shop.webhook_secret == "whsec_123"


def test_webhook_url_validated(client):
    user, shop = _user_shop()
    client.force_login(user)
    resp = client.post(
        PROFILE,
        {"name": shop.name, "address": "adr", "webhook_url": "not-a-url", "webhook_secret": ""},
    )
    assert resp.status_code == 200
    shop.refresh_from_db()
    assert shop.webhook_url == ""  # невалидный URL не сохранён


def test_profile_requires_login(client):
    resp = client.get(PROFILE)
    assert resp.status_code == 302  # redirect to login


# --- SERBITO-362 (JAVI-10): https only; the secret is write-only and never echoed back ---


def _post(client, shop, **fields):
    data = {"name": shop.name, "address": "Knez Mihailova 6, Beograd", "webhook_url": ""}
    return client.post(PROFILE, {**data, **fields})


def test_http_webhook_url_rejected(client):
    user, shop = _user_shop()
    client.force_login(user)
    resp = _post(client, shop, webhook_url="http://merchant.example/hook")
    assert resp.status_code == 200
    assert "must start with https://" in resp.content.decode()
    shop.refresh_from_db()
    assert shop.webhook_url == ""


def test_saved_secret_is_not_echoed_into_the_form(client):
    user, shop = _user_shop()
    shop.webhook_url, shop.webhook_secret = "https://m.example/h", "whsec_do_not_show"
    shop.save()
    client.force_login(user)
    body = client.get(PROFILE).content.decode()
    assert "whsec_do_not_show" not in body
    assert "A secret is set" in body
    assert 'type="password"' in body


def test_empty_secret_field_keeps_the_saved_secret(client):
    user, shop = _user_shop()
    shop.webhook_secret = "whsec_keep"
    shop.save()
    client.force_login(user)
    _post(client, shop, webhook_url="https://m.example/h", webhook_secret="")
    shop.refresh_from_db()
    assert shop.webhook_secret == "whsec_keep"
    assert shop.webhook_url == "https://m.example/h"


def test_new_secret_replaces_and_checkbox_clears(client):
    user, shop = _user_shop()
    shop.webhook_secret = "whsec_old"
    shop.save()
    client.force_login(user)
    _post(client, shop, webhook_secret="whsec_new")
    shop.refresh_from_db()
    assert shop.webhook_secret == "whsec_new"
    _post(client, shop, clear_webhook_secret="on")
    shop.refresh_from_db()
    assert shop.webhook_secret == ""


def test_secret_not_echoed_when_the_form_has_errors(client):
    user, shop = _user_shop()
    client.force_login(user)
    resp = _post(client, shop, webhook_url="http://x.example", webhook_secret="whsec_typed")
    assert "whsec_typed" not in resp.content.decode()


# --- SERBITO-357: a trial store sees how to get verified ---


def test_trial_store_sees_verification_contact(client):
    user, shop = _user_shop()
    client.force_login(user)
    body = client.get(PROFILE).content.decode()
    assert "Trial store" in body
    assert (
        'Write to <a href="mailto:alexander.bondarchuk@gmail.com">'
        "alexander.bondarchuk@gmail.com</a> to get verified." in body
    )


def test_trial_verification_contact_in_serbian(client):
    user, _shop = _user_shop()
    client.force_login(user)
    body = client.get(PROFILE, HTTP_ACCEPT_LANGUAGE="sr").content.decode()
    assert "Pišite na" in body and "mailto:alexander.bondarchuk@gmail.com" in body


def test_verified_store_has_no_trial_note(client):
    user, shop = _user_shop()
    shop.sending_verified = True
    shop.save()
    client.force_login(user)
    body = client.get(PROFILE).content.decode()
    assert "to get verified" not in body
