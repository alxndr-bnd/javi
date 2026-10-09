"""SERBITO-595: the request funnel is measured — landing → sign-up form → sign-up → active shop.

- The server counts browser views of "/", "/en/", "/ru/" and opens of the registration form per
  day (FunnelCount). Bots, link previews, deploy checks (curl), prefetches, HEAD and errors are
  not counted. A failing count never breaks the page.
- Sign-ups and activated shops come from Shop / Delivery, so their history is there already.
- GA4 gets the same steps as events: landing_view, cta_click, lead_submit (landing),
  signup_start (registration form) and signup_complete (once, on the page after sign-up).
- `manage.py funnel_report` prints weekly counts, never names, e-mails or phones.
"""

import datetime
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from common import funnel
from common.models import FunnelCount
from common.testing import LANDING_PAGES
from deliveries.models import Delivery, Shop

pytestmark = pytest.mark.django_db

BROWSER = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
BOTS = [
    "",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "facebookexternalhit/1.1",
    "Viber/22.0 link preview",
    "curl/8.7.1",
    "python-requests/2.32",
    "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/131.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; moto g power (2022)) Chrome-Lighthouse",
]


@pytest.fixture(autouse=True)
def _counting(settings):
    settings.FUNNEL_COUNTING = True
    cache.clear()  # the sign-up rate limiter lives in the cache


def _counts(event):
    return {r.lang: r.count for r in FunnelCount.objects.filter(event=event)}


# --- landing views ---


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_browser_landing_view_is_counted_per_language(client, lang):
    path = LANDING_PAGES[lang][0]
    for _ in range(2):
        assert client.get(path, HTTP_USER_AGENT=BROWSER).status_code == 200
    assert _counts(funnel.LANDING_VIEW) == {lang: 2}
    assert FunnelCount.objects.get().day == timezone.localdate()


@pytest.mark.parametrize("ua", BOTS)
def test_bots_and_checks_are_not_counted(client, ua):
    assert client.get("/", HTTP_USER_AGENT=ua).status_code == 200
    assert FunnelCount.objects.count() == 0


def test_prefetch_head_and_other_paths_are_not_counted(client):
    client.get("/", HTTP_USER_AGENT=BROWSER, HTTP_SEC_PURPOSE="prefetch")
    client.head("/", HTTP_USER_AGENT=BROWSER)
    client.get("/privacy.html", HTTP_USER_AGENT=BROWSER)
    client.get("/no-such-page/", HTTP_USER_AGENT=BROWSER)
    client.get("/?utm_source=x", HTTP_USER_AGENT=BROWSER)  # a UTM visit is still a view of "/"
    assert _counts(funnel.LANDING_VIEW) == {"sr": 1}


def test_counting_off_by_setting(client, settings):
    settings.FUNNEL_COUNTING = False
    client.get("/", HTTP_USER_AGENT=BROWSER)
    assert FunnelCount.objects.count() == 0


def test_a_failing_count_never_breaks_the_page(client, caplog):
    with mock.patch.object(FunnelCount.objects, "filter", side_effect=RuntimeError("db down")):
        resp = client.get("/", HTTP_USER_AGENT=BROWSER)
    assert resp.status_code == 200
    assert "Funnel count failed" in caplog.text


def test_landing_sends_ga4_funnel_events():
    for _lang, (_path, file) in LANDING_PAGES.items():
        html = file.read_text(encoding="utf-8")
        for event in ("landing_view", "cta_click", "lead_submit"):
            assert f"track('{event}'" in html, event
        assert "gtag('event', name" in html
        # Once per page: a second copy of the script sent every view and CTA click twice.
        assert html.count("track('landing_view');") == 1
        assert html.count("function track(") == 1


# --- registration form and sign-up ---


def _register(client):
    return client.post(
        reverse("accounts:register"),
        {
            "email": "funnel@shop.rs",
            "store_name": "Funnel Shop",
            "password1": "s3cret-pass-9",
            "password2": "s3cret-pass-9",
        },
        HTTP_USER_AGENT=BROWSER,
    )


def test_opening_the_registration_form_is_counted(client):
    resp = client.get(reverse("accounts:register"), HTTP_USER_AGENT=BROWSER)
    assert resp.status_code == 200
    client.get(reverse("accounts:register"), HTTP_USER_AGENT="Googlebot/2.1")
    assert _counts(funnel.SIGNUP_START) == {"en": 1}
    _register(client)  # a POST is not another form open
    assert _counts(funnel.SIGNUP_START) == {"en": 1}


