"""Отложенные задачи через Cloud Tasks (scheduleTime). Абстракция + Noop + Cloud Tasks."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

# Заголовок с общим секретом колбэков Cloud Tasks (проверяет tasks/views.py).
TASKS_SECRET_HEADER = "X-Tasks-Secret"


class TaskScheduler(ABC):
    @abstractmethod
    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        """Запланировать отправку запроса оценки на run_at (aware-datetime)."""
        raise NotImplementedError

    @abstractmethod
    def schedule_webhook(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        """Поставить HTTP POST на url с телом body и headers (ретраи — на стороне очереди).

        Реализация прода создаёт Cloud Tasks HTTP-задачу, которая шлёт запрос
        НАПРЯМУЮ на url мерчанта (без промежуточного колбэка в Django).
        """
        raise NotImplementedError

    @abstractmethod
    def schedule_escalation(self, delivery_id: int, run_at: datetime) -> None:
        """P4: запланировать проверку доставки на run_at (если не доставлено — следующий канал)."""
        raise NotImplementedError


class NoopTaskScheduler(TaskScheduler):
    """Локальный/дефолтный планировщик: ничего не ставит, только логирует."""

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        logger.info("Noop schedule rating for delivery %s at %s", delivery_id, run_at)

    def schedule_webhook(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        logger.info("Noop schedule webhook to %s (%d bytes)", url, len(body))

    def schedule_escalation(self, delivery_id: int, run_at: datetime) -> None:
        logger.info("Noop schedule escalation for delivery %s at %s", delivery_id, run_at)


class CloudTasksScheduler(TaskScheduler):
    """Cloud Tasks: HTTP-задача POST на колбэк с scheduleTime (lazy-import библиотеки)."""

    def _schedule_post(self, path: str, run_at: datetime) -> None:
        """Создать Cloud Tasks HTTP POST-задачу на наш колбэк `path` с scheduleTime."""
        from google.cloud import tasks_v2  # lazy: нужна только в проде
        from google.protobuf import timestamp_pb2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            settings.CLOUD_TASKS_PROJECT,
            settings.CLOUD_TASKS_LOCATION,
            settings.CLOUD_TASKS_QUEUE,
        )
        # Секрет — в заголовке, не в URL: URL задачи виден в логах запросов и в самой задаче
        # (SERBITO-362, JAVI-3). Cloud Tasks передаёт заголовки http_request как есть.
        url = f"{settings.CLOUD_TASKS_SERVICE_URL.rstrip('/')}{path}"
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(run_at)
        client.create_task(
            request={
                "parent": parent,
                "task": {
                    "http_request": {
                        "http_method": tasks_v2.HttpMethod.POST,
                        "url": url,
                        "headers": {TASKS_SECRET_HEADER: settings.TASKS_SECRET},
                    },
                    "schedule_time": ts,
                },
            }
        )

    def schedule_rating_request(self, delivery_id: int, run_at: datetime) -> None:
        self._schedule_post(f"/tasks/send-rating/{delivery_id}/", run_at)
        logger.info("Scheduled rating for delivery %s at %s", delivery_id, run_at)

    def schedule_escalation(self, delivery_id: int, run_at: datetime) -> None:
        self._schedule_post(f"/tasks/escalate/{delivery_id}/", run_at)
        logger.info("Scheduled escalation for delivery %s at %s", delivery_id, run_at)

    def schedule_webhook(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        from google.cloud import tasks_v2  # lazy: нужна только в проде

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            settings.CLOUD_TASKS_PROJECT,
            settings.CLOUD_TASKS_LOCATION,
            settings.CLOUD_TASKS_QUEUE,
        )
        client.create_task(
            request={
                "parent": parent,
                "task": {
                    "http_request": {
                        "http_method": tasks_v2.HttpMethod.POST,
                        "url": url,
                        "headers": headers,
                        "body": body,
                    },
                },
            }
        )
        logger.info("Scheduled webhook to %s (%d bytes)", url, len(body))


def get_task_scheduler() -> TaskScheduler:
    return import_string(settings.TASK_SCHEDULER)()
