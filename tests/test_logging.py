"""Structured log lines."""

import json
import logging

from cryptobot.logsetup import StructuredFormatter, log_event


def test_json_formatter_includes_fields() -> None:
    formatter = StructuredFormatter(json_logs=True)
    record = logging.LogRecord(
        name="cryptobot.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="marca",
        args=(),
        exc_info=None,
    )
    record.fields = {"symbol": "BTC/USDT", "equity": 10_000}
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "marca"
    assert payload["level"] == "INFO"
    assert payload["symbol"] == "BTC/USDT"
    assert payload["equity"] == 10_000


def test_text_formatter_appends_sorted_fields() -> None:
    formatter = StructuredFormatter(json_logs=False)
    logger = logging.getLogger("cryptobot.logging.test")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "listo",
        (),
        None,
        extra={"fields": {"b": 2, "a": 1}},
    )
    rendered = formatter.format(record)
    assert "listo" in rendered
    assert "a=1 b=2" in rendered


def test_log_event_attaches_a_mapping(caplog) -> None:
    logger = logging.getLogger("cryptobot.logging.event")
    with caplog.at_level(logging.INFO):
        log_event(logger, logging.INFO, "hola", symbol="ETH/USDT")
    assert caplog.records[-1].fields["symbol"] == "ETH/USDT"
