"""Logging helpers used across the Spectre bot and web dashboard.

Both processes write to the same Railway log stream, so every line is tagged
with the process it came from::

    14:03:14 INFO    [bot] spectre: Boot sequence initiated
    14:05:01 WARNING [web] config_app: Director alert by Kurbo delivered to 2 of 3 server owners
"""

from __future__ import annotations

import logging
import os

# Notices that show up on every boot and never need action.
_QUIET_MESSAGES = ("PyNaCl is not installed",)


class ConsoleFormatter(logging.Formatter):
    """Format records as ``time level [process] logger: message``."""

    def __init__(self, component: str = "bot") -> None:
        super().__init__(
            f"%(asctime)s %(levelname)-7s [{component}] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # uvicorn logs its normal lifecycle messages on "uvicorn.error".
        if record.name == "uvicorn.error":
            record = logging.makeLogRecord({**record.__dict__, "name": "uvicorn"})
        return super().format(record)


class QuietFilter(logging.Filter):
    """Drop boot notices nobody needs to read."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.msg).startswith(_QUIET_MESSAGES)


def configure_logging(component: str = "bot") -> logging.Logger:
    """Configure the root Spectre logger and return it."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(ConsoleFormatter(component))
    handler.addFilter(QuietFilter())
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        handlers=[handler],
    )
    logger = logging.getLogger("spectre")
    logging.getLogger("nextcord").setLevel(logging.WARNING)
    return logger


__all__ = ["ConsoleFormatter", "QuietFilter", "configure_logging"]
