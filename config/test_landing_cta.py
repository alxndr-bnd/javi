"""SERBITO-356 item 1: the landing lets a shop start on its own.

SERBITO-595: one primary action above the fold. The hero has a single CTA (registration) with
the trial offer next to it; the lead form ("leave your contact") stays further down for
questions, linked from "Who runs Javi". The header links existing shops to sign-in. App links
carry the landing language over to the app. Every CTA says which one it is (data-cta) for GA4.
SERBITO-459: each language has its own page ("/", "/en/", "/ru/"); the language comes from the
page, not from a saved choice.
"""

import pytest

from common.testing import LANDING_PAGES, parse_html

TEXTS = {
    "sr": ("Isprobaj 30 dana besplatno", "Prijava", "30 dana besplatno"),
    "en": ("Try it free for 30 days", "Sign in", "30 days free"),
    "ru": ("Попробовать 30 дней бесплатно", "Войти", "30 дней бесплатно"),
}
PRICE = "30 €"


def _html(lang):
    return LANDING_PAGES[lang][1].read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_hero_has_one_primary_action_registration(lang):
    page = parse_html(_html(lang))
    hero = page.find("section", {"class": "hero"})
    cta, signin, _ = TEXTS[lang]
    assert [(a.attrs["href"], a.text(), a.attrs.get("data-cta")) for a in hero.find_all("a")] == [
        ("/accounts/register/", cta, "hero")
    ]
    nav_signin = page.find("nav", {"id": "langs"}).find("a", {"class": "signin"})
    assert (nav_signin.attrs["href"], nav_signin.text()) == ("/accounts/login/", signin)


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_trial_and_price_sit_next_to_the_cta(lang):
    hero = parse_html(_html(lang)).find("section", {"class": "hero"})
    trial = hero.find("p", {"class": "trial"}).text()
    assert TEXTS[lang][2] in trial
    assert PRICE in trial


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_lead_form_is_still_reachable(lang):
    page = parse_html(_html(lang))
    assert page.find("section", {"id": "prijava"})
    about = page.find("section", {"id": "o-nama"})
    assert "#prijava" in [a.attrs["href"] for a in about.find_all("a")]


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_every_registration_link_is_an_app_link_with_a_cta_name(lang):
    page = parse_html(_html(lang))
    links = [a for a in page.find_all("a") if a.attrs.get("href") == "/accounts/register/"]
    assert [a.attrs.get("data-cta") for a in links] == ["hero", "pricing"]
    assert all("data-app-link" in a.attrs for a in links)


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_app_links_carry_the_page_language(lang):
    html = _html(lang)
    assert html.count("data-app-link") >= 4  # two CTAs, sign-in + the script selector
    assert "{sr:'sr-latn', en:'en', ru:'en'}[LANG]" in html
    assert "const LANG = document.documentElement.lang;" in html
    assert "django_language=" in html
