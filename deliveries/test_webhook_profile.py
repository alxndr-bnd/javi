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
