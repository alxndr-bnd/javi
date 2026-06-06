"""Фейк-планировщики для тестов: записывают задачи/вебхуки вместо Cloud Tasks."""

from __future__ import annotations

from datetime import datetime

from .scheduler import TaskScheduler


class RecordingTaskScheduler(TaskScheduler):
    scheduled: list[tuple[int, datetime]] = []

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        type(self).scheduled.append((delivery_id, run_at))

    def schedule_webhook(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        RecordingWebhookScheduler.webhooks.append(
            {"url": url, "body": body, "headers": headers}
        )


class RecordingWebhookScheduler(TaskScheduler):
    """Записывает поставленные исходящие вебхуки (url/body/headers) для проверок."""

    webhooks: list[dict] = []

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        RecordingTaskScheduler.scheduled.append((delivery_id, run_at))

    def schedule_webhook(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        type(self).webhooks.append({"url": url, "body": body, "headers": headers})


class FailingTaskScheduler(TaskScheduler):
    """Имитирует сбой постановки задачи (напр. недоступность Cloud Tasks)."""

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        raise RuntimeError("cloud tasks unavailable")

    def schedule_webhook(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        raise RuntimeError("cloud tasks unavailable")
