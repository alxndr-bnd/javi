"""SERBITO-398: the template-test helper reports a missing element by name, also under -O."""

import subprocess
import sys
from pathlib import Path

import pytest

from common.testing import parse_html

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_find_names_the_missing_element():
    tree = parse_html("<main><h1>Javi</h1></main>")
    assert tree.find("h1").text() == "Javi"
    with pytest.raises(AssertionError, match=r"no <nav \{'id': 'menu'\}>"):
        tree.find("nav", {"id": "menu"})


def test_find_still_raises_when_python_drops_asserts():
    # `python -O` removes `assert` statements; the helper must not depend on them.
    code = (
        "from common.testing import parse_html\n"
        "try:\n"
        "    parse_html('<p></p>').find('nav')\n"
        "except AssertionError as error:\n"
        "    print('raised:', error)\n"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "raised: no <nav >"
