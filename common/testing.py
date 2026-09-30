"""A tiny HTML tree for template-structure tests (headings, landmarks, aria), stdlib only."""

from __future__ import annotations

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
