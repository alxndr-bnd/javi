"""SERBITO-265: the "Other projects" cross-promo lives only on the public landing.

The landing is static (WhiteNoise serves landing/ at the site root), so the block sits in each
language page (landing/index.html, landing/en/, landing/ru/; SERBITO-459) in that language. The
shop dashboard and the customer tracking page belong to the shop and its customers — no
cross-promo there.
"""

import json
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model

from common.testing import LANDING_PAGES
from deliveries.models import Delivery, Shop, TrackingToken

pytestmark = pytest.mark.django_db

UTM = "?utm_source=javi&utm_medium=crosspromo&utm_campaign=footer"
PRODUCTS = [
    "https://gtd.serbito.rs/",
    "https://poker.serbito.rs/",
    "https://serbito.rs/",
]
MADE_BY = "https://www.linkedin.com/company/nohandoff/"
LANGS = list(LANDING_PAGES)
# The block's heading and descriptions in each page's own language.
TEXTS = {
    "sr": [
        "Drugi projekti",
        "Besplatan GTD menadžer zadataka sa Telegram botom",
        "Besplatan planning poker za scrum timove, bez registracije",
        "Mali oglasi u Srbiji",
        "Napravio",
    ],
    "en": [
        "Other projects",
        "Free GTD task manager with a Telegram bot",
        "Free planning poker for scrum teams, no sign-up",
        "Classifieds in Serbia",
        "Made by",
    ],
    "ru": [
        "Другие проекты",
        "Бесплатный GTD-менеджер задач с Telegram-ботом",
        "Бесплатный planning poker для scrum-команд, без регистрации",
        "Объявления в Сербии",
        "Сделано в",
    ],
}


class _Page(HTMLParser):
    """Collects hrefs inside #crosspromo, JSON-LD blocks and meta properties."""

    def __init__(self):
        super().__init__()
        self.promo_depth = 0
        self.promo_links, self.promo_text, self.ld_json, self.meta = [], [], [], {}
        self._in_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "nav" and a.get("id") == "crosspromo":
            self.promo_depth = 1
        elif self.promo_depth and tag == "nav":
            self.promo_depth += 1
        if self.promo_depth:
            if tag == "a":
                self.promo_links.append(a["href"])
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
        if tag == "meta" and a.get("property"):
            self.meta[a["property"]] = a.get("content")

    def handle_endtag(self, tag):
        if tag == "nav" and self.promo_depth:
            self.promo_depth -= 1
        if tag == "script":
            self._in_ld = False

    def handle_data(self, data):
        if self._in_ld:
            self.ld_json.append(data)
        if self.promo_depth and data.strip(" —\n"):
            self.promo_text.append(data.strip(" —\n"))


def _landing(client, lang):
    resp = client.get(LANDING_PAGES[lang][0])
    assert resp.status_code == 200
    html = b"".join(resp.streaming_content).decode()
    page = _Page()
    page.feed(html)
    return html, page


@pytest.mark.parametrize("lang", LANGS)
def test_landing_has_crosspromo_with_utm(client, lang):
    _, page = _landing(client, lang)
    assert page.promo_links == [p + UTM for p in PRODUCTS] + [MADE_BY]


@pytest.mark.parametrize("lang", LANGS)
def test_crosspromo_in_the_page_language(client, lang):
    _, page = _landing(client, lang)
    names = ["GTD", "Planning Poker", "Serbito", "No Handoff"]
    assert [t for t in page.promo_text if t not in names] == TEXTS[lang]


@pytest.mark.parametrize("lang", LANGS)
def test_crosspromo_keeps_seo_tags(client, lang):
    _, page = _landing(client, lang)
    ld = json.loads("".join(page.ld_json))
    assert ld["url"] == "https://javi.serbito.rs/"
    assert page.meta["og:url"] == "https://javi.serbito.rs" + LANDING_PAGES[lang][0]
    assert page.meta["og:image"] == "https://javi.serbito.rs/og.png"


def _shop_with_token():
    user = get_user_model().objects.create_user(email="x@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pizza Napoli")
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="Ana",
        recipient_phone="+381641234567",
        dest_address="Adresa 1, Beograd",
        dest_city="Beograd",
    )
    return TrackingToken.objects.create(delivery=delivery)


@pytest.mark.parametrize("path", ["/app/", "tracking", "/accounts/login/"])
def test_no_crosspromo_outside_landing(client, path):
    token = _shop_with_token()
    if path == "/app/":
        assert client.login(username="x@shop.rs", password="pass12345")
    if path == "tracking":
        path = f"/t/{token.token}/"
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "crosspromo" not in body
    for product in PRODUCTS:
        assert product not in body
    assert MADE_BY not in body
