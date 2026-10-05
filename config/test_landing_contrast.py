"""SERBITO-278: every link on the landing has an explicit colour with WCAG AA contrast (4.5:1).

A link with no colour rule falls back to the browser's #0000ee, about 2:1 on the dark --bg;
that is how the footer privacy link went unnoticed. The test reads the landing's inline <style>,
resolves which rule colours each <a> (descendant selectors, specificity, source order) and checks
the text colour against the link's own background, or --bg when it has none. Every language page
(SERBITO-459) is checked: their links differ (language switch), their CSS must not.
"""

import re
from html.parser import HTMLParser

import pytest

from common.testing import LANDING_PAGES, contrast

AA = 4.5
HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
SIMPLE = re.compile(r"^([a-z][a-z0-9]*)?((?:[.#][\w-]+)*)$")


class _Landing(HTMLParser):
    """Collects the inline CSS and, for every <a>, its ancestor chain (tag, id, classes)."""

    def __init__(self):
        super().__init__()
        self.css, self.links, self._stack, self._in_style = [], [], [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        node = (tag, a.get("id"), set((a.get("class") or "").split()))
        if tag == "style":
            self._in_style = True
        if tag == "a":
            self.links.append((a.get("href"), [*self._stack, node]))
        elif tag not in {"meta", "link", "br", "img", "input"}:
            self._stack.append(node)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        if tag != "a" and self._stack and self._stack[-1][0] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_style:
            self.css.append(data)


def _parse(file):
    page = _Landing()
    page.feed(file.read_text(encoding="utf-8"))
    css = re.sub(r"/\*.*?\*/", "", "".join(page.css), flags=re.S)
    vars_ = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", css))

    def resolve(value):
        return re.sub(r"var\((--[\w-]+)\)", lambda m: vars_[m.group(1)].strip(), value)

    rules = []  # (selector, {prop: value}, source order)
    for order, (selectors, body) in enumerate(re.findall(r"([^{}]+)\{([^{}]*)\}", css)):
        decls = dict(
            (k.strip(), resolve(v.strip()))
            for k, v in (d.split(":", 1) for d in body.split(";") if ":" in d)
        )
        for sel in selectors.split(","):
            rules.append((sel.strip(), decls, order))
    return page.links, rules, resolve("var(--bg)")


def _matches_simple(part, node):
    m = SIMPLE.match(part)
    if not m:
        return False  # pseudo-classes, attribute and child selectors never style a link here
    tag, _id, classes = node
    if m.group(1) and m.group(1) != tag:
        return False
    for kind, name in re.findall(r"([.#])([\w-]+)", m.group(2)):
        if (kind == "." and name not in classes) or (kind == "#" and name != _id):
            return False
    return True


def _matches(selector, chain):
    *ancestors, last = selector.split()
    if not _matches_simple(last, chain[-1]):
        return False
    rest = chain[:-1]
    for part in reversed(ancestors):
        while rest and not _matches_simple(part, rest[-1]):
            rest = rest[:-1]
        if not rest:
            return False
        rest = rest[:-1]
    return True


def _specificity(selector):
    return (
        selector.count("#"),
        selector.count("."),
        sum(1 for p in selector.split() if SIMPLE.match(p) and SIMPLE.match(p).group(1)),
    )


def _winning(prop, chain, rules):
    hits = [
        (_specificity(s), order, d[prop])
        for s, d, order in rules
        if prop in d and _matches(s, chain)
    ]
    return max(hits)[2] if hits else None


PAGES = {lang: _parse(file) for lang, (_, file) in LANDING_PAGES.items()}
LINKS = [(lang, href, chain) for lang, (links, _, _) in PAGES.items() for href, chain in links]


@pytest.mark.parametrize("lang", list(PAGES))
def test_landing_has_links(lang):
    hrefs = [href for href, _ in PAGES[lang][0]]
    assert "/privacy.html" in hrefs
    assert {"/", "/en/", "/ru/"} <= set(hrefs)  # the language switch
    assert len(hrefs) >= 10


@pytest.mark.parametrize("lang,href,chain", LINKS, ids=[f"{lang}:{h}" for lang, h, _ in LINKS])
def test_every_landing_link_has_aa_contrast(lang, href, chain):
    _, rules, page_bg = PAGES[lang]
    colour = _winning("color", chain, rules)
    assert colour, f"{href}: no colour rule, falls back to the browser's default blue"
    [fg] = HEX.findall(colour)
    background = _winning("background", chain, rules) or _winning("background-color", chain, rules)
    backgrounds = HEX.findall(background or "") or [page_bg]
    for bg in backgrounds:
        ratio = contrast(fg, bg)
        assert ratio >= AA, f"{href}: {fg} on {bg} = {ratio:.2f}:1, needs {AA}:1"


@pytest.mark.parametrize("lang", list(PAGES))
def test_privacy_link_matches_other_footer_links(lang):
    links, rules, _ = PAGES[lang]
    footer = [chain for href, chain in links if any(n[0] == "footer" for n in chain)]
    colours = {_winning("color", chain, rules) for chain in footer}
    assert len(footer) == 5
    assert len(colours) == 1
