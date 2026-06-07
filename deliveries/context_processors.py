"""Контекст-процессоры кабинета."""

from __future__ import annotations

from integrations.usage import quota_summary


def free_quota(request):
    """Глобальный остаток бесплатных квот — только залогиненным (read-only)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"free_quota": quota_summary()}
