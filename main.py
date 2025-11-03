#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os, logging
import nextcord
from nextcord.ext import commands

from tasks.remote_config_watcher import RemoteConfigWatcher  # << use Spaces watcher

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
log = logging.getLogger("spectre.main")

intents = nextcord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(intents=intents)

@bot.event
async def on_ready():
    # Re-attach persistent view if cog exposes it
    cog = bot.get_cog("ArchiveCog")
    if cog and hasattr(cog, "register_persistent_view"):
        try:
            cog.register_persistent_view()
        except Exception as e:
            log.warning("Archive view attach failed: %s", e)
    log.info("✅ Logged in as %s (%s)", bot.user, getattr(bot.user, "id", "?"))

def main():
    # Load archive cog (uses server_config inside)
    try:
        bot.load_extension("cogs.archive")
    except Exception as e:
        log.warning("Could not load cogs.archive: %s", e)

    # Start watcher that listens to Spaces changes + deploy-queue
    RemoteConfigWatcher(bot).start()

    token = (os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN")
    bot.run(token)

if __name__ == "__main__":
    main()
