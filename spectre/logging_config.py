"""Logging helpers used across the Spectre bot."""

from __future__ import annotations

import logging
import os


def configure_logging() -> logging.Logger:
    """Configure the root Spectre logger and return it."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("spectre")
    logging.getLogger("nextcord.gateway").setLevel(logging.WARNING)
    logging.getLogger("nextcord.http").setLevel(logging.WARNING)
    return logger


__all__ = ["configure_logging"]
