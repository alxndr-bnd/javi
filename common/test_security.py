"""Security helpers (SERBITO-362): DB rate limits, redaction, shared secrets."""

import base64
from datetime import timedelta
from unittest import mock

import pytest
import requests
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone

from common import ratelimit
from common.models import RateLimitCounter
from common.redact import describe_request_error, redact
from common.secrets import request_has_secret, secret_matches
from common.validators import validate_https_url

rf = RequestFactory()


# --- ratelimit ---


@pytest.mark.django_db
def test_hit_allows_up_to_limit_then_refuses():
    results = [ratelimit.hit("t", "1.2.3.4", limit=3, window_seconds=60) for _ in range(4)]
    assert results == [True, True, True, False]
    assert ratelimit.exceeded("t", "1.2.3.4", limit=3, window_seconds=60)
    assert not ratelimit.exceeded("t", "5.6.7.8", limit=3, window_seconds=60)
    assert ratelimit.hit("other-scope", "1.2.3.4", limit=3, window_seconds=60)


@pytest.mark.django_db
def test_counter_resets_in_next_window_and_old_rows_are_removed():
    start = timezone.now().replace(second=0, microsecond=0)
    with mock.patch("common.ratelimit.timezone.now", return_value=start):
        assert ratelimit.hit("t", "ip", limit=1, window_seconds=60)
        assert not ratelimit.hit("t", "ip", limit=1, window_seconds=60)
    later = start + timedelta(minutes=5)
    with mock.patch("common.ratelimit.timezone.now", return_value=later):
        assert ratelimit.hit("t", "ip", limit=1, window_seconds=60)
    assert RateLimitCounter.objects.count() == 1  # the expired window was cleaned up


@pytest.mark.django_db
def test_counter_key_does_not_store_the_identity():
    ratelimit.hit("login-account", "owner@shop.rs", limit=5, window_seconds=60)
    (row,) = RateLimitCounter.objects.all()
    assert "owner" not in row.key and len(row.key) == 64


# --- redaction (JAVI-5) ---


def test_redact_masks_secret_query_values_and_bot_tokens():
    text = (
        "GET https://maps.googleapis.com/maps/api/geocode/json?address=Tajna+5&key=AIzaSECRET "
        "POST https://api.telegram.org/bot123:AA-bb_cc/sendMessage "
        "/webhooks/infobip/reports/?secret=whsec&x=1 idempotency_key=keep"
    )
    out = redact(text)
    assert "AIzaSECRET" not in out and "AA-bb_cc" not in out and "whsec" not in out
    assert "key=[Filtered]" in out and "/bot[Filtered]/sendMessage" in out
    assert "idempotency_key=keep" in out


def test_describe_request_error_never_includes_the_url():
    url = "https://maps.googleapis.com/maps/api/geocode/json?address=Tajna+5&key=AIzaSECRET"
    response = requests.Response()
    response.status_code = 403
    response.url = url
    http_error = requests.HTTPError(f"403 Client Error: for url: {url}", response=response)
    conn_error = requests.ConnectionError(f"Max retries exceeded with url: {url}")
    assert describe_request_error(http_error) == "HTTPError: HTTP 403"
    assert describe_request_error(conn_error) == "ConnectionError"
    assert describe_request_error(ValueError("bad json")) == "ValueError: bad json"


# --- shared secrets (JAVI-3) ---


def test_secret_matches_is_fail_closed():
    assert secret_matches("s", "s")
    assert not secret_matches("s", "")
    assert not secret_matches("", "")
    assert not secret_matches(None, "s")
    assert not secret_matches("wrong", "s")


def _basic(user, password):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.mark.parametrize(
    ("kwargs", "path", "ok"),
    [
        ({"HTTP_X_HOOK": "s3"}, "/", True),
        ({"HTTP_AUTHORIZATION": _basic("infobip", "s3")}, "/", True),
        ({}, "/?secret=s3", True),  # legacy, still accepted
        ({"HTTP_X_HOOK": "nope"}, "/", False),
        ({"HTTP_AUTHORIZATION": _basic("infobip", "nope")}, "/", False),
        ({"HTTP_AUTHORIZATION": "Basic !!!"}, "/", False),
        ({}, "/?secret=nope", False),
        ({}, "/", False),
    ],
)
def test_request_has_secret(kwargs, path, ok):
    assert request_has_secret(rf.post(path, **kwargs), "s3", header="X-Hook") is ok


def test_request_has_secret_rejects_everything_when_unset():
    request = rf.post("/?secret=", HTTP_X_HOOK="")
    assert not request_has_secret(request, "", header="X-Hook")


# --- https-only webhook URLs (JAVI-10) ---


def test_validate_https_url():
    validate_https_url("https://merchant.example/hook")
    validate_https_url("")
    with pytest.raises(ValidationError):
        validate_https_url("http://merchant.example/hook")
