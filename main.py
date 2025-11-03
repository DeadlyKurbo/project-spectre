#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project SPECTRE — Discord Bot Entrypoint
- Robuuste logging
- Config via env
- Intents + privileges
- Slash command sync (guild-specifiek of global)
- Persistent UI views re-attach (Archive menu)
- Afhandeling van interactions met auto-defer (in cogs/utils)
- Hot-reload commands (!reload)
- Graceful shutdown

Vereist:
- DISCORD_TOKEN
Optioneel:
- COMMAND_SYNC = "guild" | "global" | "none" (default: "guild" als GUILD_ID gezet, anders "global")
- GUILD_ID     = numeriek id voor snelle dev-sync
"""

from __future__ import annotations
import os
import sys
import re
import logging
import asyncio
import signal
from pathlib import Path
from typing import Optional, Iterable

import nextcord
from nextcord.ext import commands

# =========================
# Logging setup
# =========================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
logging.basicConfig(level=LOG_LEVEL, format=LOG_FMT)
log = logging.getLogger("spectre.main")

# =========================
# Constants / Paths
# =========================
ROOT_DIR = Path(__file__).parent.resolve()
COGS_DIR = ROOT_DIR / "cogs"
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ARCHIVE_STORE = DATA_DIR / "archive_menu.json"  # gebruikt door ArchiveCog

# =========================
# Config helpers
# =========================
def require_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def getenv_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = os.getenv(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default

def get_command_sync_strategy() -> str:
    """
    "guild": sync alleen naar één guild (sneller tijdens dev)
    "global": sync naar alle guilds (prod)
    "none": geen automatische sync
    """
    s = os.getenv("COMMAND_SYNC", "").strip().lower()
    if s in {"guild", "global", "none"}:
        return s
    # default slim: als GUILD_ID staat -> guild, anders global
    return "guild" if getenv_int("GUILD_ID") else "global"

# =========================
# Intents
# =========================
def make_intents() -> nextcord.Intents:
    intents = nextcord.Intents.default()
    intents.guilds = True
    intents.members = True          # Vereist: zet aan in Dev Portal
    intents.message_content = True  # Vereist: zet aan in Dev Portal
    return intents

# =========================
# Bot setup
# =========================
class SpectreBot(commands.Bot):
    def __init__(self, *, command_prefix: str, intents: nextcord.Intents):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.synced = False
        self._closing = asyncio.Event()

    # ---------- events ----------
    async def setup_hook(self) -> None:
        """Wordt aangeroepen vóór on_ready; goed moment om cogs te laden."""
        await self._load_all_cogs()
        log.info("All cogs loaded in setup_hook.")

    async def on_ready(self):
        # Command sync
        await self._ensure_application_commands_synced()

        # Re-register persistent views (zoals Archive)
        archive_cog = self.get_cog("ArchiveCog")
        if archive_cog and hasattr(archive_cog, "register_persistent_view"):
            try:
                archive_cog.register_persistent_view()
                log.info("Archive persistent view re-attached.")
            except Exception as e:
                log.warning("Failed to re-attach Archive persistent view: %s", e)

        log.info("✅ Logged in as %s (%s)", self.user, getattr(self.user, "id", "?"))

    async def on_command_error(self, ctx: commands.Context, exc: Exception):
        if isinstance(exc, commands.CommandNotFound):
            await ctx.reply("❓ Unknown command.", mention_author=False)
            return
        log.exception("Command error: %s", exc)
        try:
            await ctx.reply(f"❌ Error: {exc}", mention_author=False)
        except Exception:
            pass

    # ---------- cogs ----------
    async def _load_all_cogs(self):
        """Laad alle .py files in de cogs/ directory behalve __init__.py"""
        if not COGS_DIR.exists():
            log.warning("Cogs directory %s not found; skipping.", COGS_DIR)
            return
        for p in sorted(COGS_DIR.glob("*.py")):
            if p.name == "__init__.py":
                continue
            ext = f"cogs.{p.stem}"
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception as e:
                log.exception("Failed to load %s: %s", ext, e)

    async def _reload_all_cogs(self):
        """Herlaad alle cogs (handig voor hot-reload)."""
        for ext in list(self.extensions.keys()):
            if not ext.startswith("cogs."):
                continue
            try:
                await self.reload_extension(ext)
                log.info("Reloaded extension: %s", ext)
            except Exception as e:
                log.exception("Failed to reload %s: %s", ext, e)

    # ---------- sync ----------
    async def _ensure_application_commands_synced(self):
        if self.synced:
            return
        strategy = get_command_sync_strategy()
        guild_id = getenv_int("GUILD_ID")
        try:
            if strategy == "none":
                log.info("Skipping command sync (COMMAND_SYNC=none).")
            elif strategy == "guild" and guild_id:
                gobj = nextcord.Object(id=guild_id)
                await self.sync_application_commands(guild_id=guild_id)
                log.info("Slash commands synced to guild %s only.", guild_id)
            else:
                await self.sync_application_commands()
                log.info("Slash commands synced globally.")
            self.synced = True
        except Exception as e:
            log.exception("Failed to sync application commands: %s", e)

    # ---------- graceful shutdown ----------
    async def close(self) -> None:
        self._closing.set()
        await super().close()

# =========================
# Commands (utility)
# =========================
def add_owner_only_commands(bot: SpectreBot):
    @bot.command(name="reload", help="Reload all cogs (owner only).")
    @commands.is_owner()
    async def _reload(ctx: commands.Context):
        await bot._reload_all_cogs()
        await ctx.reply("♻️ Reloaded all cogs.", mention_author=False)

    @bot.command(name="ping", help="Latency check.")
    async def _ping(ctx: commands.Context):
        # Dit is geen slash, maar laat basale respons zien
        await ctx.reply(f"Pong! `{round(bot.latency * 1000)} ms`", mention_author=False)

# =========================
# Signal handlers
# =========================
def install_signal_handlers(loop: asyncio.AbstractEventLoop, bot: SpectreBot):
    def _sigterm():
        log.info("SIGTERM received — shutting down...")
        loop.create_task(bot.close())

    def _sigint():
        log.info("SIGINT received — shutting down...")
        loop.create_task(bot.close())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _sigterm if sig == signal.SIGTERM else _sigint)
        except NotImplementedError:
            # Windows
            pass

# =========================
# Main entry
# =========================
def main():
    token = require_env("DISCORD_TOKEN")

    intents = make_intents()
    bot = SpectreBot(command_prefix="!", intents=intents)

    # Owner-only & utility commands
    add_owner_only_commands(bot)

    # Run
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    install_signal_handlers(loop, bot)

    try:
        loop.run_until_complete(bot.start(token))
    finally:
        # Zorg dat loop netjes sluit
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()
        try:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        log.info("Event loop closed.")

if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
            # Nuttige melding als env mist
            print(f"[FATAL] {e}", file=sys.stderr)
            sys.exit(2)
    except Exception as e:
        print(f"[FATAL] Unhandled: {e}", file=sys.stderr)
        sys.exit(1)
