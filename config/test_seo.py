"""SERBITO-303: search engines see the landing and nothing private.

- robots.txt disallows every private prefix Django serves and keeps /t/ crawlable, so bots can
  read the tracking pages' noindex (a Disallow would hide it).
- Everything Django renders sends `X-Robots-Tag: noindex, nofollow`; /t/ pages also carry the
  meta tag. Landing files (WhiteNoise) do not.
- landing/sitemap.xml stays a static file; this test keeps it exactly in sync with the public
  landing pages (every landing/**/*.html that is not noindex) and checks each URL answers 200.

SERBITO-459: one URL per language, so Google indexes the Serbian landing for Serbian queries.
- "/" (sr, Latin script), "/en/" and "/ru/" are separate static pages. Each has its own <title>,
  description, H1, <html lang>, self canonical and og:locale in its language in the raw HTML:
  no script rewrites the text (Googlebot renders with en-US and used to index English).
- Every language page lists all three plus x-default ("/") as hreflang alternates, and each
  alternate lists it back. The language switch is plain links to those URLs.
- The sitemap gives every URL a <lastmod> and the landing URLs the same alternates
  (xhtml:link). /privacy.html is one page with all three languages: no alternates.
"""

import datetime
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import pytest
from django.urls import get_resolver

from common.testing import LANDING_DIR as LANDING
from common.testing import LANDING_PAGES, parse_html

SITE = "https://javi.serbito.rs"
NOINDEX = "noindex, nofollow"
META_NOINDEX = '<meta name="robots" content="noindex, nofollow">'
PRIVATE_PREFIXES = ["admin/", "app/", "accounts/", "api/", "webhooks/", "tasks/", "i18n/"]
# Top-level Django prefixes that must stay crawlable (they rely on noindex instead).
CRAWLABLE_PREFIXES = {"t/"}


def _body(resp):
    if resp.streaming:
        return b"".join(resp.streaming_content).decode()
    return resp.content.decode()


def _robots():
    parser = RobotFileParser()
    parser.parse((LANDING / "robots.txt").read_text(encoding="utf-8").splitlines())
    return parser


def _top_level_prefixes():
    return {str(p.pattern).split("/", 1)[0] + "/" for p in get_resolver().url_patterns}


# --- robots.txt ---


@pytest.mark.parametrize("prefix", PRIVATE_PREFIXES)
def test_robots_disallows_private_prefix(prefix):
    assert not _robots().can_fetch("*", f"{SITE}/{prefix}anything")


def test_robots_covers_every_django_prefix():
    """A new top-level route must be disallowed or deliberately listed as crawlable.

    The admin moved to a secret ADMIN_PATH (SERBITO-362) and is not mounted without it; that
    path stays out of robots.txt (listing it would publish it), /admin/ stays disallowed.
    """
    assert _top_level_prefixes() | {"admin/"} == set(PRIVATE_PREFIXES) | CRAWLABLE_PREFIXES


@pytest.mark.parametrize("path", ["/", "/en/", "/ru/", "/privacy.html", "/t/", "/t/some-token/"])
def test_robots_allows_public_paths(path):
    assert _robots().can_fetch("*", f"{SITE}{path}")


def test_robots_points_to_sitemap(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert f"Sitemap: {SITE}/sitemap.xml" in _body(resp).splitlines()


# --- sitemap ---


def _url(page):
    """Site URL of a landing file: a directory's index.html is served as the directory."""
    path = page.relative_to(LANDING).as_posix()
    return f"{SITE}/{path.removesuffix('index.html')}"


def _public_landing_urls():
    urls = set()
    for page in LANDING.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        if re.search(r'<meta name="robots" content="[^"]*noindex', html):
            continue
        urls.add(_url(page))
    return urls


SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "xhtml": "http://www.w3.org/1999/xhtml",
}


def _sitemap_entries():
    root = ET.parse(LANDING / "sitemap.xml").getroot()
    return root.findall("sm:url", SITEMAP_NS)


