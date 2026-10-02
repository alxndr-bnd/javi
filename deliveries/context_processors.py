"""Контекст-процессоры кабинета."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from integrations.usage import quota_summary
from notifications.quotas import shop_usage


def _row(label, used: int, limit: int) -> dict:
    pct = min(100, round(used * 100 / limit)) if limit > 0 else 100
    return {"label": label, "used": used, "limit": limit, "pct": pct}


def free_quota(request):
    """Лимиты в меню кабинета (SERBITO-356).

    Магазину — его собственные лимиты сообщений (день/месяц, SERBITO-345/357): именно они
    останавливают его отправку. Общий остаток бесплатных квот провайдеров — это расход всей
    платформы, его видит только staff (раньше — каждый магазин).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    ctx = {}
    shop = getattr(user, "shop", None)
    if shop is not None:
        usage = shop_usage(shop)
        ctx["shop_quota"] = {
            "trial": usage["trial"],
            "rows": [
                _row(_("Today"), usage["day_used"], usage["day_limit"]),
                _row(_("This month"), usage["month_used"], usage["month_limit"]),
            ],
        }
    if user.is_staff:
        ctx["free_quota"] = quota_summary()
    return ctx
