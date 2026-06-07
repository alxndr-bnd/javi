"""MessagingProvider'ы поверх Infobip.

Транспорт (auth/_post/_send_viber/_send_sms/webhook-URL) живёт в `_InfobipTransport`
и переиспользуется тонкими ОДНО-канальными провайдерами (`ViberProvider`, `SmsProvider`).
`InfobipProvider` оставлен для обратной совместимости (Viber-first с авто-fallback на SMS);
в проде многоканальный fallback теперь собирает `ChainedMessagingProvider` (см. providers.py).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.urls import reverse

from .base import MessagingProvider, SendResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5  # секунд


class _InfobipTransport:
    """Низкоуровневый транспорт Infobip: auth, POST и сборка Viber/SMS-сообщений.

    Не провайдер сам по себе — общая основа для одно-канальных провайдеров и
    legacy `InfobipProvider`. Конструктор читает настройки так же, как раньше.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        sender: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or settings.INFOBIP_BASE_URL).rstrip("/")
        key = api_key if api_key is not None else settings.INFOBIP_API_KEY
        self.api_key = key.strip()  # ключ идёт в Authorization-заголовок — \n его сломает
        self.sender = sender or settings.INFOBIP_SENDER
        self.timeout = timeout

    # --- низкоуровневые отправки ---

    def _headers(self) -> dict:
        return {
            "Authorization": f"App {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post(self, url: str, payload: dict) -> tuple[bool, str | None]:
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("Infobip send failed (%s): %s", url, exc)
            return False, None
        try:
            return True, data["messages"][0].get("messageId")
        except (KeyError, IndexError, TypeError):
            return True, None

    def _report_url(self) -> str | None:
        """URL нашего вебхука отчётов о доставке (с секретом). None если секрет не задан."""
        secret = settings.INFOBIP_WEBHOOK_SECRET
        if not secret:
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}{reverse('notifications:infobip_reports')}?secret={secret}"

    def _send_viber(self, to: str, text: str) -> tuple[bool, str | None]:
        message = {
            "sender": self.sender,
            "destinations": [{"to": to}],
            "content": {"text": text, "type": "TEXT"},
        }
        url = self._report_url()
        if url:
            # delivery + seen reports → наш вебхук (даёт Isporučeno/Pročitano/Nije dostavljeno).
            message["webhooks"] = {"delivery": {"url": url}, "seen": {"url": url}}
        return self._post(f"{self.base_url}/viber/2/messages", {"messages": [message]})

    def _send_sms(self, to: str, text: str) -> tuple[bool, str | None]:
        message = {"from": self.sender, "destinations": [{"to": to}], "text": text}
        url = self._report_url()
        if url:
            message["notifyUrl"] = url
            message["notifyContentType"] = "application/json"
        return self._post(f"{self.base_url}/sms/2/text/advanced", {"messages": [message]})


class ViberProvider(_InfobipTransport, MessagingProvider):
    """Одно-канальный провайдер: шлёт ТОЛЬКО Viber через Infobip."""

    def send_text(self, to_e164: str, text: str) -> SendResult:
        if not self.api_key:
            logger.error("INFOBIP_API_KEY не задан — отправка отключена")
            return SendResult(ok=False)
        to = to_e164.lstrip("+")  # Infobip ожидает номер без «+»
        ok, mid = self._send_viber(to, text)
        return SendResult(ok=ok, provider_message_id=mid, channel="viber" if ok else "")


class SmsProvider(_InfobipTransport, MessagingProvider):
    """Одно-канальный провайдер: шлёт ТОЛЬКО SMS через Infobip."""

    def send_text(self, to_e164: str, text: str) -> SendResult:
        if not self.api_key:
            logger.error("INFOBIP_API_KEY не задан — отправка отключена")
            return SendResult(ok=False)
        to = to_e164.lstrip("+")  # Infobip ожидает номер без «+»
        ok, mid = self._send_sms(to, text)
        return SendResult(ok=ok, provider_message_id=mid, channel="sms" if ok else "")


class InfobipProvider(_InfobipTransport, MessagingProvider):
    """Legacy: один вендор, синхронный Viber→SMS fallback внутри send_text.

    Оставлен для обратной совместимости. Новый прод-путь — `ChainedMessagingProvider`
    из одно-канальных `ViberProvider`/`SmsProvider` (см. integrations/providers.py).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        sender: str | None = None,
        channel: str | None = None,
        sms_fallback: bool | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(base_url=base_url, api_key=api_key, sender=sender, timeout=timeout)
        self.channel = channel or settings.INFOBIP_CHANNEL
        self.sms_fallback = (
            settings.INFOBIP_SMS_FALLBACK if sms_fallback is None else sms_fallback
        )

    def send_text(self, to_e164: str, text: str) -> SendResult:
        if not self.api_key:
            logger.error("INFOBIP_API_KEY не задан — отправка отключена")
            return SendResult(ok=False)

        to = to_e164.lstrip("+")  # Infobip ожидает номер без «+»

        # Прямой SMS, если Viber Business ещё не подключён.
        if self.channel == "sms":
            ok, mid = self._send_sms(to, text)
            return SendResult(ok=ok, provider_message_id=mid, channel="sms" if ok else "")

        # Viber-first.
        ok, mid = self._send_viber(to, text)
        if ok:
            return SendResult(ok=True, provider_message_id=mid, channel="viber")

        # Fallback на SMS при сбое Viber.
        if self.sms_fallback:
            logger.info("Viber send failed — fallback to SMS")
            ok, mid = self._send_sms(to, text)
            if ok:
                return SendResult(ok=True, provider_message_id=mid, channel="sms")
        return SendResult(ok=False)