def _sitemap_urls():
    return [e.find("sm:loc", SITEMAP_NS).text.strip() for e in _sitemap_entries()]


def test_sitemap_lists_exactly_the_public_landing_pages():
    urls = _sitemap_urls()
    assert len(urls) == len(set(urls)), "duplicate <loc> in sitemap.xml"
    assert set(urls) == _public_landing_urls()


@pytest.mark.parametrize("url", _sitemap_urls())
def test_every_sitemap_url_is_served_and_indexable(client, url):
    resp = client.get(urlsplit(url).path)
    assert resp.status_code == 200
    assert "X-Robots-Tag" not in resp.headers
    assert "noindex" not in _body(resp)


@pytest.mark.parametrize("entry", _sitemap_entries(), ids=_sitemap_urls())
def test_every_sitemap_url_has_lastmod(entry):
    lastmod = entry.find("sm:lastmod", SITEMAP_NS)
    assert lastmod is not None, "no <lastmod>: Google gets no change signal"
    day = datetime.date.fromisoformat(lastmod.text.strip())
    assert day <= datetime.date.today()


@pytest.mark.parametrize("entry", _sitemap_entries(), ids=_sitemap_urls())
def test_sitemap_alternates_match_the_page(entry):
    """The sitemap and the page itself declare the same hreflang alternates."""
    url = entry.find("sm:loc", SITEMAP_NS).text.strip()
    in_sitemap = {
        (link.get("hreflang"), link.get("href"))
        for link in entry.findall("xhtml:link", SITEMAP_NS)
        if link.get("rel") == "alternate"
    }
    page = urlsplit(url).path.removeprefix("/") or "index.html"
    page = LANDING / (page + "index.html" if page.endswith("/") else page)
    assert in_sitemap == _alternates(page.read_text(encoding="utf-8"))


