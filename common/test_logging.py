"""JSON logs for Cloud Logging (SERBITO-336)."""

import io
import json
import logging
import sys

import pytest
from django.conf import settings

from common.logging import JsonFormatter, severity


def _record(level=logging.INFO, msg="hello %s", args=("world",), exc_info=None):
    return logging.LogRecord("javi.test", level, __file__, 42, msg, args, exc_info)


def _format(record) -> dict:
    line = JsonFormatter().format(record)
    assert "\n" not in line  # one entry = one line, or Cloud Logging splits it
    return json.loads(line)


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (logging.DEBUG, "DEBUG"),
        (logging.INFO, "INFO"),
        (logging.WARNING, "WARNING"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "CRITICAL"),
        (logging.WARNING + 5, "WARNING"),
    ],
)
def test_severity_maps_stdlib_levels(level, expected):
    assert severity(level) == expected
    assert _format(_record(level))["severity"] == expected


def test_entry_has_message_logger_time_and_source_location():
    entry = _format(_record())
    assert entry["message"] == "hello world"
    assert entry["logger"] == "javi.test"
    assert entry["time"].endswith("+00:00")
    location = entry["logging.googleapis.com/sourceLocation"]
    assert location["file"] == __file__ and location["line"] == 42


def test_exception_stack_goes_into_message():
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(logging.ERROR, "failed", (), exc_info=sys.exc_info())
    entry = _format(record)
    assert entry["severity"] == "ERROR"
    assert entry["message"].startswith("failed\nTraceback")
    assert "ValueError: boom" in entry["message"]


def test_json_friendly_extras_are_copied_objects_are_not():
    record = _record()
    record.event = "shop.signup"
    record.shop_id = 7
    record.details = {"trial": True, "tags": ["a", "b"]}
    record.request = object()  # Django's extra={"request": ...}: its repr carries the URL
    entry = _format(record)
    assert entry["event"] == "shop.signup"
    assert entry["shop_id"] == 7
    assert entry["details"] == {"trial": True, "tags": ["a", "b"]}
    assert "request" not in entry


def test_extras_do_not_override_core_fields():
    record = _record()
    record.logger = "spoofed"
    assert _format(record)["logger"] == "javi.test"


def test_non_ascii_kept_readable():
    entry = JsonFormatter().format(_record(msg="Isporučeno %s", args=("✓",)))
    assert "Isporučeno ✓" in entry


def test_settings_send_json_to_stdout():
    handler = settings.LOGGING["handlers"]["stdout"]
    assert handler["stream"] == "ext://sys.stdout"
    assert handler["formatter"] == "json"
    assert settings.LOGGING["root"]["handlers"] == ["stdout"]
    # Django's own loggers have no handler of their own and reach root, i.e. the JSON one.
    assert settings.LOGGING["loggers"]["django"]["propagate"] is True
    assert "handlers" not in settings.LOGGING["loggers"]["django"]


def test_root_logger_writes_json_lines(monkeypatch):
    root = logging.getLogger()
    stdout_handler = next(
        h for h in root.handlers if isinstance(getattr(h, "formatter", None), JsonFormatter)
    )
    buffer = io.StringIO()
    monkeypatch.setattr(stdout_handler, "stream", buffer)
    logging.getLogger("django.request").warning("Not Found: %s", "/x/")
    entry = json.loads(buffer.getvalue().splitlines()[-1])
    assert entry == entry | {"severity": "WARNING", "message": "Not Found: /x/"}
    assert entry["logger"] == "django.request"
