"""Languages of the app and of customer-facing text (SERBITO-356).

The app speaks English and Serbian in Latin script. Django's code for the latter is `sr-latn`
(locale directory `sr_Latn`); plain `sr` would load Django's Cyrillic catalogue, so form
errors came out in Cyrillic inside the Latin UI. An old `sr` cookie or an `sr`/`sr-RS`
Accept-Language still resolves to `sr-latn` through Django's language-variant lookup.
"""

from __future__ import annotations

from django.utils import translation

SERBIAN = "sr-latn"
ENGLISH = "en"

# Language of customer messages and pages (SMS/Viber, /t/ pages). Serbia first: the default.
CUSTOMER_LANGUAGES = [(SERBIAN, "Srpski"), (ENGLISH, "English")]
DEFAULT_CUSTOMER_LANGUAGE = SERBIAN


def html_lang(code: str | None) -> str:
    """Django language code → BCP 47 tag for <html lang> (`sr-latn` → `sr-Latn`)."""
    if not code:
        return ENGLISH
    lang, _, script = code.partition("-")
    return f"{lang}-{script.title()}" if len(script) == 4 else code


def base_language(code: str | None) -> str:
    """Two-letter language (`sr-latn` → `sr`), e.g. for the privacy page's anchors."""
    return (code or ENGLISH).split("-")[0]


def supported_language(code: str | None, default: str = DEFAULT_CUSTOMER_LANGUAGE) -> str:
    """A supported Django code for `code` (`sr`, `sr-RS`, `sr-Latn` → `sr-latn`), or default."""
    if not code:
        return default
    try:
        return translation.get_supported_language_variant(code.strip().lower())
    except LookupError:
        return default


def language(request):
    """Template context: `html_lang` for <html lang> and `lang_base` for the privacy anchor."""
    code = translation.get_language()
    return {"html_lang": html_lang(code), "lang_base": base_language(code)}
