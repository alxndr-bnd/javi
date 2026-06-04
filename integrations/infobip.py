"""MessagingProvider поверх Infobip (Viber/SMS)."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import MessagingProvider, SendResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5  # секунд


class InfobipProvider(MessagingProvider):
    """Отправка текста через Infobip. Канал (viber|sms) — из settings."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        sender: str | None = None,
        channel: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or settings.INFOBIP_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.INFOBIP_API_KEY
        self.sender = sender or settings.INFOBIP_SENDER
        self.channel = channel or settings.INFOBIP_CHANNEL
        self.timeout = timeout

    def send_text(self, to_e164: str, text: str) -> SendResult:
        if not self.api_key:
            logger.error("INFOBIP_API_KEY не задан — отправка отключена")
            return SendResult(ok=False)

        to = to_e164.lstrip("+")  # Infobip ожидает номер без «+»
        if self.channel == "sms":
            url = f"{self.base_url}/sms/2/text/advanced"
            payload = {
                "messages": [{"from": self.sender, "destinations": [{"to": to}], "text": text}]
            }
        else:  # viber
            url = f"{self.base_url}/viber/2/messages"
            payload = {
                "messages": [
                    {
                        "sender": self.sender,
                        "destinations": [{"to": to}],
                        "content": {"text": text, "type": "TEXT"},
                    }
                ]
            }

        headers = {
            "Authorization": f"App {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("Infobip send failed: %s", exc)
            return SendResult(ok=False)

        try:
            message_id = data["messages"][0].get("messageId")
        except (KeyError, IndexError, TypeError):
            message_id = None
        return SendResult(ok=True, provider_message_id=message_id)
