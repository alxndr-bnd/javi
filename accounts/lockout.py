"""Brute-force protection for sign-in and the admin (SERBITO-362, JAVI-2).

Failed sign-ins are counted per client IP and per account (email) in fixed windows of
LOGIN_LOCKOUT_MINUTES (common.ratelimit, in the DB). While either count is at its limit the
sign-in is refused before the password is checked — also for a correct password, so guessing
learns nothing. The account limit is higher than the IP one: it stops a guess spread over
many IPs, while one noisy IP cannot lock the owner out on its own for long.

Both the shop sign-in (accounts.forms.LoginForm, with a clear message) and the admin login go
through LockoutBackend, so the admin is covered too.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver

from common import ratelimit
from common.client_ip import client_ip


def _limits(request, username: str | None) -> list[tuple[str, str, int]]:
    checks = []
    if request is not None:
        checks.append(("login-ip", client_ip(request), settings.LOGIN_FAILURE_LIMIT_IP))
    if username:
        checks.append(
            ("login-account", username.strip().lower(), settings.LOGIN_FAILURE_LIMIT_ACCOUNT)
        )
    return checks


def _window_seconds() -> int:
    return settings.LOGIN_LOCKOUT_MINUTES * 60


def is_locked(request, username: str | None) -> bool:
    return any(
        ratelimit.exceeded(scope, ident, limit=limit, window_seconds=_window_seconds())
        for scope, ident, limit in _limits(request, username)
    )


def record_failure(request, username: str | None) -> None:
    for scope, ident, limit in _limits(request, username):
        ratelimit.hit(scope, ident, limit=limit, window_seconds=_window_seconds())


@receiver(user_login_failed)
def _count_failed_login(sender, credentials, request=None, **kwargs):
    if request is None:
        return  # not a web sign-in (e.g. a management command)
    record_failure(request, credentials.get("username") or credentials.get("email"))


class LockoutBackend(ModelBackend):
    """ModelBackend that refuses to check a password while the IP or account is locked."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is not None and is_locked(request, username or kwargs.get("email")):
            raise PermissionDenied("too many failed sign-ins")
        return super().authenticate(request, username=username, password=password, **kwargs)
