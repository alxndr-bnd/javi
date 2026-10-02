"""SERBITO-356 item 1: the landing lets a shop start on its own.

The primary CTA opens registration, the secondary one the lead form, and the header links
existing shops to sign-in. App links carry the landing language over to the app.
"""

import re
from pathlib import Path

import pytest

LANDING = (Path(__file__).resolve().parent.parent / "landing" / "index.html").read_text(
    encoding="utf-8"
)


def _link(key):
    m = re.search(rf'<a href="([^"]+)"[^>]*data-i18n="{key}">([^<]+)</a>', LANDING)
    assert m, key
    return m.group(1), m.group(2)


def test_primary_cta_opens_registration():
    href, text = _link("hero_cta")
    assert href == "/accounts/register/"
    assert text == "Isprobaj besplatno"


def test_secondary_cta_opens_lead_form():
    href, text = _link("hero_cta2")
    assert href == "#prijava"
    assert text == "Ostavite kontakt"
    assert 'id="prijava"' in LANDING


def test_header_links_to_sign_in():
    href, text = _link("nav_signin")
    assert href == "/accounts/login/"
    assert text == "Prijava"


@pytest.mark.parametrize(
    "lang, cta, cta2, signin",
    [
        ("sr", "Isprobaj besplatno", "Ostavite kontakt", "Prijava"),
        ("en", "Try it free", "Leave your contact", "Sign in"),
        ("ru", "Попробовать бесплатно", "Оставить контакт", "Войти"),
    ],
)
def test_ctas_are_translated(lang, cta, cta2, signin):
    block = LANDING[LANDING.index(f"  {lang}:{{") :]
    block = block[: block.index("\n  },")] if "\n  }," in block else block
    assert f'hero_cta:"{cta}"' in block
    assert f'hero_cta2:"{cta2}"' in block
    assert f'nav_signin:"{signin}"' in block


def test_app_links_carry_the_language():
    assert LANDING.count("data-app-link") >= 3  # two links + the script selector
    assert "{sr:'sr-latn', en:'en', ru:'en'}" in LANDING
    assert "django_language=" in LANDING
