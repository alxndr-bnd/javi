from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        from . import lockout  # noqa: F401 — registers the failed-sign-in counter
