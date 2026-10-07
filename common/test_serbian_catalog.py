"""SERBITO-356 (5a/5c): the Serbian (Latin) catalogue is complete, compiled and unambiguous.

Before: 67 empty and 13 fuzzy entries (login, register and API keys showed in English), and
"Odjava" meant both "Sign out" and "Unsubscribe".
"""

import gettext
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import translation

from deliveries.models import Delivery, Shop, TrackingToken

PO = Path(__file__).resolve().parent.parent / "locale" / "sr_Latn" / "LC_MESSAGES" / "django.po"
CYRILLIC = re.compile("[Ѐ-ӿ]")


def _unquote(lines):
    return "".join(
        bytes(line.strip()[1:-1], "utf-8").decode("unicode_escape").encode("latin-1").decode()
        for line in lines
    )


def _entries():
    """(flags, msgid, msgstrs) for every entry of the .po, header excluded."""
    for block in PO.read_text(encoding="utf-8").split("\n\n"):
        flags, fields, current = "", {}, None
        for line in block.splitlines():
            if line.startswith("#,"):
                flags += line
            elif line.startswith("#"):
                continue
            elif line.startswith('"'):
                fields[current].append(line)
            else:
                current, _, rest = line.partition(" ")
                fields[current] = [rest]
        if "msgid" in fields and _unquote(fields["msgid"]):
            strs = [_unquote(v) for k, v in fields.items() if k.startswith("msgstr")]
            yield flags, _unquote(fields["msgid"]), strs


def test_no_empty_or_fuzzy_entries():
    entries = list(_entries())
    assert len(entries) > 200
    assert [m for f, m, _s in entries if "fuzzy" in f] == []
    assert [m for _f, m, s in entries if not all(s)] == []


def test_latin_script_only():
    assert [s for _f, _m, strs in _entries() for s in strs if CYRILLIC.search(s)] == []


def test_mo_is_compiled_from_this_po():
    with open(PO.with_suffix(".mo"), "rb") as fh:
        mo = gettext.GNUTranslations(fh)
    stale = [m for _f, m, strs in _entries() if len(strs) == 1 and mo.gettext(m) != strs[0]]
    assert stale == [], "run: manage.py compilemessages -l sr_Latn"


def test_sign_out_and_unsubscribe_are_different_words():
    with translation.override("sr-latn"):
        sign_out = translation.gettext("Sign out")
        unsubscribe = translation.gettext("Unsubscribe")
        unsubscribe_long = translation.gettext("Unsubscribe from notifications")
    assert sign_out == "Odjavi se"
    assert unsubscribe == unsubscribe_long == "Otkaži obaveštenja"
    assert "Odjav" not in unsubscribe


@pytest.mark.django_db
def test_auth_pages_are_serbian(client):
    for path, text in [("/accounts/login/", "Lozinka"), ("/accounts/register/", "Napravite nalog")]:
        body = client.get(path, HTTP_ACCEPT_LANGUAGE="sr").content.decode()
        assert text in body, path


@pytest.mark.django_db
def test_menu_and_unsubscribe_page_use_their_own_words(client):
    user = get_user_model().objects.create_user(email="w@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pekara")
    delivery = Delivery.objects.create(
        shop=shop,
        recipient_name="A",
        recipient_phone="+381641234567",
        dest_address="a",
        status=Delivery.Status.ON_THE_WAY,
    )
    token = TrackingToken.objects.create(delivery=delivery)
    client.force_login(user)
    assert "Odjavi se" in client.get("/app/", HTTP_ACCEPT_LANGUAGE="sr").content.decode()
    page = client.get(f"/t/{token.token}/odjava/").content.decode()
    assert "Otkazati obaveštenja?" in page and "Odjav" not in page
