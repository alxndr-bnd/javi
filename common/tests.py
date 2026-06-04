import pytest

from common.phone import InvalidPhone, normalize_phone


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