def test_registration_page_shows_the_trial_and_sends_signup_start(client):
    body = client.get(reverse("accounts:register"), HTTP_USER_AGENT=BROWSER).content.decode()
    assert "30 days free, then 30 € per month" in body
    assert "After the 30 days, payment is required to continue." in body
    assert "soon" not in body
    assert "gtag('event', 'signup_start');" in body
    invalid = client.post(reverse("accounts:register"), {"email": "x"}, HTTP_USER_AGENT=BROWSER)
    assert invalid.status_code == 200  # the form again, with errors: not another start
    assert "signup_start" not in invalid.content.decode()
    client.cookies["django_language"] = "sr-latn"
    body = client.get(reverse("accounts:register"), HTTP_USER_AGENT=BROWSER).content.decode()
    assert "30 dana besplatno, zatim 30 € mesečno" in body
    assert "Posle 30 dana za nastavak je potrebno plaćanje." in body


def test_signup_complete_reaches_ga4_once_after_sign_up(client):
    resp = _register(client)
    assert resp.status_code == 302
    first = client.get(resp.url, HTTP_USER_AGENT=BROWSER).content.decode()
    assert "gtag('event', 'signup_complete');" in first
    again = client.get(resp.url, HTTP_USER_AGENT=BROWSER).content.decode()
    assert "signup_complete" not in again


def test_tracking_pages_never_get_funnel_events(client):
    """Customer pages (/t/<token>/) drop the whole analytics block (SERBITO-306)."""
    _register(client)
    shop = Shop.objects.get()
    delivery = Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_address="A 1"
    )
    from deliveries.models import TrackingToken

    token = TrackingToken.objects.create(delivery=delivery)
    body = client.get(f"/t/{token.token}/", HTTP_USER_AGENT=BROWSER)
    assert b"signup_complete" not in body.content
    assert b"gtag(" not in body.content


# --- weekly report ---

TODAY = datetime.date(2026, 10, 14)  # a Wednesday


def _shop(email, created):
    user = get_user_model().objects.create_user(email=email, password="pass12345")
    shop = Shop.objects.create(owner=user, name=f"Shop {email}")
    Shop.objects.filter(pk=shop.pk).update(created_at=created)
    return shop


def _at(day, hour=12):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour)))


def _delivery(shop, started):
    return Delivery.objects.create(
        shop=shop,
        recipient_name="Secret Recipient",
        recipient_phone="+381641234567",
        dest_address="Tajna 1, Beograd",
        started_at=started,
    )


@pytest.fixture
def history():
    this_monday = datetime.date(2026, 10, 12)
    last_monday = datetime.date(2026, 10, 5)
    FunnelCount.objects.create(day=last_monday, event="landing_view", lang="sr", count=40)
    FunnelCount.objects.create(day=last_monday, event="landing_view", lang="en", count=10)
    FunnelCount.objects.create(day=last_monday, event="signup_start", lang="en", count=6)
    FunnelCount.objects.create(day=this_monday, event="landing_view", lang="ru", count=7)
    a = _shop("a@secret.rs", _at(last_monday))
    b = _shop("b@secret.rs", _at(last_monday + datetime.timedelta(days=6), 23))  # Sunday night
    c = _shop("c@secret.rs", _at(this_monday))
    _delivery(a, _at(last_monday + datetime.timedelta(days=1)))
    _delivery(a, _at(this_monday))  # a second delivery does not activate the shop again
    _delivery(c, _at(this_monday + datetime.timedelta(days=1)))
    _delivery(b, None)  # added, never started: not active
    return last_monday, this_monday


def test_weekly_counts(history):
    last_monday, this_monday = history
    weeks = funnel.weekly(3, today=TODAY)
    assert [w.start for w in weeks] == [
        last_monday - datetime.timedelta(weeks=1),
        last_monday,
        this_monday,
    ]
    last, this = weeks[1], weeks[2]
    assert (last.landing_view, last.signup_start, last.signup_complete, last.shop_activated) == (
        50,
        6,
        2,
        1,
    )
    assert (this.landing_view, this.signup_start, this.signup_complete, this.shop_activated) == (
        7,
        0,
        1,
        1,
    )
    assert last.view_to_signup == "4.0%"
    assert weeks[0].view_to_signup == "-"


def test_report_prints_counts_only_and_changes_nothing(history):
    before = (FunnelCount.objects.count(), Shop.objects.count(), Delivery.objects.count())
    out = StringIO()
    with mock.patch("common.funnel.timezone.localdate", return_value=TODAY):
        call_command("funnel_report", "--weeks", "2", stdout=out)
    text = out.getvalue()
    assert "2026-10-05 .. 2026-10-11" in text
    assert "2026-10-12 .. 2026-10-18" in text
    for secret in ("secret.rs", "Shop ", "Secret Recipient", "+38164", "Tajna"):
        assert secret not in text
    assert (FunnelCount.objects.count(), Shop.objects.count(), Delivery.objects.count()) == before
