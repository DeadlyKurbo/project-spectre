#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import logging
import asyncio
import nextcord
from nextcord.ext import commands

from tasks.remote_config_watcher import RemoteConfigWatcher

LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
log = logging.getLogger("spectre.main")


class SpectreBot(commands.Bot):
    def __init__(self):
        intents = nextcord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)
        self._rcw_started = False

    async def setup_hook(self) -> None:
        # Start een background task die de archive-cog blijft proberen te laden.
        self.loop.create_task(self._ensure_archive_loaded())

    async def _ensure_archive_loaded(self):
        """Blijf cogs.archive retrien tot het lukt; start daarna de watcher."""
        while True:
            try:
                if "cogs.archive" not in self.extensions:
                    self.load_extension("cogs.archive")
                    log.info("📦 Loaded extension cogs.archive")
                if not self._rcw_started:
                    RemoteConfigWatcher(self).start()
                    self._rcw_started = True
                    log.info("🛰️ RemoteConfigWatcher started")
                return  # klaar
            except Exception:
                log.exception("❌ Failed loading cogs.archive (retrying in 10s)")
                await asyncio.sleep(10)

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        await ctx.reply("pong")


def main() -> None:
    bot = SpectreBot()

    @bot.event
    async def on_ready():
        log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)

    token = (os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        # Niet crashen; duidelijke log en idle houden voor debugging
        log.error("Missing DISCORD_TOKEN env var")
        return

    try:
        bot.run(token)
    except KeyboardInterrupt:
        log.info("Shutting down...")


if __name__ == "__main__":
    main()
