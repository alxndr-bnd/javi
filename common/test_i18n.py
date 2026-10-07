"""SERBITO-356 (5b): Serbian is served as sr-latn, so Django's own messages are Latin too."""

import pytest
from django.contrib.auth import get_user_model

from common.i18n import html_lang, supported_language
from deliveries.models import Shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop_client(client):
    user = get_user_model().objects.create_user(email="i18n@shop.rs", password="pass12345")
    Shop.objects.create(owner=user, name="Pekara", origin_lat=44.8, origin_lng=20.4)
    client.force_login(user)
    return client


@pytest.mark.parametrize("accept", ["sr", "sr-RS", "sr-Latn-RS", "sr-Latn"])
def test_serbian_browser_gets_latin_django_errors(shop_client, accept):
    """Django's own validation text ("This field is required.") is Latin, not Cyrillic."""
    resp = shop_client.post("/app/dostava/nova/", {}, HTTP_ACCEPT_LANGUAGE=accept)
    body = resp.content.decode()
    assert "Ovo polje se mora popuniti." in body
    assert "Ово поље" not in body
    assert '<html lang="sr-Latn">' in body


def test_old_sr_cookie_still_selects_serbian(shop_client, settings):
    shop_client.cookies[settings.LANGUAGE_COOKIE_NAME] = "sr"
    body = shop_client.get("/app/").content.decode()
    assert '<html lang="sr-Latn">' in body


def test_language_switch_posts_sr_latn(shop_client):
    body = shop_client.get("/app/").content.decode()
    assert 'name="language" value="sr-latn"' in body
    resp = shop_client.post("/i18n/setlang/", {"language": "sr-latn", "next": "/app/"})
    assert resp.status_code == 302
    assert '<html lang="sr-Latn">' in shop_client.get("/app/").content.decode()


@pytest.mark.parametrize(
    "code, tag", [("sr-latn", "sr-Latn"), ("en", "en"), (None, "en"), ("en-gb", "en-gb")]
)
def test_html_lang(code, tag):
    assert html_lang(code) == tag


@pytest.mark.parametrize(
    "code, expected",
    [
        ("sr", "sr-latn"),
        ("sr-RS", "sr-latn"),
        ("sr-Latn", "sr-latn"),
        ("en", "en"),
        ("ru", "sr-latn"),
        ("", "sr-latn"),
        (None, "sr-latn"),
    ],
)
def test_supported_language(code, expected):
    assert supported_language(code) == expected
