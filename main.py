#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import logging
import nextcord
from nextcord.ext import commands

from tasks.remote_config_watcher import RemoteConfigWatcher

LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
log = logging.getLogger("spectre.main")


def create_bot() -> commands.Bot:
    intents = nextcord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.message_content = True
    return commands.Bot(intents=intents)


def main() -> None:
    bot = create_bot()

    @bot.event
    async def on_ready():
        log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)

    # --- Load cogs with HARD errors (niet stillen)
    try:
        bot.load_extension("cogs.archive")
        log.info("📦 Loaded extension cogs.archive")
    except Exception as e:
        log.exception("❌ Could not load cogs.archive (fix this error first)")
        raise  # belangrijk: niet doorgaan als de cog niet geladen is

    # --- Start watcher NA het laden van de cog
    RemoteConfigWatcher(bot).start()

    token = (os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN")
    bot.run(token)


if __name__ == "__main__":
    main()
