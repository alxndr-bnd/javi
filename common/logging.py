"""Structured logs: one JSON object per line on stdout (SERBITO-336).

Cloud Logging parses a JSON line from stdout into jsonPayload and reads the special fields
itself: `severity` becomes the entry's level (so WARNING/ERROR can be filtered and alerted on,
instead of every line being "DEFAULT"), `message` is the summary line, and
`logging.googleapis.com/sourceLocation` points at the code. A stack trace goes into `message`,
where Error Reporting looks for it.

Extra fields passed with `logger.warning(..., extra={"event": "shop.signup", "shop_id": 7})`
land in the payload as they are, so an alert can match `jsonPayload.event="shop.signup"`.
Only JSON-friendly values are copied: Django's `extra={"request": request}` would put the
request repr (a URL with a tracking token) into the payload.

LOG_FORMAT=text switches to plain lines for local work (config/settings.py).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_RECORD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
_JSON_SCALARS = (str, int, float, bool, type(None))


def _json_friendly(value) -> bool:
    if isinstance(value, _JSON_SCALARS):
        return True
    if isinstance(value, list | tuple):
        return all(_json_friendly(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _json_friendly(v) for k, v in value.items())
    return False


def severity(levelno: int) -> str:
    """Cloud Logging LogSeverity for a stdlib level (custom levels round down)."""
    if levelno >= logging.CRITICAL:
        return "CRITICAL"
    if levelno >= logging.ERROR:
        return "ERROR"
    if levelno >= logging.WARNING:
        return "WARNING"
    if levelno >= logging.INFO:
        return "INFO"
    return "DEBUG"


class JsonFormatter(logging.Formatter):
    """A LogRecord as a single-line JSON object for Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        elif record.exc_text:
            message = f"{message}\n{record.exc_text}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"

        entry = {
            "severity": severity(record.levelno),
            "message": message,
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }
        for key, value in vars(record).items():
            if key not in _RECORD_ATTRS and key not in entry and _json_friendly(value):
                entry[key] = value
        return json.dumps(entry, ensure_ascii=False)
