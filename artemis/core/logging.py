"""
artemis/core/logging.py
Structured JSON logging helper used across hub, node, and sim.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_loggers: dict[str, logging.Logger] = {}


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    rotate_mb: int = 100,
    keep_backups: int = 10,
) -> None:
    """
    Call once at startup (hub/main.py or node/main.py) to configure root logger.
    Subsequent calls to get_logger() will inherit this configuration.
    """
    root = logging.getLogger("artemis")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid adding duplicate handlers on repeated calls (e.g. during tests)
    if root.handlers:
        return

    fmt = _JSONFormatter()

    # Console handler — always present
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # Rotating file handler — optional
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=rotate_mb * 1024 * 1024,
            backupCount=keep_backups,
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)

    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the 'artemis' namespace.
    Always call setup_logging() at least once before get_logger().
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(f"artemis.{name}")
    return _loggers[name]
