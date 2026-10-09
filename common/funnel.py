"""Request funnel counts (SERBITO-595): landing → sign-up form → sign-up → active shop.

Steps and where each number comes from:

- ``landing_view``: a GET of ``/``, ``/en/`` or ``/ru/`` that answered 200, by a browser (not a
  bot, not a prefetch). Counted per day and page language in ``FunnelCount``.
- ``signup_start``: a GET of the registration form, counted the same way (language = app language).
- ``signup_complete``: a new ``Shop`` (``Shop.created_at``). History is in the table already.
- ``shop_activated``: a shop's first delivery that started (``Delivery.started_at``): the first
  Viber/SMS to a customer. History is in the table already.

Nothing here stores or prints personal data: only dates, step names, languages and counts.
GA4 gets the same step names as events from the pages (plus ``cta_click`` and ``lead_submit``,
which the server cannot see); GA4 needs consent, so these counts are the ones to compare.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Min, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

LANDING_VIEW = "landing_view"
SIGNUP_START = "signup_start"
COUNTED_EVENTS = (LANDING_VIEW, SIGNUP_START)

# Landing path -> page language (SERBITO-459: one static page per language).
LANDING_PATHS = {"/": "sr", "/en/": "en", "/ru/": "ru"}

# Crawlers, link previews, uptime and deploy checks, HTTP libraries. A browser UA has none of these.
_BOT_UA = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|lighthouse|headless|curl|wget|"
    r"python|go-http|java/|okhttp|axios|node-fetch|uptime|monitor|pingdom|scan|http-client",
    re.IGNORECASE,
)


def is_human(request) -> bool:
    """A browser page view: a user agent that is not a known bot and not a prefetch."""
    ua = request.headers.get("User-Agent", "")
    if not ua or _BOT_UA.search(ua):
        return False
    purpose = request.headers.get("Sec-Purpose", "") + request.headers.get("Purpose", "")
    return "prefetch" not in purpose.lower()


def record(event: str, lang: str = "", day: datetime.date | None = None) -> None:
    """Add 1 to today's count of ``event``. Never raises: a count must not break a page."""
    if not settings.FUNNEL_COUNTING:
        return
    from common.models import FunnelCount

    day = day or timezone.localdate()
    try:
        updated = FunnelCount.objects.filter(day=day, event=event, lang=lang).update(
            count=F("count") + 1
        )
        if not updated:
            try:
                with transaction.atomic():
                    FunnelCount.objects.create(day=day, event=event, lang=lang, count=1)
            except IntegrityError:  # another request created the row first
                FunnelCount.objects.filter(day=day, event=event, lang=lang).update(
                    count=F("count") + 1
                )
    except Exception:  # the page matters more than the count
        logger.warning("Funnel count failed", exc_info=True, extra={"event": "funnel.count"})


class LandingViewMiddleware:
    """Counts landing page views. Sits before WhiteNoise, which answers the landing itself."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        lang = LANDING_PATHS.get(request.path)
        if lang and request.method == "GET" and response.status_code == 200 and is_human(request):
            record(LANDING_VIEW, lang)
        return response


# --- weekly report (manage.py funnel_report) ---


@dataclass
class Week:
    start: datetime.date  # Monday
    landing_view: int = 0
    signup_start: int = 0
    signup_complete: int = 0
    shop_activated: int = 0

    @property
    def end(self) -> datetime.date:
        return self.start + datetime.timedelta(days=6)

    @property
    def view_to_signup(self) -> str:
        if not self.landing_view:
            return "-"
        return f"{self.signup_complete * 100 / self.landing_view:.1f}%"


def monday(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def weekly(weeks: int, today: datetime.date | None = None) -> list[Week]:
    """The last ``weeks`` ISO weeks (Monday to Sunday), the current one last."""
    from common.models import FunnelCount
    from deliveries.models import Delivery, Shop

    today = today or timezone.localdate()
    first = monday(today) - datetime.timedelta(weeks=weeks - 1)
    rows = {
        first + datetime.timedelta(weeks=i): Week(first + datetime.timedelta(weeks=i))
        for i in range(weeks)
    }

    def bucket(day: datetime.date) -> Week | None:
        return rows.get(monday(day))

    counts = (
        FunnelCount.objects.filter(day__gte=first, event__in=COUNTED_EVENTS)
        .values("day", "event")
        .annotate(n=Sum("count"))
    )
    for row in counts:
        week = bucket(row["day"])
        if week:
            setattr(week, row["event"], getattr(week, row["event"]) + row["n"])

    tz = timezone.get_current_timezone()
    for created in Shop.objects.filter(
        created_at__date__gte=first - datetime.timedelta(days=1)
    ).values_list("created_at", flat=True):
        week = bucket(timezone.localtime(created, tz).date())
        if week:
            week.signup_complete += 1

    firsts = (
        Delivery.objects.filter(started_at__isnull=False)
        .values("shop")
        .annotate(first=Min("started_at"))
        .values_list("first", flat=True)
    )
    for started in firsts:
        week = bucket(timezone.localtime(started, tz).date())
        if week:
            week.shop_activated += 1

    return list(rows.values())


# --- one-off GA4 events after a redirect ---

SESSION_GA_EVENTS = "ga_events"
GA_EVENT_NAMES = frozenset({"signup_complete"})


def queue_ga_event(request, name: str) -> None:
    """Send GA4 event ``name`` on the next page this session renders (base.html)."""
    events = request.session.get(SESSION_GA_EVENTS, [])
    if name in GA_EVENT_NAMES and name not in events:
        request.session[SESSION_GA_EVENTS] = [*events, name]


def ga_events(request):
    """Context processor: the queued GA4 events, removed from the session once rendered."""
    session = getattr(request, "session", None)
    if session is None or SESSION_GA_EVENTS not in session:
        return {}
    events = [e for e in session.pop(SESSION_GA_EVENTS) if e in GA_EVENT_NAMES]
    return {"ga_events": events}