def test_sitemap_is_served(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "X-Robots-Tag" not in resp.headers


# --- noindex on Django pages ---


# /t/ pages (live, expired, unknown) are noindex:
# tracking/tests.py::test_tracking_pages_stay_private


@pytest.mark.parametrize(
    "path",
    ["/accounts/login/", "/accounts/register/", "/api/docs/", "/api/redoc/", "/api/schema/"],
)
def test_private_pages_are_noindex(client, db, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["X-Robots-Tag"] == NOINDEX


# --- one URL per language (SERBITO-459) ---

LANGS = list(LANDING_PAGES)
OG_LOCALE = {"sr": "sr_RS", "en": "en_US", "ru": "ru_RU"}
# What a visitor (and Googlebot, which renders with en-US) reads, without running any script.
TITLE = {
    "sr": "Javi — obavestite kupca kada paket stiže",
    "en": "Javi — tell your customer when the parcel is on the way",
    "ru": "Javi — сообщите покупателю, когда посылка в пути",
}
H1 = {
    "sr": "Obavestite kupca kada paket krene — i kada stiže",
    "en": "Tell your customer when the parcel leaves — and when it arrives",
    "ru": "Сообщите покупателю, когда посылка выехала — и когда приедет",
}
EXPECTED_ALTERNATES = {(lang, SITE + path) for lang, (path, _) in LANDING_PAGES.items()} | {
    ("x-default", f"{SITE}/")
}
CYRILLIC = re.compile(r"[\u0400-\u04ff]")
SERBIAN_LATIN = re.compile(r"[čćđšžČĆĐŠŽ]")


def _alternates(html):
    links = parse_html(html).find_all("link", {"rel": "alternate"})
    return {(link.attrs["hreflang"], link.attrs["href"]) for link in links}


def _landing(lang):
    return LANDING_PAGES[lang][1].read_text(encoding="utf-8")


def _head(lang):
    return parse_html(_landing(lang)).find("head")


def _meta(lang, attr, name):
    return [m.attrs["content"] for m in _head(lang).find_all("meta", {attr: name})]


@pytest.mark.parametrize("lang", LANGS)
def test_language_page_is_served_as_is(client, lang):
    path, file = LANDING_PAGES[lang]
    resp = client.get(path)
    assert resp.status_code == 200
    assert _body(resp) == file.read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", LANGS)
def test_language_page_declares_its_language(lang):
    page = parse_html(_landing(lang))
    assert page.find("html").attrs["lang"] == lang
    assert _meta(lang, "property", "og:locale") == [OG_LOCALE[lang]]
    others = [OG_LOCALE[x] for x in LANGS if x != lang]
    assert _meta(lang, "property", "og:locale:alternate") == others
    hidden = page.find("input", {"name": "lang"})  # the lead form says which page it came from
    assert hidden.attrs["value"] == lang


@pytest.mark.parametrize("lang", LANGS)
def test_language_page_has_self_canonical(lang):
    url = SITE + LANDING_PAGES[lang][0]
    [canonical] = _head(lang).find_all("link", {"rel": "canonical"})
    assert canonical.attrs["href"] == url
    assert _meta(lang, "property", "og:url") == [url]


@pytest.mark.parametrize("lang", LANGS)
def test_title_and_h1_are_in_the_page_language_without_js(lang):
    page = parse_html(_landing(lang))
    title = page.find("title").text()
    [h1] = page.find_all("h1")
    assert (title, h1.text()) == (TITLE[lang], H1[lang])
    description = _meta(lang, "name", "description")[0]
    og_title = _meta(lang, "property", "og:title")[0]
    for text in (title, h1.text(), description, og_title):
        assert bool(CYRILLIC.search(text)) == (lang == "ru"), text
        if lang == "en":
            assert not SERBIAN_LATIN.search(text), text
    if lang == "sr":
        assert SERBIAN_LATIN.search(title + h1.text() + description)


@pytest.mark.parametrize("lang", LANGS)
def test_no_script_switches_the_language(lang):
    """The text is the page's own: no translation table, no browser-language guess."""
    html = _landing(lang)
    for marker in ("data-i18n", "navigator.language", "setLang", "const I18N"):
        assert marker not in html, marker


@pytest.mark.parametrize("lang", LANGS)
def test_hreflang_lists_every_language_and_x_default(lang):
    assert _alternates(_landing(lang)) == EXPECTED_ALTERNATES


@pytest.mark.parametrize("lang", LANGS)
def test_hreflang_is_reciprocal(lang):
    """Every alternate a page names lists that page back (Google ignores one-way hreflang)."""
    url = SITE + LANDING_PAGES[lang][0]
    by_url = {SITE + path: lang_ for lang_, (path, _) in LANDING_PAGES.items()}
    for hreflang, href in _alternates(_landing(lang)):
        if hreflang == "x-default":
            continue
        assert by_url[href] == hreflang, href
        assert (lang, url) in _alternates(_landing(hreflang)), (hreflang, href)


@pytest.mark.parametrize("lang", LANGS)
def test_language_switch_is_plain_links(lang):
    nav = parse_html(_landing(lang)).find("nav", {"id": "langs"})
    links = [a for a in nav.find_all("a") if a.attrs.get("hreflang")]
    assert [(a.attrs["href"], a.attrs["hreflang"]) for a in links] == [
        (path, lang_) for lang_, (path, _) in LANDING_PAGES.items()
    ]
    current = [a.attrs["hreflang"] for a in links if a.attrs.get("aria-current") == "page"]
    assert current == [lang]
    assert nav.find_all("button") == []


def test_language_pages_share_style_and_script():
    """Only the words differ: one stylesheet and one behaviour script on every language page."""

    def shared(lang):
        html = _landing(lang)
        styles = re.findall(r"<style>(.*?)</style>", html, flags=re.S)
        scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)  # inline, no JSON-LD
        return styles, scripts

    sr = shared("sr")
    assert sr[0] and len(sr[1]) == 2  # Consent Mode default + page behaviour
    for lang in LANGS[1:]:
        assert shared(lang) == sr, lang
