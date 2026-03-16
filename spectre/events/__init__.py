"""Event handler registration for the Spectre bot."""

from __future__ import annotations

import asyncio
import nextcord

from archive_status import update_status_message
from archivist import handle_upload, refresh_menus
from async_utils import safe_handler
from constants import ROOT_PREFIX, UPLOAD_CHANNEL_ID
from server_config import get_server_config
from storage_spaces import ensure_dir
from views import RootView

from ..context import SpectreContext
from ..tasks.backups import create_backup_loop


def register(context: SpectreContext) -> None:
    bot = context.bot
    context.backup_loop = create_backup_loop(context)

    def _iter_runtime_guild_ids() -> list[int]:
        """Return known guild IDs, combining configured and currently connected guilds."""

        guild_ids = {int(gid) for gid in context.guild_ids}
        guild_ids.update(int(guild.id) for guild in bot.guilds)
        return sorted(guild_ids)

    def _prepare_guild_storage(guild_id: int) -> None:
        """Ensure guild archive directories and persistent views are registered."""

        # Register persistent views first so menu interactions remain available
        # even when configuration backends are briefly unavailable during
        # startup/reconnect windows.
        try:
            bot.add_view(RootView(guild_id))
        except Exception:
            context.logger.exception(
                "Failed to register persistent root view for guild %s", guild_id
            )

        try:
            base = get_server_config(guild_id).get("ROOT_PREFIX", ROOT_PREFIX)
            ensure_dir(base)
            for cat in ("missions", "personnel", "intelligence", "acl"):
                ensure_dir(f"{base}/{cat}")
        except Exception:
            context.logger.exception(
                "Failed to prepare archive storage for guild %s", guild_id
            )

    async def _refresh_modern_archive_menus() -> None:
        """Refresh modern archive root menus for all connected guilds."""

        for gid in _iter_runtime_guild_ids():
            guild = bot.get_guild(gid)
            if not guild:
                continue
            try:
                await refresh_menus(guild)
            except Exception:
                context.logger.exception(
                    "Failed to auto-refresh modern archive menu for guild %s", gid
                )

    async def _sync_slash_commands() -> None:
        if context.commands_synced:
            return
        try:
            guild_ids = _iter_runtime_guild_ids()
            if guild_ids:
                for gid in guild_ids:
                    await bot.sync_application_commands(guild_id=gid)
            else:
                await bot.sync_application_commands()
        except Exception:
            context.logger.exception("Failed to sync slash commands")
        else:
            context.commands_synced = True
            context.logger.info(
                "Synced slash commands for %s guild(s)",
                len(guild_ids) if guild_ids else "global",
            )

    @bot.event
    @safe_handler
    async def on_ready() -> None:
        await context.log_action(f"SPECTRE online as {bot.user}", broadcast=False)
        for gid in _iter_runtime_guild_ids():
            try:
                _prepare_guild_storage(gid)
            except Exception:
                context.logger.exception(
                    "Unexpected startup failure while preparing guild %s", gid
                )
        await _refresh_modern_archive_menus()
        try:
            await update_status_message(bot)
        except Exception:
            pass
        if context.backup_loop and not context.backup_loop.is_running():
            context.backup_loop.start()
        context.lazarus_ai.start()
        await _sync_slash_commands()

    @bot.event
    @safe_handler
    async def on_guild_join(guild: nextcord.Guild) -> None:
        if guild.id not in context.guild_ids:
            context.guild_ids.append(guild.id)
        try:
            _prepare_guild_storage(guild.id)
        except Exception:
            context.logger.exception(
                "Unexpected failure while preparing joined guild %s", guild.id
            )
        try:
            await bot.sync_application_commands(guild_id=guild.id)
            context.logger.info("Synced slash commands for joined guild %s", guild.id)
        except Exception:
            context.logger.exception(
                "Failed to sync slash commands for joined guild %s", guild.id
            )

    @bot.event
    @safe_handler
    async def on_disconnect() -> None:
        context.logger.warning("Bot disconnected; waiting for reconnect")

    @bot.event
    @safe_handler
    async def on_application_command_error(
        interaction: nextcord.Interaction, error: Exception
    ) -> None:
        context.logger.exception("Application command error", exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    " An unexpected error occurred.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    " An unexpected error occurred.", ephemeral=True
                )
        except Exception:
            pass

    @bot.event
    @safe_handler
    async def on_message(message: nextcord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != UPLOAD_CHANNEL_ID:
            return
        await handle_upload(message)


__all__ = ["register"]
