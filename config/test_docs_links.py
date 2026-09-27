"""SERBITO-317: every link to a SETUP_CICD.md#anchor resolves to a heading in that file.

SETUP_CICD.md was rewritten in English (SERBITO-294) and older docs kept its Russian anchors,
which GitHub silently opens at the top of the page. Anchors follow GitHub's heading slugs.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "SETUP_CICD.md"
# [text](path/SETUP_CICD.md#anchor), plus the file's own [text](#anchor) table of contents.
EXTERNAL_LINK = re.compile(r"SETUP_CICD\.md#([^)\s\"'>]+)")
LOCAL_LINK = re.compile(r"\]\(#([^)\s]+)\)")


def github_slug(heading: str) -> str:
    """GitHub's anchor for a heading: drop markup and punctuation, lowercase, spaces -> '-'."""
    text = re.sub(r"[`*_~]|\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def heading_anchors(markdown: str) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    in_code = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        match = None if in_code else re.match(r"#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            slug = github_slug(match[1])
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def _links() -> list[tuple[str, str]]:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    links = []
    for name in tracked:
        path = ROOT / name
        if not path.is_file() or path.suffix not in {".md", ".py", ".html", ".yaml", ".yml"}:
            continue
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        links += [(name, anchor) for anchor in EXTERNAL_LINK.findall(text)]
        if path == SETUP:
            links += [(name, anchor) for anchor in LOCAL_LINK.findall(text)]
    return links


def test_slug_rules():
    assert github_slug("5. DNS: javi.serbito.rs") == "5-dns-javiserbitors"
    assert github_slug("3.2. Artifact Registry repository `javi`") == (
        "32-artifact-registry-repository-javi"
    )
    assert github_slug("8. Runtime: Cloud SQL, secrets, env") == "8-runtime-cloud-sql-secrets-env"


def test_repo_links_to_setup_cicd_exist():
    # The plan links into SETUP_CICD.md, so an empty scan would mean the scan is broken.
    assert any(name.startswith("docs/") for name, _ in _links())


@pytest.mark.parametrize(("source", "anchor"), _links())
def test_setup_cicd_anchor_resolves(source, anchor):
    assert anchor in heading_anchors(SETUP.read_text(encoding="utf-8")), (
        f"{source} links to SETUP_CICD.md#{anchor}, which is not a heading there"
    )
