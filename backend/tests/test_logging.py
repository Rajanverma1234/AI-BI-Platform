"""Structured logging tests."""

from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, RequestIdFilter, request_id_ctx
from app.utils import slugify


def _record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)


def test_json_formatter_emits_single_line_json() -> None:
    record = _record()
    RequestIdFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"


def test_request_id_is_attached_from_context() -> None:
    token = request_id_ctx.set("req-42")
    try:
        record = _record()
        RequestIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_ctx.reset(token)

    assert payload["request_id"] == "req-42"


def test_extra_fields_are_included() -> None:
    record = _record()
    record.status_code = 200
    RequestIdFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))

    assert payload["status_code"] == 200


def test_slugify_produces_url_safe_values() -> None:
    assert slugify("  Revenue & Growth 2026! ") == "revenue-growth-2026"
    assert slugify("Café Analytics") == "cafe-analytics"
    assert slugify("x" * 200, max_length=10) == "x" * 10
