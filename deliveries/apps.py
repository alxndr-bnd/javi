from django.apps import AppConfig


class DeliveriesConfig(AppConfig):
    name = "deliveries"

    def ready(self):
        # SERBITO-467: a wrong retention config must stop the start, not erase data too early.
        from .retention import validate_retention_settings

        validate_retention_settings()
