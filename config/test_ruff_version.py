"""One ruff version for the pre-commit hook and for `uv run ruff` in CI (SERBITO-552)."""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_uv_ruff_is_the_pre_commit_ruff():
    hooks = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text("utf-8"))
    (rev,) = [r["rev"] for r in hooks["repos"] if r["repo"].endswith("/ruff-pre-commit")]
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["dependency-groups"]["dev"]
    (pin,) = [d for d in dev if re.match(r"ruff\b", d)]
    assert pin == f"ruff=={rev.removeprefix('v')}", (pin, rev)
    lock = (ROOT / "uv.lock").read_text("utf-8")
    assert f'name = "ruff"\nversion = "{rev.removeprefix("v")}"' in lock
