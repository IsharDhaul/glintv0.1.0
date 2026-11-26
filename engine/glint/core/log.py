"""Structured logging: one logfmt line per event (`ts=… level=… event=… key=value …`)."""

import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


def _fmt_value(value: object) -> str:
    text = str(value)
    if not text or any(c in text for c in ' ="'):
        return '"' + text.replace('"', '\\"') + '"'
    return text


class LogfmtFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        parts = [
            f"ts={ts}",
            f"level={record.levelname.lower()}",
            f"logger={record.name}",
            f"event={_fmt_value(record.getMessage())}",
        ]
        parts += [
            f"{key}={_fmt_value(value)}"
            for key, value in sorted(vars(record).items())
            if key not in _RESERVED
        ]
        if record.exc_info:
            parts.append(f"exc={_fmt_value(self.formatException(record.exc_info))}")
        return " ".join(parts)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(LogfmtFormatter())
    root = logging.getLogger("glint")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("glint") else f"glint.{name}")


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Log one structured line, e.g. `log_event(log, "stage_done", stage="x", rows=10, ms=42)`."""
    logger.info(event, extra=fields)
