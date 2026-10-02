"""SERBITO-321 (owner decision SERBITO-285): keep GA4, ask for consent first.

- Landing, privacy page and app pages set the Consent Mode v2 default (everything denied, or a
  stored choice) inline, before gtag config and before gtag.js loads. The snippet is the same on
  all three, so a fix in one place cannot silently miss the others. GA's cookies are host-only
  (cookie_domain 'none'), not shared with the other *.serbito.rs products.
- The banner (landing/consent.js, served at /consent.js) speaks sr/en/ru; each page has a
  "Cookie settings" control (data-consent-open) that reopens it.
- privacy.html explains consent, what is sent while denied and how to change it, in sr/en/ru.
- /t/ tracking pages: still no GA (config/test_analytics.py), and no banner or settings either.
"""

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from common.testing import contrast, css_declarations
from deliveries.models import Shop

pytestmark = pytest.mark.django_db

LANDING = Path(__file__).resolve().parent.parent / "landing"
CONSENT_JS = (LANDING / "consent.js").read_text(encoding="utf-8")
GA_ID = "G-KHME7DK2K0"
DEFAULT = "gtag('consent', 'default'"
CONFIG = f"gtag('config', '{GA_ID}', {{cookie_domain: 'none'}});"
LOADER = f"googletagmanager.com/gtag/js?id={GA_ID}"
# Django pages add a CSP nonce (SERBITO-362); the static landing has none.
SCRIPT = re.compile(r'<script(?: nonce="[^"]+")? src="/consent.js" defer></script>')
LANGS = ["sr", "en", "ru"]


def _body(resp):
    if resp.streaming:
        return b"".join(resp.streaming_content).decode()
    return resp.content.decode()


@pytest.fixture
def shop(db):
    user = get_user_model().objects.create_user(email="consent@shop.rs", password="pass12345")
    return Shop.objects.create(owner=user, name="Pizza Napoli")


def _page(client, shop, name, lang="en"):
    if name == "app":
        client.force_login(shop.owner)
        path = "/app/"
    else:
        path = {"landing": "/", "privacy": "/privacy.html", "login": "/accounts/login/"}[name]
    resp = client.get(path, HTTP_ACCEPT_LANGUAGE=lang)
    assert resp.status_code == 200, path
    return _body(resp)


def _consent_script(body):
    match = re.search(
        r'<script(?: nonce="[^"]+")?>'
        r"((?:(?!</script>).)*?gtag\('consent', 'default'.*?)</script>",
        body,
        re.S,
    )
    assert match, "no inline Consent Mode default"
    return " ".join(match.group(1).split())


# --- Consent Mode v2 default precedes the tag ---


@pytest.mark.parametrize("name", ["landing", "privacy", "app", "login"])
def test_consent_default_precedes_gtag_config(client, shop, name):
    body = _page(client, shop, name)
    assert body.count(DEFAULT) == 1
    assert body.index(DEFAULT) < body.index(CONFIG) < body.index(LOADER)
    script = _consent_script(body)
    for key in ("ad_storage", "ad_user_data", "ad_personalization"):
        assert f"{key}: 'denied'" in script
    assert "analytics_storage: a" in script and "var a = 'denied';" in script
    assert "wait_for_update: 500" in script
    # a returning visitor's choice counts only for 12 months
    assert "localStorage.getItem('javi_consent')" in script and "365 * 864e5" in script


def test_consent_default_is_the_same_everywhere(client, shop):
    scripts = {
        name: _consent_script(_page(client, shop, name)) for name in ("landing", "privacy", "app")
    }
    assert len(set(scripts.values())) == 1, scripts


@pytest.mark.parametrize("name", ["landing", "privacy", "app", "login"])
def test_page_loads_the_banner(client, shop, name):
    body = _page(client, shop, name)
    assert SCRIPT.search(body)
    assert "data-consent-open" in body


def test_banner_script_is_served(client):
    resp = client.get("/consent.js")
    assert resp.status_code == 200
    assert "javascript" in resp["Content-Type"]


# --- banner and "Cookie settings" in every language ---


@pytest.mark.parametrize(
    "lang, accept, decline, settings",
    [
        ("sr", "Prihvati", "Odbij", "Podešavanja kolačića"),
        ("en", "Accept", "Decline", "Cookie settings"),
        ("ru", "Принять", "Отклонить", "Настройки cookies"),
    ],
)
def test_banner_and_settings_in_every_language(lang, accept, decline, settings):
    block = re.search(rf"\n    {lang}: \{{(.*?)\n    \}}", CONSENT_JS, re.S)
    assert block, f"no {lang} strings in consent.js"
    strings = block.group(1)
    assert f'accept: "{accept}"' in strings and f'decline: "{decline}"' in strings
    assert "Google Analytics" in strings  # the one sentence says what the cookies are for
    # the landing's footer button translates with the rest of the page
    landing = (LANDING / "index.html").read_text(encoding="utf-8")
    assert f'cookies:"{settings}"' in landing
    # the privacy page has a settings button in each language
    privacy = (LANDING / "privacy.html").read_text(encoding="utf-8")
    assert f'data-consent-open="{lang}">{settings}</button>' in privacy


def test_landing_footer_has_cookie_settings(client, shop):
    body = _page(client, shop, "landing")
    footer = body[body.index("<footer>") : body.index("</footer>")]
    assert re.search(r'<button type="button"[^>]*data-consent-open[^>]*data-i18n="cookies"', footer)


