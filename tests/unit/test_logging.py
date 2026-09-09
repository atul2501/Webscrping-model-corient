import json
import logging

from app.utils.logging import JsonFormatter


def _make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_timestamp_is_rendered_in_ist_not_utc():
    payload = json.loads(JsonFormatter().format(_make_record()))
    # IST is a fixed UTC+5:30 offset with no DST - confirmed by the
    # timestamp's own offset suffix, not by comparing to system time.
    assert payload["timestamp"].endswith("+05:30")


def test_format_includes_level_logger_and_message():
    payload = json.loads(JsonFormatter().format(_make_record()))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello world"


def test_format_includes_extra_context_fields_when_present():
    record = _make_record(crawl_id="abc123", source="vijay_sales", status_code=200)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["crawl_id"] == "abc123"
    assert payload["source"] == "vijay_sales"
    assert payload["status_code"] == 200


def test_format_omits_extra_context_fields_when_absent():
    payload = json.loads(JsonFormatter().format(_make_record()))
    assert "crawl_id" not in payload
    assert "source" not in payload
