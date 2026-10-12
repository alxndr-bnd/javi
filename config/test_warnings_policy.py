"""Warnings are failures (SERBITO-613): the gate fails on a warning, not only on an error."""

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PYTEST = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["tool"]["pytest"]
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yaml").read_text("utf-8"))
RUNS = "\n".join(step.get("run", "") for step in CI["jobs"]["verify"]["steps"])


def test_every_warning_fails_a_test():
    rules = PYTEST["ini_options"]["filterwarnings"]
    assert rules[0] == "error"
    # No blanket ignore of a whole category: an ignore names a message and a module.
    assert all(rule.count(":") >= 3 for rule in rules[1:]), rules


def test_ci_fails_on_check_warnings_vulnerabilities_and_dockerfile_lint():
    assert "manage.py check --fail-level WARNING" in RUNS
    assert "pip-audit --strict --require-hashes" in RUNS
    assert "docker build --check ." in RUNS
    release = (ROOT / "scripts" / "release_minor.sh").read_text("utf-8")
    assert "manage.py check --fail-level WARNING" in release