@pytest.mark.parametrize(
    "lang, html_lang, settings, privacy",
    [
        ("en", "en", "Cookie settings", "Privacy policy"),
        ("sr", "sr-Latn", "Podešavanja kolačića", "Politika privatnosti"),
    ],
)
def test_app_footer_in_app_language(client, shop, lang, html_lang, settings, privacy):
    body = _page(client, shop, "app", lang)
    assert f'<html lang="{html_lang}">' in body
    footer = body[body.index('<footer class="site-foot">') : body.index("</footer>")]
    assert f"data-consent-open>{settings}</button>" in footer
    assert f'<a href="/privacy.html#{lang}">{privacy}</a>' in footer


def test_banner_behaviour_contract():
    """Accept grants analytics only; decline/withdrawal deletes _ga*; the privacy link is there."""
    assert 'gtag("consent", "update", { analytics_storage: value })' in CONSENT_JS
    assert "ad_storage" not in CONSENT_JS  # no ads consent is ever granted
    assert 'if (value === "denied") dropGaCookies();' in CONSENT_JS
    assert 'name.indexOf("_ga") !== 0' in CONSENT_JS
    assert '"/privacy.html#" + l' in CONSENT_JS
    assert 'var KEY = "javi_consent";' in CONSENT_JS and "365 * 864e5" in CONSENT_JS


def _function(name):
    body = CONSENT_JS[CONSENT_JS.index(f"function {name}(") :]
    return body[: body.index("\n  }\n")]


def test_banner_never_hides_the_focused_element():
    """SERBITO-352 (WCAG 2.4.11): while the banner is up, the page reserves its height at the
    bottom (scroll-padding for focus scrolling, padding so footer links can scroll clear), and a
    control it still covers after focus moves is scrolled above it."""
    reserve = _function("reserve")
    assert 'var room = banner.hidden ? "" : banner.offsetHeight + 2 * GAP + "px";' in reserve
    assert "root.scrollPaddingBottom = room;" in reserve and "root.paddingBottom = room;" in reserve
    # re-measured whenever the banner appears, goes, or changes size (language, viewport)
    assert "banner.hidden = false;\n    reserve();" in _function("show")
    assert "banner.hidden = true;\n    reserve();" in _function("choose")
    assert 'window.addEventListener("resize", reserve);' in CONSENT_JS
    assert "render(); reserve();" in CONSENT_JS
    # focus: after the browser's own scrolling, a covered control is lifted just above the banner
    assert 'document.addEventListener("focusin"' in CONSENT_JS
    assert "requestAnimationFrame(function () { unobscure(e.target); })" in CONSENT_JS
    unobscure = _function("unobscure")
    assert "banner.hidden" in unobscure and "banner.contains(el)" in unobscure
    assert "if (r.bottom > limit) window.scrollBy(0," in unobscure


def _banner_css():
    block = CONSENT_JS[CONSENT_JS.index("var CSS =") :]
    block = block[: block.index(";\n")]
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', block))


def test_accept_and_decline_carry_equal_weight():
    """SERBITO-352 (owner-approved): Decline is as easy to see and hit as Accept — the same class,
    one rule for both (no per-button styling), equal-width columns, readable text."""
    for hook in ("jc-accept", "jc-decline"):
        assert f'<button type="button" class="jc-btn {hook}"></button>' in CONSENT_JS
    css = _banner_css()
    selectors = re.findall(r"([^{}]+)\{", css)
    assert [s for s in selectors if "jc-accept" in s or "jc-decline" in s] == []
    assert css_declarations(css, ".jc-actions")["grid-template-columns"] == "1fr 1fr"
    button = css_declarations(css, ".jc .jc-btn")
    assert contrast(button["color"], button["background"]) >= 4.5


def test_withdrawal_clears_parent_domain_cookies_only_once():
    """Host-only _ga* always; the .serbito.rs ones earlier versions left, on the first run only."""
    drop = CONSENT_JS[CONSENT_JS.index("function dropGaCookies") :]
    drop = drop[: drop.index("\n  }\n")]
    assert 'document.cookie = name + "=; Max-Age=0; path=/";' in drop  # host-only
    assert 'parent = !localStorage.getItem(LEGACY); localStorage.setItem(LEGACY, "1");' in drop
    assert "if (!parent) return;" in drop
    assert "for (var i = 1; i < parts.length - 1; i++)" in drop  # parents, never the TLD


# --- privacy page explains consent ---


@pytest.mark.parametrize(
    "lang, heading",
    [
        ("sr", "Saglasnost za analitiku"),
        ("en", "Analytics consent"),
        ("ru", "Согласие на аналитику"),
    ],
)
def test_privacy_explains_consent(lang, heading):
    html = (LANDING / "privacy.html").read_text(encoding="utf-8")
    section = re.search(rf'<section id="{lang}" lang="{lang}">(.*?)</section>', html, re.S).group(1)
    assert f"<h2>{heading}</h2>" in section
    consent = section[section.index(f"<h2>{heading}</h2>") :]
    consent = consent[: consent.index("</p>")]
    assert "localStorage" in consent and "12" in consent  # where the choice lives, re-ask
    assert f'data-consent-open="{lang}"' in consent  # how to change it
    assert "_ga" in consent  # withdrawal deletes the cookies
