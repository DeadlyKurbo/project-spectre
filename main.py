#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Failsafe entrypoint voor Project SPECTRE.

Doel:
- Zeker weten dat /invite en /dashboard binnen 3s antwoorden (geen "did not respond").
- Commands worden altijd gesynct (guild -> snel; anders global).
- Archive-cog wordt geladen zonder extra menu-spam (view is persistent in de cog).
"""

from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional

import nextcord
from nextcord.ext import commands
from nextcord import Embed
from nextcord.ui import Button, View

# -------------------
# Logging
# -------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
log = logging.getLogger("spectre.failsafe")

# -------------------
# Helpers
# -------------------
def getenv_int(name: str) -> Optional[int]:
    v = os.getenv(name, "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None

def require_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def build_link_view(label: str, url: str) -> View:
    view = View()
    view.add_item(Button(label=label, url=url))
    return view

# Defaults uit jullie settings
DEF_INVITE = (
    "https://discord.com/oauth2/authorize?client_id=1121761480145117224"
    "&permissions=8&scope=bot%20applications.commands"
)
DEF_DASHBOARD = "https://project-spectre-production.up.railway.app/"

INVITE_URL = os.getenv("SPECTRE_BOT_INVITE_URL", DEF_INVITE).strip() or DEF_INVITE
DASHBOARD_URL = os.getenv("SPECTRE_DASHBOARD_URL", DEF_DASHBOARD).strip() or DEF_DASHBOARD

# -------------------
# Bot setup
# -------------------
intents = nextcord.Intents.default()
intents.guilds = True
intents.members = True          # Zorg in Dev Portal dat dit AAN staat
intents.message_content = True  # idem

bot = commands.Bot(intents=intents)

# -------------------
# Slash commands — gegarandeerd aanwezig
# -------------------
@bot.slash_command(name="invite", description="Get the bot invite link.")
async def invite_cmd(interaction: nextcord.Interaction):
    # ALTIJD binnen 3s ack'en
    await interaction.response.defer(ephemeral=True, with_message=True)
    embed = Embed(
        title="Spectre Invite",
        description="Use the button below to invite the bot.",
        color=0x0FA3B1,
    )
    await interaction.followup.send(
        embed=embed,
        view=build_link_view("Invite Bot", INVITE_URL),
        ephemeral=True,
    )

@bot.slash_command(name="dashboard", description="Open the Spectre dashboard.")
async def dashboard_cmd(interaction: nextcord.Interaction):
    await interaction.response.defer(ephemeral=True, with_message=True)
    embed = Embed(
        title="Spectre Dashboard",
        description="Access Spectre's dashboard using the button below.",
        color=0x0FA3B1,
    )
    await interaction.followup.send(
        embed=embed,
        view=build_link_view("Open Dashboard", DASHBOARD_URL),
        ephemeral=True,
    )

# -------------------
# Utility text commands
# -------------------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply(f"Pong! `{round(bot.latency * 1000)} ms`", mention_author=False)

@bot.command(name="reload")
@commands.is_owner()
async def reload_all(ctx: commands.Context):
    # Herlaad alleen cogs.* die we gebruiken (nu archive)
    try:
        await bot.reload_extension("cogs.archive")
        await ctx.reply("♻️ Reloaded.", mention_author=False)
    except Exception as e:
        await ctx.reply(f"❌ Reload failed: {e}", mention_author=False)

# -------------------
# Lifecycle
# -------------------
@bot.event
async def on_ready():
    # Commands syncen (guild -> snel als GUILD_ID is gezet)
    try:
        gid = getenv_int("GUILD_ID")
        if gid:
            await bot.sync_application_commands(guild_id=gid)
            log.info("Slash commands synced to guild %s.", gid)
        else:
            await bot.sync_application_commands()
            log.info("Slash commands synced globally.")
    except Exception as e:
        log.warning("Command sync failed (continuing anyway): %s", e)

    # Persistent Archive view re-attachen (cog levert de View)
    try:
        archive_cog = bot.get_cog("ArchiveCog")
        if archive_cog and hasattr(archive_cog, "register_persistent_view"):
            archive_cog.register_persistent_view()
            log.info("Archive persistent view attached.")
    except Exception as e:
        log.warning("Could not attach Archive view: %s", e)

    log.info("✅ Logged in as %s (%s)", bot.user, getattr(bot.user, "id", "?"))

# -------------------
# Boot
# -------------------
def main():
    # Laad onze Archive-cog (zorgt voor persistent view + /archive-deploy)
    try:
        bot.load_extension("cogs.archive")
    except Exception as e:
        log.warning("Could not load cogs.archive (continuing): %s", e)

    token = require_env("DISCORD_TOKEN")
    bot.run(token)

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os, logging
import nextcord
from nextcord.ext import commands

from tasks.deploy_watcher import DeployWatcher

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
    # persistent view
    cog = bot.get_cog("ArchiveCog")
    if cog and hasattr(cog, "register_persistent_view"):
        try:
            cog.register_persistent_view()
        except Exception as e:
            log.warning("Archive view attach failed: %s", e)
    log.info("✅ Logged in as %s (%s)", bot.user, getattr(bot.user, "id", "?"))

def main():
    # cogs
    try:
        bot.load_extension("cogs.archive")
    except Exception as e:
        log.warning("Could not load cogs.archive: %s", e)

    # start watcher (website -> deploy)
    DeployWatcher(bot).start()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN")
    bot.run(token)

if __name__ == "__main__":
    main()
