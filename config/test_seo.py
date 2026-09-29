"""SERBITO-303: search engines see the landing and nothing private.

- robots.txt disallows every private prefix Django serves and keeps /t/ crawlable, so bots can
  read the tracking pages' noindex (a Disallow would hide it).
- Everything Django renders sends `X-Robots-Tag: noindex, nofollow`; /t/ pages also carry the
  meta tag. Landing files (WhiteNoise) do not.
- landing/sitemap.xml stays a static file; this test keeps it exactly in sync with the public
  landing pages (every landing/*.html that is not noindex) and checks each URL answers 200.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import pytest
from django.urls import get_resolver

LANDING = Path(__file__).resolve().parent.parent / "landing"
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


@pytest.mark.parametrize("path", ["/", "/privacy.html", "/t/", "/t/some-token/"])
def test_robots_allows_public_paths(path):
    assert _robots().can_fetch("*", f"{SITE}{path}")


def test_robots_points_to_sitemap(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert f"Sitemap: {SITE}/sitemap.xml" in _body(resp).splitlines()


# --- sitemap ---


def _public_landing_urls():
    urls = set()
    for page in LANDING.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        if re.search(r'<meta name="robots" content="[^"]*noindex', html):
            continue
        urls.add(f"{SITE}/" if page.name == "index.html" else f"{SITE}/{page.name}")
    return urls


def _sitemap_urls():
    root = ET.parse(LANDING / "sitemap.xml").getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text.strip() for loc in root.findall("sm:url/sm:loc", ns)]


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
