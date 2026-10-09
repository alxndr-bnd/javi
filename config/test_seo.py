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

SERBITO-595: shop-owner search terms and a public price.
- Title = descriptor + the search phrase (≤ 60 chars); H1 names Viber, SMS and delivery
  notifications to customers; the description (≤ 155 chars) carries the price and the trial.
- The SoftwareApplication has an Offer: 30 EUR a month. A FAQPage node repeats the questions and
  answers shown on the page, word for word.
- Owner answers (2026-10-09): Viber/SMS messages are in the 30 €, with no limit shown. After the
  30 free days payment is required; without it the trial limits stay. No "card payment soon"
  promise. No Handoff (the owner's company) makes Javi; no address or personal data.

SERBITO-462: SEO polish.
- "Javi" alone is ambiguous (Spanish footballers): the title, og:site_name and the schema
  alternateName carry a descriptor in the page language.
- Each language page has one JSON-LD @graph: Organization (No Handoff), WebSite, WebPage and
  SoftwareApplication, with stable @ids under https://javi.serbito.rs/.
- /index.html, /en/index.html, /ru/index.html answer 301 (WhiteNoise's default is 302).
"""

import datetime
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit
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
# The brand with a descriptor (SERBITO-462): title, og:site_name, schema alternateName.
DESCRIPTOR = {
    "sr": "Javi — Viber/SMS obaveštenja o isporuci",
    "en": "Javi — Viber/SMS delivery notifications",
    "ru": "Javi — уведомления о доставке в Viber/SMS",
}
TITLE = {
    "sr": "Javi — Viber/SMS obaveštenja o isporuci i praćenje pošiljke",
    "en": "Javi — Viber/SMS delivery notifications and parcel tracking",
    "ru": "Javi — уведомления о доставке в Viber/SMS для магазинов",
}
H1 = {
    "sr": "Viber i SMS obaveštenja kupcima o dostavi",
    "en": "Viber and SMS delivery notifications for your customers",
    "ru": "Уведомления покупателям о доставке в Viber и SMS",
}
# What a shop owner searches for (SERBITO-595): every page names the channels in title and H1.
SEARCH_TERMS = ("Viber", "SMS")
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
    for term in SEARCH_TERMS:
        assert term in title and term in h1.text() and term in description, term
    assert len(description) <= 155, len(description)
    assert "30" in description  # the price or the trial is in the snippet


@pytest.mark.parametrize("lang", LANGS)
def test_brand_descriptor_in_title_and_site_name(lang):
    """Google shows up to ~60 characters of a title; the descriptor names what Javi does."""
    title = parse_html(_landing(lang)).find("title").text()
    assert title.startswith(DESCRIPTOR[lang])
    assert len(title) <= 60, len(title)
    assert _meta(lang, "property", "og:site_name") == [DESCRIPTOR[lang]]


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


# --- structured data (SERBITO-462) ---

LINKEDIN = "https://www.linkedin.com/company/nohandoff/"
ORG_ID = f"{SITE}/#organization"
WEBSITE_ID = f"{SITE}/#website"
APP_ID = f"{SITE}/#software"


def _graph(lang):
    """The page's one JSON-LD block: {@type: node}, one node per type."""
    blocks = _head(lang).find_all("script", {"type": "application/ld+json"})
    assert len(blocks) == 1, "one JSON-LD block per page"
    data = json.loads("".join(c for c in blocks[0].children if isinstance(c, str)))
    assert data["@context"] == "https://schema.org"
    assert set(data) == {"@context", "@graph"}
    nodes = {node["@type"]: node for node in data["@graph"]}
    assert len(nodes) == len(data["@graph"]), "one node per type"
    return nodes


def _refs(value):
    """Every {"@id": …} reference inside a node (not the node's own @id)."""
    if isinstance(value, dict):
        if set(value) == {"@id"}:
            yield value["@id"]
        else:
            for v in value.values():
                yield from _refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from _refs(v)


@pytest.mark.parametrize("lang", LANGS)
def test_json_ld_graph_has_the_four_nodes_with_stable_ids(lang):
    url = SITE + LANDING_PAGES[lang][0]
    nodes = _graph(lang)
    assert set(nodes) == {"Organization", "WebSite", "WebPage", "SoftwareApplication", "FAQPage"}
    ids = {t: n["@id"] for t, n in nodes.items()}
    assert ids == {
        "Organization": ORG_ID,
        "WebSite": WEBSITE_ID,
        "WebPage": f"{url}#webpage",
        "SoftwareApplication": APP_ID,
        "FAQPage": f"{url}#faq",
    }
    for node in nodes.values():  # every reference points to a node of this graph
        for ref in _refs({k: v for k, v in node.items() if k != "@id"}):
            assert ref in ids.values(), ref


@pytest.mark.parametrize("lang", LANGS)
def test_json_ld_organization_is_no_handoff(lang):
    org = _graph(lang)["Organization"]
    # SERBITO-595: the organisation's own site is javi; LinkedIn is a profile of it (sameAs).
    assert org == {
        "@type": "Organization",
        "@id": ORG_ID,
        "name": "No Handoff",
        "url": f"{SITE}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"{SITE}/apple-touch-icon.png",
            "width": 180,
            "height": 180,
        },
        "sameAs": [LINKEDIN],
    }


@pytest.mark.parametrize("lang", LANGS)
def test_json_ld_website(lang):
    site = _graph(lang)["WebSite"]
    assert site["url"] == f"{SITE}/"
    assert site["name"] == "Javi"
    assert site["alternateName"] == DESCRIPTOR[lang]
    assert site["publisher"] == {"@id": ORG_ID}


@pytest.mark.parametrize("lang", LANGS)
def test_json_ld_webpage_matches_the_page(lang):
    """The WebPage node says what the page head says: url, title, description, language."""
    page = _graph(lang)["WebPage"]
    html = parse_html(_landing(lang))
    assert page["url"] == SITE + LANDING_PAGES[lang][0]
    assert page["name"] == html.find("title").text()
    assert page["description"] == _meta(lang, "name", "description")[0]
    assert page["inLanguage"] == html.find("html").attrs["lang"]
    assert page["isPartOf"] == {"@id": WEBSITE_ID}
    assert page["about"] == {"@id": APP_ID}


@pytest.mark.parametrize("lang", LANGS)
def test_json_ld_software_application(lang):
    app = _graph(lang)["SoftwareApplication"]
    assert app["name"] == "Javi"
    assert app["alternateName"] == DESCRIPTOR[lang]
    assert app["applicationCategory"] == "BusinessApplication"
    assert app["operatingSystem"] == "Web"
    assert app["url"] == SITE + LANDING_PAGES[lang][0]
    assert app["publisher"] == {"@id": ORG_ID}
    description = app["description"]
    assert bool(CYRILLIC.search(description)) == (lang == "ru"), description
    if lang == "en":
        assert not SERBIAN_LATIN.search(description), description
    if lang == "sr":
        assert SERBIAN_LATIN.search(description), description
    # The public price (SERBITO-593/595): 30 EUR a month per shop, the same as on the page.
    offer = app["offers"]
    assert offer["@type"] == "Offer"
    assert (offer["price"], offer["priceCurrency"]) == ("30", "EUR")
    assert offer["priceSpecification"]["billingDuration"] == "P1M"
    assert offer["url"] == SITE + LANDING_PAGES[lang][0] + "#cena"
    price = parse_html(_landing(lang)).find("section", {"id": "cena"}).text()
    assert "30 €" in price


@pytest.mark.parametrize("lang", LANGS)
def test_json_ld_faq_matches_the_visible_faq(lang):
    """Google ignores (or penalises) FAQ markup that the visitor cannot read on the page."""
    faq = _graph(lang)["FAQPage"]
    assert faq["inLanguage"] == lang
    visible = parse_html(_landing(lang)).find("div", {"class": "faq"})
    questions = [h.text() for h in visible.find_all("h3")]
    # Node.text() puts a space between a link and the text after it: "docs/ ." -> "docs/."
    answers = [re.sub(r" ([.,:;!?])", r"\1", p.text()) for p in visible.find_all("p")]
    assert len(questions) >= 5
    assert [(q["name"], q["acceptedAnswer"]["text"]) for q in faq["mainEntity"]] == list(
        zip(questions, answers, strict=True)
    )
    assert all(q["@type"] == "Question" for q in faq["mainEntity"])


# The owner's answers (SERBITO-595, 2026-10-09), in the price card, the FAQ and the Offer.
AFTER_TRIAL = {
    "sr": "Posle 30 dana za nastavak je potrebno plaćanje. Bez plaćanja ostaju probni limiti.",
    "en": (
        "After the 30 days, payment is required to continue. "
        "Without payment, the trial limits stay."
    ),
    "ru": "После 30 дней для продолжения нужна оплата. Без оплаты остаются пробные лимиты.",
}
MESSAGES_INCLUDED = {
    "sr": "Viber i SMS poruke su uključene u cenu.",
    "en": "Viber and SMS messages are included in the price.",
    "ru": "Сообщения в Viber и SMS входят в цену.",
}
NO_LONGER_PROMISED = ("soon", "uskoro", "скоро", "charges nothing", "ne naplaćuje", "не списывает")


@pytest.mark.parametrize("lang", LANGS)
def test_price_says_payment_is_required_after_the_trial(lang):
    page = parse_html(_landing(lang))
    price = page.find("section", {"id": "cena"})
    assert price.find("p", {"class": "after"}).text() == AFTER_TRIAL[lang]
    faq = page.find("section", {"id": "pitanja"}).text()
    assert AFTER_TRIAL[lang] in faq
    assert MESSAGES_INCLUDED[lang] in faq
    offer = _graph(lang)["SoftwareApplication"]["offers"]
    assert MESSAGES_INCLUDED[lang] in offer["description"]
    for text in (price.text(), faq, json.dumps(_graph(lang), ensure_ascii=False)):
        for word in NO_LONGER_PROMISED:
            assert word not in text.lower(), (lang, word)


@pytest.mark.parametrize("lang", LANGS)
def test_no_handoff_runs_javi_without_personal_data(lang):
    html = _landing(lang)
    assert "TODO" not in html
    about = parse_html(html).find("section", {"id": "o-nama"})
    assert "No Handoff" in about.text()
    assert "@" not in about.text()  # no personal or business e-mail on the page


def test_json_ld_shared_nodes_agree_across_languages():
    """One organisation, one site, one app: only the words and the page URL differ."""
    per_page = {"alternateName", "description", "url"}

    def shared(lang):
        nodes = _graph(lang)
        site = {k: v for k, v in nodes["WebSite"].items() if k != "alternateName"}
        app = {
            k: v for k, v in nodes["SoftwareApplication"].items() if k not in per_page | {"offers"}
        }
        offer = nodes["SoftwareApplication"]["offers"]
        app["price"] = (offer["price"], offer["priceCurrency"])
        return nodes["Organization"], site, app

    for lang in LANGS[1:]:
        assert shared(lang) == shared("sr"), lang


# --- /index.html is a permanent redirect (SERBITO-462) ---


@pytest.mark.parametrize(
    "path, target",
    [
        ("/index.html", "/"),
        ("/en/index.html", "/en/"),
        ("/ru/index.html", "/ru/"),
        ("/en", "/en/"),
        ("/ru", "/ru/"),
    ],
)
def test_index_html_redirects_permanently(client, path, target):
    resp = client.get(path)
    assert resp.status_code == 301
    assert urljoin(f"{SITE}{path}", resp["Location"]) == f"{SITE}{target}"
