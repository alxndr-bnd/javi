import json
from io import BytesIO
from unittest import mock

import pytest
import sentry_sdk
from django.contrib.auth import get_user_model
from django.core.signals import request_finished, request_started
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.transport import Transport

from config.sentry import init_sentry, scrub_tracking_tokens
from deliveries.models import Delivery, Shop, TrackingToken

DSN = "https://key@o1.ingest.us.sentry.io/1"


def test_not_initialized_without_dsn():
    with mock.patch("config.sentry.sentry_sdk.init") as init:
        assert init_sentry({}) is False
        assert init_sentry({"SENTRY_DSN": "", "SENTRY_RELEASE": "javi@1.2.0"}) is False
    init.assert_not_called()


def test_test_process_has_no_active_sentry_client():
    # settings.py не поднимает Sentry под pytest — события из тестов не уходят.
    assert not sentry_sdk.get_client().is_active()


def test_initialized_on_cloud_run_with_release_and_production_env():
    environ = {"SENTRY_DSN": DSN, "SENTRY_RELEASE": "javi@1.2.0", "K_SERVICE": "javi"}
    with mock.patch("config.sentry.sentry_sdk.init") as init:
        assert init_sentry(environ) is True
    init.assert_called_once()
    kwargs = init.call_args.kwargs
    assert kwargs["dsn"] == DSN
    assert kwargs["release"] == "javi@1.2.0"
    assert kwargs["environment"] == "production"
    assert kwargs["send_default_pii"] is False
    assert kwargs["include_local_variables"] is False  # JAVI-6: no PII from frame locals
    assert kwargs["traces_sample_rate"] == 0.1
    assert any(isinstance(i, DjangoIntegration) for i in kwargs["integrations"])
    assert kwargs["before_send"] is scrub_tracking_tokens
    assert kwargs["before_send_transaction"] is scrub_tracking_tokens


def test_initialized_outside_cloud_run_is_development_without_release():
    with mock.patch("config.sentry.sentry_sdk.init") as init:
        assert init_sentry({"SENTRY_DSN": DSN}) is True
    kwargs = init.call_args.kwargs
    assert kwargs["environment"] == "development"
    assert kwargs["release"] is None


# --- SERBITO-314: tracking tokens never reach Sentry ------------------------------------------


