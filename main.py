"""Entrypoint for the Spectre Discord bot runtime."""

from __future__ import annotations

from constants import (
    CLASSIFIED_ROLE_ID,
    FLEET_ADMIRAL_ROLE_ID,
    OWNER_ROLE_ID,
    XO_ROLE_ID,
)
from spectre.commands.protocols import protocol_epsilon_command
from spectre.runtime import run as run_spectre


class _ProtocolStubContext:
    """Lightweight context used for protocol unit tests.

    The full :class:`spectre.context.SpectreContext` instance requires the bot
    event loop and registered cogs. For dashboard and protocol unit tests we
    only need a minimal stub that exposes :py:meth:`log_action`.
    """

    async def log_action(self, _message: str) -> None:  # pragma: no cover - noop
        return None


_STUB_CONTEXT = _ProtocolStubContext()


async def protocol_epsilon(interaction):
    """Delegate the protocol epsilon command using a stubbed context.

    This maintains compatibility for lightweight tests that invoke the
    command handler directly without bootstrapping the entire bot runtime.
    """

    await protocol_epsilon_command(_STUB_CONTEXT, interaction)


__all__ = [
    "protocol_epsilon",
    "run_spectre",
    "CLASSIFIED_ROLE_ID",
    "OWNER_ROLE_ID",
    "XO_ROLE_ID",
    "FLEET_ADMIRAL_ROLE_ID",
]


if __name__ == "__main__":
    run_spectre()
