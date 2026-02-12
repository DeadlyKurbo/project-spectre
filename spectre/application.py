"""Application bootstrap and orchestration logic."""

from __future__ import annotations

import asyncio
import logging

from lazarus import LazarusAI

from constants import LAZARUS_CHANNEL_ID
from server_config import SERVER_CONFIGS
from tasks.remote_config_watcher import RemoteConfigWatcher

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
        self.remote_config_watcher: RemoteConfigWatcher | None = None
        guild_ids = list(SERVER_CONFIGS.keys())
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

        # Bridge legacy ``main.log_action`` call sites to the runtime context so
        # admin audit logs are delivered to configured Discord channels.
        import main as legacy_main

        legacy_main.set_action_log_handler(
            lambda message, broadcast: self.context.log_action(message, broadcast=broadcast)
        )

        register_events(self.context)
        register_commands(self.context)
        self._legacy_loader_task: asyncio.Task[None] | None = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop yet (common during startup); defer until the bot is ready.
            self.bot.add_listener(self._start_legacy_components, "on_ready")
        else:
            self._legacy_loader_task = loop.create_task(self._ensure_legacy_components())

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

    async def _ensure_legacy_components(self) -> None:
        """Load legacy extensions and start background watchers with retries."""

        while True:
            try:
                if "cogs.archive" not in self.bot.extensions:
                    self.bot.load_extension("cogs.archive")
                    self.logger.info("Loaded extension cogs.archive")
                if not self.remote_config_watcher:
                    self.remote_config_watcher = RemoteConfigWatcher(self.bot)
                    self.remote_config_watcher.start()
                    self.logger.info("RemoteConfigWatcher started")
                return
            except Exception:
                self.logger.exception(
                    "Failed initialising legacy archive components; retrying in 10 seconds"
                )
                await asyncio.sleep(10)


    async def _start_legacy_components(self, *_args, **_kwargs) -> None:
        """Lazy-start legacy helpers once the bot loop is running."""

        if self._legacy_loader_task and not self._legacy_loader_task.done():
            return

        # ``asyncio.create_task`` requires a running event loop. At this point the
        # bot is connected so it is safe to schedule the legacy bootstrapper.
        self._legacy_loader_task = asyncio.create_task(self._ensure_legacy_components())


__all__ = ["SpectreApplication"]
