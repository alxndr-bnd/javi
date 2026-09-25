from unittest import mock

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from config.sentry import init_sentry

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
    assert kwargs["traces_sample_rate"] == 0.1
    assert any(isinstance(i, DjangoIntegration) for i in kwargs["integrations"])


def test_initialized_outside_cloud_run_is_development_without_release():
    with mock.patch("config.sentry.sentry_sdk.init") as init:
        assert init_sentry({"SENTRY_DSN": DSN}) is True
    kwargs = init.call_args.kwargs
    assert kwargs["environment"] == "development"
    assert kwargs["release"] is None
