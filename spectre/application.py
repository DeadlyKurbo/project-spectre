"""Application bootstrap and orchestration logic."""

from __future__ import annotations

import logging

from lazarus import LazarusAI

from constants import LAZARUS_CHANNEL_ID
from server_config import configured_guild_ids

from .bot_factory import create_bot, ensure_event_loop
from .commands import register_all as register_commands
from .context import SpectreContext
from .events import register as register_events
from .logging_config import configure_logging
from .settings import SpectreSettings
from .version import ensure_nextcord_version


class SpectreApplication:
    """Assemble the bot, register components, and expose runtime helpers."""

    def __init__(self) -> None:
        ensure_event_loop()
        ensure_nextcord_version()
        self.settings = SpectreSettings.from_env()
        self.logger = configure_logging()
        self._log_token_source()

        self.bot = create_bot()
        guild_ids = configured_guild_ids()
        self.context = SpectreContext(
            bot=self.bot,
            settings=self.settings,
            logger=self.logger,
            lazarus_ai=LazarusAI(
                self.bot,
                LAZARUS_CHANNEL_ID,
                self.settings.backup_interval_hours,
                self.settings.lazarus_status_interval,
            ),
            guild_ids=guild_ids,
        )
        self.bot.add_cog(self.context.lazarus_ai)

        if not guild_ids:
            self.logger.warning(
                "No valid guild IDs configured; slash commands will be registered globally."
            )

        register_events(self.context)
        register_commands(self.context)

    def _log_token_source(self) -> None:
        if self.settings.token_source == "DISCORD_BOT_TOKEN":
            self.logger.warning(
                "DISCORD_TOKEN is not set; using DISCORD_BOT_TOKEN fallback. "
                "Please update the environment to use DISCORD_TOKEN."
            )

    @property
    def token(self) -> str | None:
        return self.settings.token

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    @logger.setter
    def logger(self, value: logging.Logger) -> None:
        self._logger = value


__all__ = ["SpectreApplication"]
