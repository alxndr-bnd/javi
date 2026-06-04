"""Нормализация телефонов к E.164 (регион RS по умолчанию) через phonenumbers."""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers

DEFAULT_REGION = "RS"
RS_COUNTRY_CODE = 381


class InvalidPhone(ValueError):
    """Номер не распарсился или невалиден — блокирующая ошибка (FR-4)."""


@dataclass(frozen=True)
class PhoneResult:
    e164: str
    is_mobile: bool
    is_rs: bool

    @property
    def is_risky(self) -> bool:
        """Немобильный или иностранный номер — предупреждение без блока (FR-4)."""
        return not (self.is_mobile and self.is_rs)


def normalize_phone(raw: str, region: str = DEFAULT_REGION) -> PhoneResult:
    """raw → PhoneResult(E.164, ...). Бросает InvalidPhone при невалидном номере."""
    try:
        num = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone(str(exc)) from exc

    if not phonenumbers.is_valid_number(num):
        raise InvalidPhone("number is not valid")

    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    ntype = phonenumbers.number_type(num)
    is_mobile = ntype in (
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    )
    return PhoneResult(e164=e164, is_mobile=is_mobile, is_rs=num.country_code == RS_COUNTRY_CODE)
