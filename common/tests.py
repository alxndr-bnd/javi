import re
from datetime import datetime
from pathlib import Path

import pytest

from common.phone import InvalidPhone, normalize_phone
from common.testing import contrast, css_declarations
from common.timewindow import BELGRADE, clamp_to_window, rating_send_time


def test_clamp_before_window_moves_to_8am():
    dt = datetime(2026, 6, 4, 6, 0, tzinfo=BELGRADE)
    out = clamp_to_window(dt)
    assert (out.date(), out.hour, out.minute) == (dt.date(), 8, 0)


def test_clamp_after_window_moves_to_next_day_8am():
    dt = datetime(2026, 6, 4, 23, 0, tzinfo=BELGRADE)
    out = clamp_to_window(dt)
    assert out.day == 5 and out.hour == 8


def test_clamp_inside_window_unchanged():
    dt = datetime(2026, 6, 4, 15, 0, tzinfo=BELGRADE)
    assert clamp_to_window(dt).hour == 15


def test_rating_send_time_adds_30_min_inside_window():
    dt = datetime(2026, 6, 4, 15, 0, tzinfo=BELGRADE)
    out = rating_send_time(dt)
    assert (out.hour, out.minute) == (15, 30)


def test_rs_mobile_normalized_to_e164():
    r = normalize_phone("064 123 4567")
    assert r.e164 == "+381641234567"
    assert r.is_mobile is True
    assert r.is_rs is True
    assert r.is_risky is False


def test_rs_fixed_line_is_risky_not_mobile():
    r = normalize_phone("011 3033100")
    assert r.e164 == "+381113033100"
    assert r.is_mobile is False
    assert r.is_rs is True
    assert r.is_risky is True


def test_foreign_number_is_risky():
    r = normalize_phone("+49 1512 3456789")
    assert r.is_rs is False
    assert r.is_risky is True


@pytest.mark.parametrize("raw", ["abc", "12"])
def test_invalid_phone_raises(raw):
    with pytest.raises(InvalidPhone):
        normalize_phone(raw)


# --- WCAG 1.4.11 (SERBITO-352): app form-field borders (login, register, shop profile, new
# delivery) contrast at least 3:1 with the field's white fill and the page background ---

APP_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "app.css"


def test_app_field_border_has_non_text_contrast():
    css = APP_CSS.read_text(encoding="utf-8")
    field = css_declarations(css, ".field input")
    [border] = re.findall(r"#[0-9a-fA-F]{3,6}\b", field["border"])
    root = css_declarations(css, ":root")
    for bg in (field["background"], root["--surface"], root["--bg"]):
        ratio = contrast(border, bg)
        assert ratio >= 3.0, f"{border} on {bg} = {ratio:.2f}:1"
