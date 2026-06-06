"""Исходящие вебхуки мерчанту (Javi → магазин).

Дизайн (выбран простейший корректный вариант):
- `notify_merchant(shop, event, payload)` собирает JSON-конверт `{event, data, sent_at}`,
  считает HMAC-SHA256 подпись над СЫРЫМ телом и ставит в очередь HTTP POST.
- Доставка — через абстракцию `TaskScheduler.schedule_webhook(...)`. В проде это
  Cloud Tasks HTTP-задача, которая шлёт POST **напрямую** на `shop.webhook_url`
  (без промежуточного колбэка в Django). Ретраи/бэкофф обеспечивает очередь.
- Локально/в тестах — Noop (ничего не уходит), что держит сеть вне тестов.
- Любой сбой постановки в очередь подавляется и логируется — основной поток не рвём.

Верификация на стороне мерчанта: пересчитать `hmac_sha256(webhook_secret, raw_body)`
и сравнить с заголовком `Javi-Signature: sha256=<hex>` (constant-time).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.utils import timezone

from tasks.scheduler import get_task_scheduler

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "Javi-Signature"


def compute_signature(secret: str, raw_body: bytes) -> str:
    """`sha256=<hex>` — HMAC-SHA256 тела с секретом магазина (паттерн AfterShip)."""
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def notify_merchant(shop, event: str, payload: dict) -> None:
    """Поставить в очередь подписанный вебхук мерчанту, если у магазина настроен webhook_url.

    Никогда не бросает: сбой постановки логируется и подавляется (основной поток важнее).
    """
    webhook_url = getattr(shop, "webhook_url", "")
    if not webhook_url:
        return
    try:
        body = json.dumps(
            {"event": event, "data": payload, "sent_at": timezone.now().isoformat()},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: compute_signature(shop.webhook_secret or "", body),
        }
        get_task_scheduler().schedule_webhook(webhook_url, body, headers)
    except Exception:
        logger.exception(
            "failed to enqueue webhook %s for shop %s", event, getattr(shop, "id", "?")
        )
