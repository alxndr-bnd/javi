"""SERBITO-352: the landing lead form ("Ostavite kontakt") from the SERBITO-330 audit.

- WCAG 1.3.5: fields asking for the visitor's own data name their purpose with an ``autocomplete``
  token, so browsers can fill them. "Email or phone / Viber" is one free-text field; email comes
  first in its label, so it takes ``email`` (a phone number is still accepted).
- Every visible field has a <label for> pointing at it.
- WCAG 1.4.11: field borders contrast at least 3:1 with the field's fill and the form card,
  and the focus rule only fires on focus (it used to paint every <select> as focused).
- SERBITO-595: the form asks only what we need to reply: shop, contact, an optional message
  (the "orders per month" select is gone).
- SERBITO-459: the form is on every language page; they share one stylesheet
  (config/test_seo.py::test_language_pages_share_style_and_script).
"""

import re

import pytest

from common.testing import LANDING_PAGES, contrast, css_declarations, parse_html

NON_TEXT = 3.0
LANGS = list(LANDING_PAGES)


def _page(lang="sr"):
    return LANDING_PAGES[lang][1].read_text(encoding="utf-8")


def _css():
    return "".join(re.findall(r"<style>(.*?)</style>", _page(), flags=re.S))


def _fields(lang):
    form = parse_html(_page(lang)).find("form", {"id": "leadForm"})
    return form, [
        n
        for n in form.iter()
        if n.tag in {"input", "select", "textarea"} and n.attrs.get("type") != "hidden"
    ]


@pytest.mark.parametrize("lang", LANGS)
def test_fields_name_their_purpose_for_autofill(lang):
    _, fields = _fields(lang)
    assert {f.attrs["name"]: f.attrs.get("autocomplete") for f in fields} == {
        "shop": "organization",
        "contact": "email",
        "message": None,
    }


@pytest.mark.parametrize("lang", LANGS)
def test_every_field_has_a_label(lang):
    form, fields = _fields(lang)
    labelled = {label.attrs.get("for") for label in form.find_all("label")}
    assert [f.attrs["id"] for f in fields if f.attrs["id"] not in labelled] == []


@pytest.mark.parametrize("selector", ["input", "select", "textarea"])
def test_field_border_contrasts_with_field_and_card(selector):
    css = _css()
    field = css_declarations(css, selector)
    [border] = re.findall(r"#[0-9a-fA-F]{3,6}\b", field["border"])
    card = css_declarations(css, ".card-form")["background"]
    for bg in (field["background"], card):
        ratio = contrast(border, bg)
        assert ratio >= NON_TEXT, f"{selector} border {border} on {bg} = {ratio:.2f}:1"


def test_focus_style_applies_only_on_focus():
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if "var(--brand)" in body and "border-color" in body:
            parts = [s.strip() for s in selectors.split(",")]
            fields = [p for p in parts if re.match(r"(input|select|textarea)\b", p)]
            assert all(p.endswith(":focus") for p in fields), selectors
