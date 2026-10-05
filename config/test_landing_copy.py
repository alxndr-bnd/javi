"""SERBITO-356 (J11): the landing's offer is a statement, not a question, in every language."""

import pytest

from common.testing import LANDING_PAGES, parse_html


@pytest.mark.parametrize("lang", list(LANDING_PAGES))
def test_offer_heading_is_a_statement(lang):
    page = parse_html(LANDING_PAGES[lang][1].read_text(encoding="utf-8"))
    text = page.find("p", {"class": "q"}).text()
    assert not text.rstrip().endswith("?"), text
    assert text.startswith("Javi ")
