"""Spectre entrypoint wiring keepalive and bot runtime."""

from __future__ import annotations

import logging

import nextcord  # re-exported for tests expecting ``main.nextcord``

from keepalive import start_keepalive
from spectre.runtime import run
from spectre.version import ensure_nextcord_version as _ensure_nextcord_version_impl

LOGGER = logging.getLogger("spectre")


def _start_keepalive() -> None:
    """Launch the keepalive HTTP server."""

    start_keepalive()


def _ensure_nextcord_version() -> None:
    """Expose the Nextcord version guard for compatibility tests."""

    _ensure_nextcord_version_impl()


def main() -> None:
    """Start the keepalive server and run the Spectre runtime."""

    _ensure_nextcord_version()
    try:
        _start_keepalive()
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.warning("Keepalive server failed to start: %s", exc)
    run()


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
