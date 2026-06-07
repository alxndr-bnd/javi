"""ChainedMessagingProvider — синхронный N-канальный fallback (композиция провайдеров).

Пробует список одно-канальных провайдеров по порядку, возвращает первый успех.
Заменяет хардкод Viber→SMS внутри одного вендора композицией: цепочку собирает фабрика
из настроек (см. integrations/providers.py). Каждая попытка фиксируется в `attempts`.
"""

from __future__ import annotations

from .base import AttemptResult, MessagingProvider, SendResult


class ChainedMessagingProvider(MessagingProvider):
    """Перебирает провайдеров по порядку, останавливается на первом ok=True."""

    def __init__(self, providers: list[MessagingProvider]) -> None:
        self.providers = providers

    def send_text(self, to_e164: str, text: str) -> SendResult:
        attempts: list[AttemptResult] = []
        for provider in self.providers:
            result = provider.send_text(to_e164, text)
            channel = result.channel or _infer_channel(provider)
            attempts.append(
                AttemptResult(
                    channel=channel,
                    ok=result.ok,
                    provider_message_id=result.provider_message_id,
                )
            )
            if result.ok:
                return SendResult(
                    ok=True,
                    provider_message_id=result.provider_message_id,
                    channel=channel,
                    attempts=tuple(attempts),
                )
        # Все попытки провалились.
        return SendResult(ok=False, channel="", attempts=tuple(attempts))


def _infer_channel(provider: MessagingProvider) -> str:
    """Канал провайдера — fallback, если он не вернул channel при сбое.

    Сначала явный атрибут `channel`, затем имя класса (`ViberProvider` → `viber`).
    """
    channel = getattr(provider, "channel", None)
    if channel:
        return channel
    name = type(provider).__name__
    suffix = "Provider"
    if name.endswith(suffix):
        name = name[: -len(suffix)]
    return name.lower()
