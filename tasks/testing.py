"""Фейк-планировщик для тестов: записывает запланированные задачи вместо Cloud Tasks."""

from __future__ import annotations

from datetime import datetime

from .scheduler import TaskScheduler


class RecordingTaskScheduler(TaskScheduler):
    scheduled: list[tuple[int, datetime]] = []

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        type(self).scheduled.append((delivery_id, run_at))


class FailingTaskScheduler(TaskScheduler):
    """Имитирует сбой постановки задачи (напр. недоступность Cloud Tasks)."""

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        raise RuntimeError("cloud tasks unavailable")
