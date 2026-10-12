"""SERBITO-352: /privacy.html shows the policy in sr, en and ru at once under <html lang="sr">.

- Each language section declares its own lang (WCAG 3.1.2), so screen readers switch voice; the
  language links that name another language are marked too.
- Headings never skip a level: one h1 per language section, its subsections h2.
- The sections sit in <main>.
"""

from pathlib import Path

from common.testing import heading_levels, parse_html

PRIVACY = Path(__file__).resolve().parent.parent / "landing" / "privacy.html"
LANGS = ["sr", "en", "ru"]


def _page():
    return parse_html(PRIVACY.read_text(encoding="utf-8"))


def test_each_language_section_declares_its_language():
    page = _page()
    assert page.find("html").attrs["lang"] == "sr"
    sections = page.find("main").find_all("section")
    assert [(s.attrs["id"], s.attrs.get("lang")) for s in sections] == [(x, x) for x in LANGS]
    links = page.find("nav").find_all("a")
    assert [(a.text(), a.attrs.get("lang")) for a in links] == [
        ("Srpski", None),  # the page language
        ("English", "en"),
        ("Русский", "ru"),
    ]


def test_headings_never_skip_a_level():
    page = _page()
    levels = heading_levels(page)
    assert levels[0] == 1
    assert all(b <= a + 1 for a, b in zip(levels, levels[1:], strict=False)), levels
    for section in page.find_all("section"):
        first, *rest = heading_levels(section)
        assert first == 1 and rest and set(rest) == {2}, (section.attrs["id"], first, rest)


# --- SERBITO-461: the policy describes the live product, with a named controller --------------

STALE = {
    "sr": "fazi provere interesovanja",
    "en": "demand-validation phase",
    "ru": "фазе проверки спроса",
}


def _section_text(lang):
    return _page().find("section", {"id": lang}).text()


def test_policy_names_the_controller_and_a_business_contact():
    html = PRIVACY.read_text(encoding="utf-8")
    assert "gmail" not in html.lower()
    for lang in LANGS:
        section = _page().find("section", {"id": lang})
        assert "No Handoff" in section.text(), lang
        hrefs = [a.attrs.get("href") for a in section.find_all("a")]
        assert "mailto:support@serbito.rs" in hrefs, lang


def test_policy_lists_the_live_data_flows():
    for lang in LANGS:
        text = _section_text(lang)
        for processor in ("Infobip", "Google Maps", "Google Cloud", "Cloudflare", "Sentry", "Whop"):
            assert processor in text, (lang, processor)
        assert STALE[lang] not in text, lang
