from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from common.testing import parse_html
from deliveries.models import Delivery, Shop, TrackingToken

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _token(status=Delivery.Status.ON_THE_WAY, *, eta_minutes=20, city="Beograd", language="en"):
    user = get_user_model().objects.create_user(email="t@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pizza Napoli")
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Tajna adresa 5, Beograd",
        dest_city=city,
        recipient_language=language,
        status=status,
        eta_at=timezone.now() + timedelta(minutes=eta_minutes) if eta_minutes else None,
    )
    return TrackingToken.objects.create(delivery=delivery)


def test_on_the_way_shows_eta_city_no_private_data(client):
    """AC#1/#3: статус U dostavi → ETA + город; без телефона/полного адреса."""
    token = _token(Delivery.Status.ON_THE_WAY)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "Pizza Napoli" in body
    assert "Arriving approximately by" in body
    assert "Beograd" in body
    # степпер всегда рендерится целиком
    assert "Received" in body and "In delivery" in body and "Delivered" in body
    assert "+381641234567" not in body
    assert "Tajna adresa" not in body


def test_created_step_primljeno(client):
    token = _token(Delivery.Status.CREATED, eta_minutes=0)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "Your order has been received" in body


def test_delivered_step(client):
    token = _token(Delivery.Status.DELIVERED, eta_minutes=0)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "has been delivered" in body
    # терминальный статус: все шаги завершены (✓), нет «текущего» (●)
    assert "step--active" not in body
    assert body.count("step--done") == 3


def test_on_the_way_step_has_active(client):
    token = _token(Delivery.Status.ON_THE_WAY)
    body = client.get(f"/t/{token.token}/").content.decode()
    assert "step--active" in body  # U dostavi — текущий


def test_expired_link_410(client):
    token = _token()
    token.expires_at = timezone.now() - timedelta(hours=1)
    token.save()
    resp = client.get(f"/t/{token.token}/")
    assert resp.status_code == 410
    assert "expired" in resp.content.decode()


def test_rating_capture_and_thanks(client):
    """AC#4: тап звезды → Rating, страница показывает «Hvala!»; AC#5 — без дублей."""
    token = _token(Delivery.Status.DELIVERED)
    url = f"/t/{token.token}/"
    # до оценки — видны звёзды
    assert "How did the delivery go" in client.get(url).content.decode()
    # ставим оценку
    resp = client.post(f"{url}oceni/", {"value": "5"})
    assert resp.status_code == 302
    token.delivery.refresh_from_db()
    assert token.delivery.rating.value == 5
    # после оценки — «Hvala!», звёзд нет
    body = client.get(url).content.decode()
    assert "Thank you" in body
    assert "How did the delivery go" not in body
    # повтор не плодит дубли (обновляет)
    client.post(f"{url}oceni/", {"value": "3"})
    token.delivery.refresh_from_db()
    assert token.delivery.rating.value == 3


def test_rating_invalid_value_ignored(client):
    from deliveries.models import Rating

    token = _token(Delivery.Status.DELIVERED)
    client.post(f"/t/{token.token}/oceni/", {"value": "9"})
    assert Rating.objects.count() == 0


def test_recipient_can_mark_received(client):
    """Получатель подтверждает получение → статус delivered, появляется блок оценки."""
    token = _token(Delivery.Status.ON_THE_WAY)
    url = f"/t/{token.token}/"
    assert "Confirm receipt of the order" in client.get(url).content.decode()
    resp = client.post(f"{url}primljeno/")
    assert resp.status_code == 302
    token.delivery.refresh_from_db()
    assert token.delivery.status == Delivery.Status.DELIVERED
    body = client.get(url).content.decode()
    assert "has been delivered" in body
    assert "Confirm receipt of the order" not in body
    assert "How did the delivery go" in body  # оценку всё ещё можно поставить


