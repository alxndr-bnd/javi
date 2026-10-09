"""SERBITO-597: the landing says why Javi beats the alternatives, so search and AI answers cite it.

- A short "What is Javi" facts block sits right after the hero: what, for whom, price, where,
  who makes it. AI answers quote such blocks.
- A "Why Javi" section lists the strengths and compares Javi with two categories: foreign
  dispatch tools and delivery platforms. The table names no competitor product (unfair
  advertising risk); it compares categories only.
- The FAQ answers the questions people ask AI assistants; config/test_seo.py keeps the FAQPage
  JSON-LD equal to the visible FAQ.
- /llms.txt states the same facts in English and Serbian, as text/plain. No page links to it;
  robots.txt allows it.
- Only true claims: no live GPS of the courier, no multi-stop routes, no shop-platform plugins.
"""

import re
from urllib.robotparser import RobotFileParser

import pytest

from common.testing import LANDING_DIR, LANDING_PAGES, parse_html

LANGS = list(LANDING_PAGES)
SITE = "https://javi.serbito.rs"

# Competitor products from the research (Basic Memory, 2026-10-09). The table and llms.txt
# compare categories, so none of these names appears there.
COMPETITORS = (
    "Shipday",
    "Spoke",
    "Track-POD",
    "Circuit",
    "BulkGate",
    "Yandex",
    "Glovo",
    "Wolt Drive",
)

FACTS_TERMS = {
    "sr": ("Viber", "SMS", "30 €", "30 dana", "Srbij", "No Handoff"),
    "en": ("Viber", "SMS", "30 €", "30 days", "Serbia", "No Handoff"),
    "ru": ("Viber", "SMS", "30 €", "30 дней", "Серби", "No Handoff"),
}
AI_QUESTIONS = {
    "sr": (
        "Kako da kupci znaju kada stiže dostava?",
        "Kako da pošaljem Viber obaveštenja kupcima online prodavnice?",
        "Postoji li u Srbiji alternativa stranim alatima za praćenje dostave?",
    ),
    "en": (
        "How do customers know when the delivery arrives?",
        "How do I send Viber notifications to my online shop's customers?",
        "Is there an alternative to foreign delivery tracking tools in Serbia?",
    ),
    "ru": (
        "Как покупателю узнать, когда приедет доставка?",
        "Как отправлять покупателям интернет-магазина уведомления в Viber?",
        "Есть ли в Сербии альтернатива зарубежным сервисам отслеживания доставки?",
    ),
}
COLUMNS = {
    "sr": ["Javi", "Strani alati za dispečing", "Platforme za dostavu"],
    "en": ["Javi", "Foreign dispatch tools", "Delivery platforms"],
    "ru": ["Javi", "Зарубежные сервисы диспетчеризации", "Платформы доставки"],
}
# Claims Javi cannot make (owner, 2026-10-09). The pages say so only in the negative.
FALSE_CLAIMS = re.compile(r"(?i)(GPS|multi-stop|Shopify|WooCommerce)")


def _page(lang):
    return parse_html(LANDING_PAGES[lang][1].read_text(encoding="utf-8"))


def _sections(lang):
    main = _page(lang).find("main")
    return [n for n in main.children if not isinstance(n, str) and n.tag == "section"]


@pytest.mark.parametrize("lang", LANGS)
def test_facts_block_follows_the_hero(lang):
    sections = _sections(lang)
    assert "hero" in sections[0].attrs.get("class", "")
    facts = sections[1]
    assert facts.attrs["id"] == "sta-je-javi"
    text = facts.text()
    for term in FACTS_TERMS[lang]:
        assert term in text, term
    assert len(facts.find_all("dt")) == len(facts.find_all("dd")) == 5


@pytest.mark.parametrize("lang", LANGS)
def test_why_section_lists_strengths_and_compares_categories(lang):
    why = _page(lang).find("section", {"id": "zasto"})
    assert len(why.find("ul", {"class": "why"}).find_all("li")) == 8
    table = why.find("table", {"class": "compare"})
    header = [th.text() for th in table.find("thead").find_all("th")]
    assert header == COLUMNS[lang]
    for row in table.find("tbody").find_all("tr"):
        assert len(row.find_all("th")) == 1
        cells = row.find_all("td")
        # On a phone each cell shows its column name (CSS ::before reads data-label).
        assert [td.attrs["data-label"] for td in cells] == COLUMNS[lang]
    for name in COMPETITORS:
        assert name not in table.text(), name


@pytest.mark.parametrize("lang", LANGS)
def test_faq_answers_the_questions_people_ask_ai(lang):
    faq = _page(lang).find("div", {"class": "faq"})
    questions = [h.text() for h in faq.find_all("h3")]
    for question in AI_QUESTIONS[lang]:
        assert question in questions, question


@pytest.mark.parametrize("lang", LANGS)
def test_no_competitor_names_and_no_false_claims(lang):
    text = _page(lang).find("main").text()
    for name in COMPETITORS:
        assert name not in text, name
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if FALSE_CLAIMS.search(sentence):
            # Only "Javi does not …" / "No, …" sentences may name these things.
            assert re.search(r"\b(ne|not|No|Ne|не|Нет)\b", sentence), sentence


def test_llms_txt_is_served_as_plain_text(client):
    resp = client.get("/llms.txt")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert "utf-8" in resp["Content-Type"]


def test_llms_txt_states_the_landing_facts():
    text = (LANDING_DIR / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Javi\n\n> ")
    for fact in (
        "30 € per month per shop",
        "Viber and SMS messages are included",
        "After 30 days, payment is required to continue.",
        "Viber i SMS poruke su uključene u cenu.",
        "Posle 30 dana za nastavak je potrebno plaćanje. Bez plaćanja ostaju probni limiti.",
        "No Handoff",
        f"{SITE}/",
        f"{SITE}/en/",
        f"{SITE}/ru/",
    ):
        assert fact in text, fact
    for name in COMPETITORS:
        assert name not in text, name


def test_llms_txt_is_allowed_and_not_linked_from_pages():
    robots = RobotFileParser()
    robots.parse((LANDING_DIR / "robots.txt").read_text(encoding="utf-8").splitlines())
    assert robots.can_fetch("*", f"{SITE}/llms.txt")
    for _, file in LANDING_PAGES.values():
        assert "llms.txt" not in file.read_text(encoding="utf-8")
