"""TelegramProvider — opt-in-only канал поверх Telegram Bot API.

Ключевое ограничение: бот НЕ может писать пользователю, который не нажал /start.
Поэтому Telegram работает только для получателей, чей chat_id мы сохранили при
opt-in (см. notifications.models.TelegramContact + вебхук бота). Если номер не
opted-in — провайдер само-скипается (ok=False БЕЗ сетевого вызова), что позволяет
ставить его ПЕРВЫМ в цепочке: для всех остальных он безвредно проваливается дальше
на Viber.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from common.redact import describe_request_error

from .base import MessagingProvider, SendResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5  # секунд


class TelegramProvider(MessagingProvider):
    """Одно-канальный провайдер Telegram. Шлёт только тем, кто сделал opt-in (/start)."""

    channel = "telegram"

    def __init__(
        self,
        bot_token: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.bot_token = bot_token if bot_token is not None else settings.TELEGRAM_BOT_TOKEN
        self.timeout = timeout

    def send_text(self, to_e164: str, text: str) -> SendResult:
        from notifications.models import TelegramContact

        contact = TelegramContact.objects.filter(phone=to_e164).first()
        if contact is None:
            # Само-скип: нет opt-in → никакого сетевого вызова, тихо проваливаемся дальше.
            return SendResult(ok=False, channel="")

        if not getattr(settings, "TELEGRAM_ENABLED", False) or not self.bot_token:
            logger.error("TELEGRAM_ENABLED off или TELEGRAM_BOT_TOKEN не задан — отправка off")
            return SendResult(ok=False, channel="")

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": contact.chat_id, "text": text}
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            # Текст исключения requests содержит URL, а в нём токен бота (JAVI-5).
            logger.error("Telegram send failed: %s", describe_request_error(exc))
            return SendResult(ok=False, channel="")

        if not data.get("ok"):
            logger.error("Telegram API вернул ok=false: %s", data.get("description"))
            return SendResult(ok=False, channel="")

        mid = (data.get("result") or {}).get("message_id")
        return SendResult(
            ok=True,
            provider_message_id=str(mid) if mid is not None else None,
            channel="telegram",
        )