def test_unsubscribe_adds_to_blocklist(client):
    """AC#1: ссылка отписки → подтверждение → POST → OptOut + «Odjavljeni ste»."""
    from notifications.models import OptOut

    token = _token(Delivery.Status.ON_THE_WAY)
    resp = client.post(f"/t/{token.token}/odjava/")
    assert resp.status_code == 200
    assert "You have been unsubscribed" in resp.content.decode()
    assert OptOut.objects.filter(phone=token.delivery.recipient_phone).exists()


def test_unsubscribe_get_only_asks_for_confirmation(client):
    """JAVI-9: GET (link previews, scanners) changes nothing; it shows a POST form."""
    from notifications.models import OptOut

    token = _token(Delivery.Status.ON_THE_WAY)
    resp = client.get(f"/t/{token.token}/odjava/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Unsubscribe from notifications?" in body
    assert f'<form method="post" action="/t/{token.token}/odjava/"' in body
    assert "You have been unsubscribed" not in body
    assert not OptOut.objects.exists()


def test_unsubscribe_expired_token_is_gone(client):
    from notifications.models import OptOut

    token = _token()
    token.expires_at = timezone.now() - timedelta(minutes=1)
    token.save()
    assert client.post(f"/t/{token.token}/odjava/").status_code == 410
    assert not OptOut.objects.exists()


@override_settings(TRACKING_RATE_LIMIT=2)
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("get", ""),
        ("post", "oceni/"),
        ("post", "primljeno/"),
        ("get", "odjava/"),
        ("post", "odjava/"),
    ],
)
def test_rate_limit_covers_every_tracking_endpoint(client, method, suffix):
    """JAVI-8: the limit applies to all /t/ endpoints, not just the status page."""
    token = _token()
    url = f"/t/{token.token}/{suffix}"
    call = getattr(client, method)
    assert call(url, REMOTE_ADDR="9.9.9.9").status_code != 429
    assert call(url, REMOTE_ADDR="9.9.9.9").status_code != 429
    assert call(url, REMOTE_ADDR="9.9.9.9").status_code == 429


@override_settings(TRACKING_RATE_LIMIT=2)
def test_rate_limit_keys_on_real_client_ip_not_spoofed_xff(client):
    """JAVI-8: behind Cloud Run REMOTE_ADDR is the front end; a forged leftmost XFF entry
    must not buy a fresh bucket, and different real clients have their own buckets."""
    token = _token()
    url = f"/t/{token.token}/"
    front_end = {"REMOTE_ADDR": "169.254.1.1"}
    for spoof in ("1.1.1.1", "2.2.2.2"):
        xff = f"{spoof}, 203.0.113.7"
        assert client.get(url, HTTP_X_FORWARDED_FOR=xff, **front_end).status_code == 200
    xff = "3.3.3.3, 203.0.113.7"
    assert client.get(url, HTTP_X_FORWARDED_FOR=xff, **front_end).status_code == 429
    other = "203.0.113.8"
    assert client.get(url, HTTP_X_FORWARDED_FOR=other, **front_end).status_code == 200


# --- /t/ is private to the recipient (SERBITO-303, -306, -321): noindex, no GA, no consent
# banner or settings — whatever state the link is in ---

NOINDEX = "noindex, nofollow"
META_NOINDEX = '<meta name="robots" content="noindex, nofollow">'
NOT_ON_TRACKING = [
    *("googletagmanager.com", "google-analytics.com", "gtag(", "G-KHME7DK2K0"),
    *("consent.js", "data-consent-open", "Cookie settings"),
]


