"""Application-owned logging; no pygame or optional dependency is imported.

GO_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR (default INFO)
GO_LOG_FORMAT=text|json (default text)
GO_LOG_FILE=/path/to/game.log (optional; desktop only)

Never log entire SGF records or raw user paths. Use short event names and game IDs.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

LOGGER_NAME = "go_game"
_EVENT_FIELDS = ("event", "game_id", "turn", "move", "captures", "reason")


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with an intentionally small field allowlist."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created, timezone.utc)
        payload = {
            "timestamp": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EVENT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _formatter(format_name: str) -> logging.Formatter:
    if format_name.lower() == "json":
        return JsonFormatter()
    return logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def configure_logging(
    *, level: Optional[str] = None, format_name: Optional[str] = None,
    log_file: Optional[str] = None, stream=None,
) -> logging.Logger:
    """Configure only the go_game logger; repeated calls do not duplicate output.

    A file is never opened in the browser. An invalid/unwritable file degrades
    to console logging and emits a warning without interrupting gameplay.
    Passing log_file="" suppresses GO_LOG_FILE, useful in tests.
    """
    logger = logging.getLogger(LOGGER_NAME)
    name = (level or os.getenv("GO_LOG_LEVEL", "INFO")).upper()
    if name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        name = "INFO"
    logger.setLevel(getattr(logging, name))
    logger.propagate = False

    for handler in tuple(logger.handlers):
        if getattr(handler, "_go_game_owned", False):
            logger.removeHandler(handler)
            handler.close()

    fmt = _formatter(format_name or os.getenv("GO_LOG_FORMAT", "text"))
    console = logging.StreamHandler(sys.stderr if stream is None else stream)
    console.setFormatter(fmt)
    console._go_game_owned = True
    logger.addHandler(console)

    path = os.getenv("GO_LOG_FILE", "") if log_file is None else log_file
    if path:
        if sys.platform == "emscripten":
            logger.warning("File logging disabled in browser", extra={"event": "logging.file_disabled"})
        else:
            try:
                file_handler = RotatingFileHandler(
                    path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
                )
            except OSError as exc:
                logger.warning(
                    "File logging unavailable (%s); using console", type(exc).__name__,
                    extra={"event": "logging.file_unavailable"},
                )
            else:
                file_handler.setFormatter(fmt)
                file_handler._go_game_owned = True
                logger.addHandler(file_handler)
    return logger
