"""Очистка названия магазина перед вставкой в Viber/SMS (SERBITO-345).

Название магазина — единственный текст клиента в сообщении, которое уходит с доверенного
sender ID. Без очистки оно превращается в канал смишинга: «Pošta: platite carinu na evil.com».
Поэтому в сообщении (и в формах) название — без ссылок, доменов, телефонных номеров,
управляющих/невидимых символов и кавычек (ими оно ограничено в шаблоне), не длиннее
SHOP_NAME_MAX_LEN.
"""

from __future__ import annotations

import re
import unicodedata

# Лимит длины названия в формах и в тексте сообщения.
SHOP_NAME_MAX_LEN = 40

# Схема (http://, viber://, …) или www. — вместе с хвостом до пробела.
_URL_RE = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.\-]*://|\bwww\.)\S*")
# Домен/почта: метка.метка…tld (tld — минимум 2 буквы), с хвостом (/path, ?q=…).
_DOMAIN_RE = re.compile(r"(?i)\S*\b[\w\-]+(?:\.[\w\-]+)*\.[a-z]{2,}\b\S*")
# Кандидат в телефонный номер: цифры с разделителями; режем, если цифр 6 и больше.
_PHONE_RE = re.compile(r"[+(]?\d[\d\s().\-/]*\d\)?")
_PHONE_MIN_DIGITS = 6
# Кавычки — ими название ограничено в шаблоне сообщения, «выйти» из них нельзя.
_QUOTES = str.maketrans("", "", "\"«»„“”‟〝〞＂<>")
# Unicode-категории на удаление: управляющие, форматные (bidi-override, zero-width),
# приватные, суррогаты, неназначенные.
_DROP_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}


def _strip_phone(match: re.Match) -> str:
    digits = sum(ch.isdigit() for ch in match.group(0))
    return " " if digits >= _PHONE_MIN_DIGITS else match.group(0)


def _normalize(value: str) -> str:
    """NFKC (полноширинные «．»/«ｗｗｗ» → ASCII) + пробельные символы → пробел,
    без управляющих/невидимых символов, схлопнутые пробелы."""
    value = unicodedata.normalize("NFKC", value or "")
    out = []
    for ch in value:
        cat = unicodedata.category(ch)
        if ch.isspace() or cat in ("Zs", "Zl", "Zp"):
            out.append(" ")
        elif cat not in _DROP_CATEGORIES:
            out.append(ch)
    return " ".join("".join(out).split())


def sanitize_shop_name(value: str, max_len: int | None = SHOP_NAME_MAX_LEN) -> str:
    """Название магазина, безопасное для текста сообщения.

    Убирает URL, домены/почту, телефонные номера (6+ цифр), кавычки и управляющие символы,
    схлопывает пробелы и обрезает до `max_len` (None — без обрезки). Может вернуть "".
    """
    value = _normalize(value)
    value = _URL_RE.sub(" ", value)
    value = _DOMAIN_RE.sub(" ", value)
    value = _PHONE_RE.sub(_strip_phone, value)
    value = value.translate(_QUOTES)
    value = " ".join(value.split())
    if max_len is not None and len(value) > max_len:
        value = value[:max_len].rstrip()
    return value


def shop_name_is_clean(value: str) -> bool:
    """True, если очистка ничего не выкинула бы (кроме нормализации пробелов/NFKC)."""
    normalized = _normalize(value)
    return bool(normalized) and sanitize_shop_name(value, max_len=None) == normalized


def clean_shop_name(value: str) -> str:
    """Валидация названия в формах/API: ссылки, номера, кавычки → ошибка; иначе нормализованное.

    Бросает django ValidationError (DRF тоже её понимает в validators/validate_*).
    """
    from django.core.exceptions import ValidationError
    from django.utils.translation import gettext

    if not shop_name_is_clean(value):
        raise ValidationError(
            gettext(
                "Store name can't contain links, email addresses, phone numbers "
                "or quotation marks."
            ),
            code="shop_name_unsafe",
        )
    return _normalize(value)