@pytest.mark.parametrize(
    ("state", "suffix", "status"),
    [
        ("live", "", 200),
        ("live", "odjava/", 200),
        ("expired", "", 410),
        ("unknown", "", 404),
        ("unknown", "odjava/", 404),
        ("unknown", None, 301),  # no trailing slash
    ],
)
def test_tracking_pages_stay_private(client, state, suffix, status):
    token = _token()
    if state == "expired":
        token.expires_at = timezone.now() - timedelta(days=1)
        token.save(update_fields=["expires_at"])
    key = "unknown-token" if state == "unknown" else token.token
    resp = client.get(f"/t/{key}" if suffix is None else f"/t/{key}/{suffix}")
    assert resp.status_code == status
    assert resp.headers["X-Robots-Tag"] == NOINDEX
    body = b"".join(resp.streaming_content) if resp.streaming else resp.content
    for marker in NOT_ON_TRACKING:
        assert marker not in body.decode(), marker
    if state != "unknown" and suffix == "":
        assert META_NOINDEX in body.decode()


# --- screen readers and keyboard (SERBITO-352): an h1 in <main>, a real list of steps whose
# state is spoken, and rating stars that Tab through left to right in a labelled group ---

APP_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "app.css"


def _tree(resp):
    return parse_html(resp.content.decode())


def _single_h1_in_main(root):
    h1s = root.find_all("h1")
    assert len(h1s) == 1, [h.text() for h in h1s]
    assert root.find("main") in h1s[0].ancestors()
    return h1s[0].text()


@pytest.mark.parametrize(
    ("status", "lang", "title", "spoken"),
    [
        ("created", "en", "Your order has been received", ["in progress", "not yet", "not yet"]),
        ("on_the_way", "en", "Your order is on its way", ["completed", "in progress", "not yet"]),
        ("delivered", "en", "Your order has been delivered", ["completed"] * 3),
        ("on_the_way", "sr", None, ["završeno", "u toku", "predstoji"]),
    ],
)
def test_status_page_structure_for_screen_readers(client, status, lang, title, spoken):
    token = _token(status, language="sr-latn" if lang == "sr" else lang)
    root = _tree(client.get(f"/t/{token.token}/"))
    h1 = _single_h1_in_main(root)
    assert title is None or h1 == title
    steps = root.find("ol", {"role": "list"})
    assert "stepper" in steps.classes() and steps.attrs.get("aria-label")
    items = steps.find_all("li")
    order = ["created", "on_the_way", "delivered"]
    assert [li.attrs.get("aria-current") for li in items] == [
        "step" if s == status else None for s in order
    ]
    assert [li.find("span", {"class": "sr-only"}).text() for li in items] == [
        f", {word}" for word in spoken
    ]


def test_rating_stars_tab_left_to_right_in_a_labelled_group(client):
    token = _token(Delivery.Status.DELIVERED)
    root = _tree(client.get(f"/t/{token.token}/"))
    group = root.find("form", {"role": "group"})
    assert "stars" in group.classes()
    label = root.find(attrs={"id": group.attrs["aria-labelledby"]})
    assert label.tag == "h2" and label.text() == "How did the delivery go?"
    hint = root.find(attrs={"id": group.attrs["aria-describedby"]})
    assert hint.text().startswith("Tap the stars to rate")
    stars = group.find_all("button")
    assert [b.attrs["value"] for b in stars] == ["1", "2", "3", "4", "5"]
    assert [b.attrs["aria-label"] for b in stars] == [f"Rating {n} of 5" for n in range(1, 6)]
    # DOM order is the visual order: the row is not reversed in CSS
    css = APP_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".stars{") :]
    assert "row-reverse" not in rule[: rule.index("}")]


@pytest.mark.parametrize(
    ("method", "suffix", "expire", "title"),
    [
        ("get", "", True, "This tracking link has expired."),
        ("get", "odjava/", False, "Unsubscribe from notifications?"),
        ("post", "odjava/", False, "You have been unsubscribed."),
    ],
)
def test_other_tracking_pages_have_h1_in_main(client, method, suffix, expire, title):
    token = _token()
    if expire:
        token.expires_at = timezone.now() - timedelta(hours=1)
        token.save(update_fields=["expires_at"])
    resp = getattr(client, method)(f"/t/{token.token}/{suffix}")
    assert _single_h1_in_main(_tree(resp)) == title
