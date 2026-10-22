"""Structured logging on top of the standard library.

Records are written to stderr. With ``json_logs`` enabled each line is a JSON
object; otherwise the line is ``time level logger message key=value``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

_CONFIGURED = False


class StructuredFormatter(logging.Formatter):
    """Format a log record as text or as a single JSON object."""

    def __init__(self, json_logs: bool) -> None:
        super().__init__()
        self.json_logs = json_logs

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = {}
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            fields.update(extra)
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        message = record.getMessage()
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        if self.json_logs:
            payload = {
                "ts": ts,
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                **fields,
            }
            return json.dumps(payload, default=str, ensure_ascii=False)
        suffix = " ".join(f"{key}={fields[key]}" for key in sorted(fields))
        line = f"{ts} {record.levelname} {record.name} {message}"
        return f"{line} {suffix}".rstrip()


class _CurrentStderrHandler(logging.StreamHandler):
    """Write to the process stderr at emit time.

    Resolving ``sys.stderr`` on each record keeps logging working when a test
    runner temporarily replaces the stream.
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:
        return sys.stderr


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Install the process-wide stderr handler. Safe to call more than once."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = _CurrentStderrHandler()
    handler.setFormatter(StructuredFormatter(json_logs=json_logs))
    root.handlers.clear()
    root.addHandler(handler)
    _CONFIGURED = True


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    **fields: Any,
) -> None:
    """Log ``message`` with structured ``fields`` attached to the record."""
    logger.log(level, message, extra={"fields": fields})
