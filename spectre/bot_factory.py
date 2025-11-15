"""Factory helpers for creating the Nextcord bot client."""

from __future__ import annotations

import asyncio
import logging

import nextcord
from nextcord.ext import commands

from tasks.remote_config_watcher import RemoteConfigWatcher


LOGGER = logging.getLogger("spectre.bot")


def ensure_event_loop() -> None:
    """Ensure an asyncio event loop exists for the current thread."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class SpectreBot(commands.Bot):
    """Bot subclass that loads cogs and starts background watchers."""

    def __init__(self) -> None:
        intents = nextcord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(intents=intents)
        self._rcw_started = False

    async def setup_hook(self) -> None:
        self.loop.create_task(self._ensure_archive_loaded())

    async def _ensure_archive_loaded(self) -> None:
        """Load the archive cog and start the remote config watcher."""

        while True:
            try:
                if "cogs.archive" not in self.extensions:
                    self.load_extension("cogs.archive")
                    LOGGER.info("📦 Loaded extension cogs.archive")
                if not self._rcw_started:
                    RemoteConfigWatcher(self).start()
                    self._rcw_started = True
                    LOGGER.info("🛰️ RemoteConfigWatcher started")
                return
            except Exception:
                LOGGER.exception("❌ Failed loading cogs.archive (retrying in 10s)")
                await asyncio.sleep(10)


def create_bot() -> commands.Bot:
    """Create the Spectre ``commands.Bot`` instance with the required intents."""

    return SpectreBot()


__all__ = ["create_bot", "ensure_event_loop", "SpectreBot"]
