"""P3 — TelegramProvider: opt-in-only side channel, само-скип без opt-in."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings

from integrations.providers import _build_messaging_chain
from integrations.telegram import TelegramProvider
from notifications.models import TelegramContact

pytestmark = pytest.mark.django_db

PHONE = "+381641234567"


def _telegram_ok(message_id=987):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"ok": True, "result": {"message_id": message_id}}
    return resp


@override_settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="tok")
def test_self_skips_without_optin_no_http():
    """Нет TelegramContact → ok=False и НИ ОДНОГО сетевого вызова."""
    with patch("integrations.telegram.requests.post") as post:
        result = TelegramProvider().send_text(PHONE, "hi")
    assert result.ok is False
    assert result.channel == ""
    post.assert_not_called()


@override_settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="tok")
def test_sends_to_stored_chat_id_when_opted_in():
    TelegramContact.objects.create(phone=PHONE, chat_id="555")
    with patch("integrations.telegram.requests.post", return_value=_telegram_ok()) as post:
        result = TelegramProvider().send_text(PHONE, "hello")
    assert result.ok is True
    assert result.channel == "telegram"
    assert result.provider_message_id == "987"
    url, kwargs = post.call_args[0][0], post.call_args[1]
    assert url == "https://api.telegram.org/bottok/sendMessage"
    assert kwargs["json"] == {"chat_id": "555", "text": "hello"}


@override_settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="tok")
def test_soft_fail_on_network_error():
    TelegramContact.objects.create(phone=PHONE, chat_id="555")
    with patch(
        "integrations.telegram.requests.post",
        side_effect=requests.RequestException("boom"),
    ):
        result = TelegramProvider().send_text(PHONE, "hello")
    assert result.ok is False
    assert result.channel == ""


@override_settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="tok")
def test_soft_fail_on_api_ok_false():
    TelegramContact.objects.create(phone=PHONE, chat_id="555")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"ok": False, "description": "blocked"}
    with patch("integrations.telegram.requests.post", return_value=resp):
        result = TelegramProvider().send_text(PHONE, "hello")
    assert result.ok is False
    assert result.channel == ""


@override_settings(TELEGRAM_ENABLED=False, TELEGRAM_BOT_TOKEN="tok")
def test_disabled_does_not_send_even_with_optin():
    TelegramContact.objects.create(phone=PHONE, chat_id="555")
    with patch("integrations.telegram.requests.post") as post:
        result = TelegramProvider().send_text(PHONE, "hi")
    assert result.ok is False
    post.assert_not_called()


@override_settings(
    TELEGRAM_ENABLED=True,
    TELEGRAM_BOT_TOKEN="tok",
    MESSAGING_PROVIDER="",
    MESSAGING_CHAIN=[],
    INFOBIP_CHANNEL="viber",
    INFOBIP_SMS_FALLBACK=True,
    INFOBIP_API_KEY="k",
)
def test_enabled_chain_prepends_telegram_and_falls_through_to_viber():
    """Telegram стоит первым; не-opted-in номер само-скипается → выигрывает Viber."""
    chain = _build_messaging_chain()
    classes = [type(p).__name__ for p in chain.providers]
    assert classes[0] == "TelegramProvider"
    assert "ViberProvider" in classes

    with patch("integrations.infobip._InfobipTransport._send_viber", return_value=(True, "vmid")):
        result = chain.send_text(PHONE, "hello")  # PHONE has no TelegramContact

    assert result.ok is True
    assert result.channel == "viber"
    # Telegram попытка зафиксирована как провал перед Viber.
    assert result.attempts[0].channel == "telegram"
    assert result.attempts[0].ok is False
    assert result.attempts[-1].channel == "viber"
    assert result.attempts[-1].ok is True


@override_settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="123456:SECRET-bot_token")
def test_error_log_has_no_bot_token(caplog):
    """JAVI-5: the bot token is in the URL path, and requests repeats the URL in errors."""
    TelegramContact.objects.create(phone=PHONE, chat_id="555")
    url = "https://api.telegram.org/bot123456:SECRET-bot_token/sendMessage"
    error = requests.ConnectionError(f"Max retries exceeded with url: {url}")
    with patch("integrations.telegram.requests.post", side_effect=error):
        assert TelegramProvider().send_text(PHONE, "hello").ok is False
    assert "Telegram send failed: ConnectionError" in caplog.text
    assert "SECRET-bot_token" not in caplog.text