class _CaptureTransport(Transport):
    """Keeps error and transaction payloads in memory instead of sending them."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type in ("event", "transaction"):
                self.events.append(item.payload.json)


@pytest.fixture
def sentry_events():
    """Real Sentry client configured by init_sentry(), with an in-process transport."""
    with mock.patch("config.sentry.sentry_sdk.init") as init:
        init_sentry({"SENTRY_DSN": DSN})
    options = {**init.call_args.kwargs, "traces_sample_rate": 1.0}
    transport = _CaptureTransport()
    sentry_sdk.init(**options, transport=transport)
    try:
        yield transport.events
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


def _wsgi_get(path, **headers):
    """GET through Django's real WSGI handler, which the Sentry integration instruments.

    Like Django's test client, keeps the test's DB connection open across the request.
    """
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "testserver",
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(),
        "wsgi.errors": BytesIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        **headers,
    }
    statuses = []
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    try:
        response = get_wsgi_application()(environ, lambda status, _headers: statuses.append(status))
        b"".join(response)
        response.close()
    finally:
        request_started.connect(close_old_connections)
        request_finished.connect(close_old_connections)
    sentry_sdk.flush()
    return statuses[0]


@pytest.fixture
def tracking_token(db):
    user = get_user_model().objects.create_user(email="s@shop.rs", password="pass12345")
    shop = Shop.objects.create(owner=user, name="Pizza Napoli")
    delivery = Delivery.objects.create(
        shop=shop, recipient_name="Ana", recipient_phone="+381641234567", dest_city="Beograd"
    )
    return TrackingToken.objects.create(delivery=delivery).token


def test_error_on_tracking_page_reaches_sentry_without_token(sentry_events, tracking_token):
    referer = f"https://javi.serbito.rs/t/{tracking_token}/"
    # Fails after the token is loaded: frame locals would hold the request, TrackingToken and
    # Delivery reprs ("name — address"), so they are not sent at all (SERBITO-362, JAVI-6).
    with mock.patch("tracking.views._stepper", side_effect=RuntimeError("boom")):
        status = _wsgi_get(f"/t/{tracking_token}/", HTTP_REFERER=referer)
    assert status.startswith("500")

    errors = [e for e in sentry_events if e.get("type") != "transaction"]
    assert len(errors) == 1
    error = errors[0]
    assert error["exception"]["values"][-1]["value"] == "boom"
    assert error["request"]["url"] == "http://testserver/t/:token/"
    assert error["request"]["headers"]["Referer"] == "https://javi.serbito.rs/t/:token/"
    frames = error["exception"]["values"][-1]["stacktrace"]["frames"]
    assert any(f.get("function") == "status" for f in frames)
    assert not any(f.get("vars") for f in frames)
    for event in sentry_events:
        assert tracking_token not in json.dumps(event)


def test_tracking_page_transaction_is_scrubbed(sentry_events, tracking_token):
    assert _wsgi_get(f"/t/{tracking_token}/").startswith("200")

    transactions = [e for e in sentry_events if e.get("type") == "transaction"]
    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction["transaction"] == "/t/:token/"
    assert transaction["request"]["url"] == "http://testserver/t/:token/"
    assert tracking_token not in json.dumps(transaction)


def test_scrubs_transaction_name_taken_from_raw_path():
    event = {"type": "transaction", "transaction": "/t/abcdefghijklmnopqrstuvwxyz012345/oceni/"}
    assert scrub_tracking_tokens(event, {})["transaction"] == "/t/:token/oceni/"


def test_scrubs_breadcrumbs_and_bare_token_reprs():
    token = "Zx9_-abcdefghijklmnopqrstuvwxyz0"
    event = {
        "request": {"url": f"https://javi.serbito.rs/t/{token}/"},
        "breadcrumbs": {
            "values": [
                {"category": "httplib", "data": {"url": f"https://javi.serbito.rs/t/{token}/"}},
                {"message": f"SMS sent: Track your order: https://javi.serbito.rs/t/{token}/"},
                {"message": f"redirect to '/t/{token}/odjava/'"},
            ]
        },
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "vars": {
                                    "token_obj": f"<TrackingToken: {token}>",
                                    "token": "[Filtered]",
                                }
                            }
                        ]
                    }
                }
            ]
        },
    }
    scrubbed = scrub_tracking_tokens(event, {})
    assert token not in json.dumps(scrubbed)
    crumbs = scrubbed["breadcrumbs"]["values"]
    assert crumbs[0]["data"]["url"] == "https://javi.serbito.rs/t/:token/"
    assert crumbs[1]["message"] == "SMS sent: Track your order: https://javi.serbito.rs/t/:token/"
    assert crumbs[2]["message"] == "redirect to '/t/:token/odjava/'"
    frame_vars = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
    assert frame_vars["token_obj"] == "<TrackingToken: :token>"


@pytest.mark.parametrize(
    "url",
    [
        "https://javi.serbito.rs/app/deliveries/42/",
        "https://javi.serbito.rs/static/t/logo.svg",
        "https://javi.serbito.rs/api/v1/deliveries/?status=t",
        "/accounts/login/?next=/app/",
    ],
)
def test_non_tracking_urls_untouched(url):
    event = {
        "transaction": url,
        "request": {"url": url, "headers": {"Referer": url}},
        "breadcrumbs": {"values": [{"data": {"url": url}}]},
    }
    assert scrub_tracking_tokens(event, {}) == event


def test_non_tracking_page_transaction_keeps_its_url(sentry_events, db):
    assert _wsgi_get("/accounts/login/").startswith("200")
    (transaction,) = [e for e in sentry_events if e.get("type") == "transaction"]
    assert transaction["request"]["url"] == "http://testserver/accounts/login/"
    assert ":token" not in json.dumps(transaction)


# --- SERBITO-362: secrets never reach Sentry -----------------------------------------------


def test_scrubs_secret_query_values_bot_tokens_and_secret_headers():
    event = {
        "request": {
            "url": "https://javi.serbito.rs/webhooks/infobip/reports/",
            "query_string": "secret=s3cr3t-value&page=2",
            "headers": {
                "X-Tasks-Secret": "tasks-secret",
                "X-Webhook-Secret": "hook-secret",
                "X-Telegram-Bot-Api-Secret-Token": "tg-secret",
                "Authorization": "Basic Zm9vOmJhcg==",
                "User-Agent": "Infobip",
            },
        },
        "breadcrumbs": {
            "values": [
                {"message": "POST https://api.telegram.org/bot123456:AAF-x_y/sendMessage"},
                {"message": "GET /maps/api/geocode/json?address=Ulica+1&key=AIzaSyX"},
            ]
        },
    }
    scrubbed = scrub_tracking_tokens(event, {})
    text = json.dumps(scrubbed)
    for secret in (
        "s3cr3t-value",
        "tasks-secret",
        "hook-secret",
        "tg-secret",
        "AAF-x_y",
        "AIzaSyX",
        "Zm9vOmJhcg==",
    ):
        assert secret not in text
    assert scrubbed["request"]["query_string"] == "secret=[Filtered]&page=2"
    assert scrubbed["request"]["headers"]["User-Agent"] == "Infobip"
    crumbs = scrubbed["breadcrumbs"]["values"]
    assert crumbs[0]["message"] == "POST https://api.telegram.org/bot[Filtered]/sendMessage"


def test_webhook_request_with_query_secret_reaches_sentry_scrubbed(sentry_events, settings, db):
    settings.INFOBIP_WEBHOOK_SECRET = "right-secret"
    status = _wsgi_get(
        "/webhooks/infobip/reports/",
        QUERY_STRING="secret=wrong-secret",
        HTTP_X_WEBHOOK_SECRET="header-secret",
    )
    assert status.startswith("403")
    (transaction,) = [e for e in sentry_events if e.get("type") == "transaction"]
    text = json.dumps(transaction)
    assert "wrong-secret" not in text and "header-secret" not in text
