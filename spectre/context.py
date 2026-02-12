"""Shared runtime context for the Spectre application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

import logging

from nextcord.ext import commands, tasks
from lazarus import LazarusAI

from .settings import SpectreSettings


@dataclass
class SpectreContext:
    """Container holding shared objects that multiple modules rely on."""

    bot: commands.Bot
    settings: SpectreSettings
    logger: logging.Logger
    lazarus_ai: LazarusAI
    guild_ids: list[int]
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    backup_loop: Optional[tasks.Loop] = None
    commands_synced: bool = False

    async def log_action(self, message: str, *, broadcast: bool = True) -> None:
        """Log archival actions. Placeholder for future persistence."""

        _ = broadcast  # Placeholder to preserve signature compatibility
        self.logger.debug("Action log entry: %s", message)

    @property
    def slash_guild_ids(self) -> list[int] | None:
        """Return guild IDs for slash command registration or ``None`` for global.

        Spectre now defaults to global slash-command registration so newly invited
        guilds receive commands immediately after a guild sync. Restricting
        commands to a static guild list prevents commands from appearing in new
        servers where the bot is later invited.
        """

        return None


__all__ = ["SpectreContext"]
