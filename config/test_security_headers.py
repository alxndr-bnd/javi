"""CSP on Django pages (JAVI-12) and fail-closed production settings (JAVI-11), SERBITO-362."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from config.checks import assert_safe_to_serve
from deliveries.models import Shop

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
ENFORCE = "Content-Security-Policy"
REPORT_ONLY = "Content-Security-Policy-Report-Only"


@pytest.fixture
def owner(client):
    user = get_user_model().objects.create_user(email="csp@shop.rs", password="pass12345")
    Shop.objects.create(owner=user, name="CSP Shop")
    client.force_login(user)
    return user


def _directives(header: str) -> dict[str, str]:
    return dict(part.strip().split(" ", 1) for part in header.split(";"))


def test_dashboard_has_baseline_csp_and_full_report_only_policy(client, owner):
    resp = client.get("/app/")
    enforced = _directives(resp[ENFORCE])
    assert enforced["object-src"] == "'none'"
    assert enforced["base-uri"] == "'self'"
    assert enforced["frame-ancestors"] == "'none'"
    assert enforced["form-action"] == "'self'"
    full = _directives(resp[REPORT_ONLY])
    assert full["default-src"] == "'self'"
    assert "'unsafe-inline'" not in full["script-src"]
    assert "https://www.googletagmanager.com" in full["script-src"]


def test_every_script_on_the_dashboard_carries_the_nonce(client, owner):
    resp = client.get("/app/")
    nonce = re.search(r"'nonce-([^']+)'", resp[REPORT_ONLY]).group(1)
    body = resp.content.decode()
    scripts = re.findall(r"<script\b[^>]*>", body)
    assert len(scripts) >= 4  # consent default, gtag, data-confirm, page script, consent.js
    for tag in scripts:
        assert f'nonce="{nonce}"' in tag, tag


def test_nonce_differs_per_response(client, owner):
    first = client.get("/app/")[REPORT_ONLY]
    second = client.get("/app/")[REPORT_ONLY]
    assert first != second


def test_enforced_mode_switches_full_policy_on(settings, client, owner):
    settings.SECURE_CSP = settings.CSP_FULL_POLICY
    settings.SECURE_CSP_REPORT_ONLY = {}
    resp = client.get("/app/")
    assert "'nonce-" in resp[ENFORCE] and REPORT_ONLY not in resp


def test_tracking_and_login_pages_have_csp(client):
    resp = client.get("/accounts/login/")
    assert "frame-ancestors 'none'" in resp[ENFORCE]


@pytest.mark.parametrize("path", ["/api/docs/", "/api/redoc/"])
def test_third_party_api_docs_are_exempt(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert ENFORCE not in resp and REPORT_ONLY not in resp


def test_templates_have_no_inline_event_handlers_or_bare_scripts():
    """Inline handlers (onclick=, onsubmit=) cannot carry a nonce — use data-* + a script."""
    for path in [*ROOT.glob("templates/**/*.html"), *ROOT.glob("*/templates/**/*.html")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=", text), path
        for tag in re.findall(r"<script\b[^>]*>", text):
            assert 'nonce="{{ csp_nonce }}"' in tag, (path, tag)


# --- JAVI-11: the web server refuses unsafe settings ---


def _settings(**overrides):
    base = {
        "DEBUG": False,
        "SECRET_KEY": "a-real-secret",
        "INSECURE_SECRET_KEY": "django-insecure-dev-only-change-me",
        "ALLOWED_HOSTS": ["javi.serbito.rs"],
    }
    return SimpleNamespace(**{**base, **overrides})


def test_safe_production_settings_pass():
    assert_safe_to_serve(_settings())


@pytest.mark.parametrize(
    "overrides",
    [
        {"SECRET_KEY": ""},
        {"SECRET_KEY": "django-insecure-dev-only-change-me"},
        {"ALLOWED_HOSTS": []},
        {"ALLOWED_HOSTS": ["*"]},
    ],
)
def test_missing_secret_or_hosts_refuse_to_serve(overrides):
    with pytest.raises(ImproperlyConfigured):
        assert_safe_to_serve(_settings(**overrides))


def test_debug_allows_dev_defaults():
    assert_safe_to_serve(_settings(DEBUG=True, SECRET_KEY="", ALLOWED_HOSTS=[]))


def test_allowed_hosts_default_is_empty_not_wildcard(settings):
    # Tests run without ALLOWED_HOSTS in the env; Django's test setup adds only "testserver".
    assert "*" not in settings.ALLOWED_HOSTS


def test_wsgi_entrypoint_runs_the_check():
    text = (ROOT / "config" / "wsgi.py").read_text(encoding="utf-8")
    assert "assert_safe_to_serve(settings)" in text


# --- SERBITO-348: the static landing (WhiteNoise) cannot be framed ---


@pytest.mark.parametrize("path", ["/", "/en/", "/ru/", "/privacy.html"])
def test_landing_html_forbids_framing(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp["X-Frame-Options"] == "DENY"
    assert resp[ENFORCE] == "frame-ancestors 'none'"
    assert REPORT_ONLY not in resp  # no policy that could break the lead form or its scripts


def test_landing_assets_get_no_framing_headers(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "X-Frame-Options" not in resp and ENFORCE not in resp


def test_django_pages_keep_their_own_policy(client):
    # The WhiteNoise hook must not replace what Django's middleware sends on its pages.
    resp = client.get("/accounts/login/")
    assert resp[ENFORCE] != "frame-ancestors 'none'"
    assert "form-action 'self'" in resp[ENFORCE]
