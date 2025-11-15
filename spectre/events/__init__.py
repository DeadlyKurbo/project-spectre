"""Event handler registration for the Spectre bot."""

from __future__ import annotations

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

    async def _sync_slash_commands() -> None:
        if context.commands_synced:
            return
        try:
            if context.guild_ids:
                for gid in context.guild_ids:
                    await bot.sync_application_commands(guild_id=gid)
            else:
                await bot.sync_application_commands()
        except Exception:
            context.logger.exception("Failed to sync slash commands")
        else:
            context.commands_synced = True
            context.logger.info(
                "Synced slash commands for %s guild(s)",
                len(context.guild_ids) if context.guild_ids else "global",
            )

    @bot.event
    @safe_handler
    async def on_ready() -> None:
        await context.log_action(f"SPECTRE online as {bot.user}", broadcast=False)
        for gid in context.guild_ids:
            base = get_server_config(gid).get("ROOT_PREFIX", ROOT_PREFIX)
            ensure_dir(base)
            for cat in ("missions", "personnel", "intelligence", "acl"):
                ensure_dir(f"{base}/{cat}")
            bot.add_view(RootView(gid))
        for gid in context.guild_ids:
            guild = bot.get_guild(gid)
            if not guild:
                continue
            try:
                await refresh_menus(guild)
            except Exception:
                pass
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
