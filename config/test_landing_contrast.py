"""SERBITO-278: every link on the landing has an explicit colour with WCAG AA contrast (4.5:1).

A link with no colour rule falls back to the browser's #0000ee, about 2:1 on the dark --bg;
that is how the footer privacy link went unnoticed. The test reads the landing's inline <style>,
resolves which rule colours each <a> (descendant selectors, specificity, source order) and checks
the text colour against the link's own background, or --bg when it has none.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

LANDING = Path(__file__).resolve().parent.parent / "landing" / "index.html"
AA = 4.5
HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
SIMPLE = re.compile(r"^([a-z][a-z0-9]*)?((?:[.#][\w-]+)*)$")


def _hex6(colour):
    return colour if len(colour) == 7 else "#" + "".join(c * 2 for c in colour[1:])


def _luminance(hex_colour):
    hex_colour = _hex6(hex_colour)
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg, bg):
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


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


def _parse():
    page = _Landing()
    page.feed(LANDING.read_text(encoding="utf-8"))
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


LINKS, RULES, PAGE_BG = _parse()


def test_landing_has_links():
    hrefs = [href for href, _ in LINKS]
    assert "/privacy.html" in hrefs
    assert len(hrefs) >= 7


@pytest.mark.parametrize("href,chain", LINKS, ids=[h for h, _ in LINKS])
def test_every_landing_link_has_aa_contrast(href, chain):
    colour = _winning("color", chain, RULES)
    assert colour, f"{href}: no colour rule, falls back to the browser's default blue"
    [fg] = HEX.findall(colour)
    background = _winning("background", chain, RULES) or _winning("background-color", chain, RULES)
    backgrounds = HEX.findall(background or "") or [PAGE_BG]
    for bg in backgrounds:
        ratio = contrast(fg, bg)
        assert ratio >= AA, f"{href}: {fg} on {bg} = {ratio:.2f}:1, needs {AA}:1"


def test_privacy_link_matches_other_footer_links():
    footer = [chain for href, chain in LINKS if any(n[0] == "footer" for n in chain)]
    colours = {_winning("color", chain, RULES) for chain in footer}
    assert len(footer) == 5
    assert len(colours) == 1
