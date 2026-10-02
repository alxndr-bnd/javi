"""SERBITO-356 (J11): the landing's offer is a statement, not a question, in every language."""

import re
from pathlib import Path

import pytest

LANDING = (Path(__file__).resolve().parent.parent / "landing" / "index.html").read_text(
    encoding="utf-8"
)


def _offer(lang):
    block = LANDING[LANDING.index(f"  {lang}:{{") :]
    return re.search(r"offer_q:'([^']*)'", block).group(1)


@pytest.mark.parametrize("lang", ["sr", "en", "ru"])
def test_offer_heading_is_a_statement(lang):
    text = _offer(lang)
    assert not text.rstrip().endswith("?"), text
    assert text.startswith("Javi ")


def test_static_offer_matches_serbian():
    static = re.search(r'<p class="q" data-i18n="offer_q">(.*?)</p>', LANDING).group(1)
    assert static == _offer("sr")
