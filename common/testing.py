"""Stdlib-only helpers for template tests: a tiny HTML tree (headings, landmarks, aria), CSS rule
lookup and WCAG contrast ratios."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


@dataclass(eq=False)  # identity: nodes link to their parent, so field equality would recurse
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    parent: Node | None = field(default=None, repr=False)
    children: list[Node | str] = field(default_factory=list, repr=False)

    def iter(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, attrs: dict[str, str] | None = None) -> list[Node]:
        """Descendants with this tag (any if None) whose attributes include ``attrs``."""
        attrs = attrs or {}
        return [
            n
            for n in self.iter()
            if (tag is None or n.tag == tag) and all(n.attrs.get(k) == v for k, v in attrs.items())
        ]

    def find(self, tag: str | None = None, attrs: dict[str, str] | None = None) -> Node:
        found = self.find_all(tag, attrs)
        assert found, f"no <{tag} {attrs or ''}>"
        return found[0]

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        parts = [c if isinstance(c, str) else c.text() for c in self.children]
        return " ".join(" ".join(parts).split())

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node("#document")

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse_html(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def heading_levels(root: Node) -> list[int]:
    """h1–h6 levels in document order."""
    return [int(n.tag[1]) for n in root.iter() if n.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}]


def _luminance(hex_colour: str) -> float:
    if len(hex_colour) == 4:
        hex_colour = "#" + "".join(c * 2 for c in hex_colour[1:])
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio of two #rgb/#rrggbb colours."""
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def css_declarations(css: str, selector: str) -> dict[str, str]:
    """Declarations of every rule whose selector list includes ``selector`` exactly, in source
    order, with ``var(--x)`` resolved from the custom properties declared anywhere in ``css``."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    variables = {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", css)}
    found: dict[str, str] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in (s.strip() for s in selectors.split(",")):
            for decl in body.split(";"):
                if ":" in decl:
                    prop, value = decl.split(":", 1)
                    found[prop.strip()] = re.sub(
                        r"var\((--[\w-]+)\)", lambda m: variables[m.group(1)], value.strip()
                    )
    return found
