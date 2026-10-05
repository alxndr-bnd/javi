"""SERBITO-356 item 1: the landing lets a shop start on its own.

The primary CTA opens registration, the secondary one the lead form, and the header links
existing shops to sign-in. App links carry the landing language over to the app.
SERBITO-459: each language has its own page ("/", "/en/", "/ru/"); the language comes from the
page, not from a saved choice.
"""

import pytest

from common.testing import LANDING_PAGES, parse_html

TEXTS = {
    "sr": ("Isprobaj besplatno", "Ostavite kontakt", "Prijava"),
    "en": ("Try it free", "Leave your contact", "Sign in"),
    "ru": ("Попробовать бесплатно", "Оставить контакт", "Войти"),
}


def _html(lang):
    return LANDING_PAGES[lang][1].read_text(encoding="utf-8")


def _links(lang):
    page = parse_html(_html(lang))
    hero = page.find("section", {"class": "hero"}).find_all("a")
    signin = page.find("nav", {"id": "langs"}).find("a", {"class": "signin"})
    return page, [(a.attrs["href"], a.text()) for a in [*hero, signin]]


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_ctas_open_registration_lead_form_and_sign_in(lang):
    page, links = _links(lang)
    cta, cta2, signin = TEXTS[lang]
    assert links == [
        ("/accounts/register/", cta),
        ("#prijava", cta2),
        ("/accounts/login/", signin),
    ]
    assert page.find("section", {"id": "prijava"})


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_app_links_carry_the_page_language(lang):
    html = _html(lang)
    assert html.count("data-app-link") >= 3  # two links + the script selector
    assert "{sr:'sr-latn', en:'en', ru:'en'}[LANG]" in html
    assert "const LANG = document.documentElement.lang;" in html
    assert "django_language=" in html
