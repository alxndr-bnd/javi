"""SERBITO-595: icons and product proof on the landing.

- /favicon.ico and /apple-touch-icon.png (180x180) are real files, drawn from the "j" logo, and
  every page links them in <head>: the three landings, the privacy page and the app (base.html).
  They used to answer 404; the only icon was a data: URI.
- Each landing shows the product: the customer's Viber message and the tracking page, both made
  from the app with test data. Each image is AVIF with a WebP fallback, has width/height (no layout
  shift), loads lazily below the fold (no LCP cost) and has alt text in the page language.
"""

import re
import struct

import pytest
from django.test import Client

from common.testing import LANDING_DIR, LANDING_PAGES, parse_html

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
PROOF_IMAGES = ("viber-poruka", "pracenje-dostave")
MAX_IMAGE_BYTES = 60_000  # a phone screen in AVIF/WebP; a bigger file is a bad export


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize(
    ("path", "content_type"),
    [("/favicon.ico", "image/"), ("/apple-touch-icon.png", "image/png")],
)
def test_icons_are_served(path, content_type):
    resp = Client().get(path)
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith(content_type)


def test_apple_touch_icon_is_180_square_and_opaque():
    data = (LANDING_DIR / "apple-touch-icon.png").read_bytes()
    assert _png_size(data) == (180, 180)
    assert data[25] == 2  # PNG colour type 2 = RGB, no alpha: iOS paints alpha black


def test_favicon_ico_has_small_sizes():
    data = (LANDING_DIR / "favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert {16, 32}.issubset(sizes)


def _icon_links(html: str) -> dict[str, str]:
    head = parse_html(html).find("head")
    return {
        (link.attrs.get("rel"), link.attrs.get("type") or link.attrs.get("sizes")): link.attrs[
            "href"
        ]
        for link in head.find_all("link")
        if link.attrs.get("rel") in {"icon", "apple-touch-icon"}
    }


@pytest.mark.parametrize(
    "file",
    [
        *(file for _, file in LANDING_PAGES.values()),
        LANDING_DIR / "privacy.html",
        LANDING_DIR.parent / "templates" / "base.html",
    ],
    ids=lambda f: str(f.relative_to(LANDING_DIR.parent)),
)
def test_every_page_links_the_icons(file):
    links = _icon_links(file.read_text(encoding="utf-8"))
    assert links[("icon", "48x48")] == "/favicon.ico"
    assert links[("apple-touch-icon", None)] == "/apple-touch-icon.png"
    assert links[("icon", "image/svg+xml")].startswith("data:image/svg+xml,")


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_landing_shows_the_message_and_the_tracking_page(lang):
    page = parse_html(LANDING_PAGES[lang][1].read_text(encoding="utf-8"))
    how = page.find("section", {"id": "kako"})  # below the hero: never the LCP element
    figures = how.find("div", {"class": "proof"}).find_all("figure")
    assert len(figures) == len(PROOF_IMAGES)
    for figure, name in zip(figures, PROOF_IMAGES, strict=True):
        [source] = figure.find_all("source")
        [img] = figure.find_all("img")
        assert (source.attrs["srcset"], source.attrs["type"]) == (f"/img/{name}.avif", "image/avif")
        assert img.attrs["src"] == f"/img/{name}.webp"
        assert (img.attrs["width"], img.attrs["height"]) == ("360", "500")
        assert img.attrs["loading"] == "lazy"
        alt = img.attrs["alt"]
        assert len(alt) > 40, alt
        assert bool(CYRILLIC.search(alt)) == (lang == "ru"), alt
        assert figure.find("figcaption").text()


@pytest.mark.parametrize("name", PROOF_IMAGES)
@pytest.mark.parametrize("ext", ["avif", "webp"])
def test_proof_images_exist_are_small_and_served(name, ext):
    path = LANDING_DIR / "img" / f"{name}.{ext}"
    assert 0 < path.stat().st_size <= MAX_IMAGE_BYTES
    resp = Client().get(f"/img/{name}.{ext}")
    assert resp.status_code == 200
    assert resp["Content-Type"] == f"image/{ext}"
