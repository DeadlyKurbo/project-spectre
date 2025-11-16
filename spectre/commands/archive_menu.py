"""Slash command entrypoint for (legacy) archive menu deployment."""

from __future__ import annotations

import logging
from typing import Any

import nextcord

from cogs.archive import ArchiveCog

from ..context import SpectreContext

log = logging.getLogger(__name__)


async def spawn_archive_menu_command(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    """Deploy the archive menu using the legacy ``ArchiveCog`` helpers."""

    if not interaction.guild:
        await interaction.response.send_message(
            "⚠️ This command can only be used within a server.",
            ephemeral=True,
        )
        return

    cog = interaction.client.get_cog("ArchiveCog")  # type: ignore[attr-defined]
    if not isinstance(cog, ArchiveCog):
        await interaction.response.send_message(
            "⚠️ The archive subsystem is still starting up. Please try again shortly.",
            ephemeral=True,
        )
        return

    channel, error = cog._resolve_menu_channel(interaction.guild)
    if error == "No channel configured":
        await interaction.response.send_message(
            "⚠️ No archive channel configured yet. Configure one in the dashboard first.",
            ephemeral=True,
        )
        return
    if error:
        await interaction.response.send_message(
            "⚠️ The configured archive channel could not be found. Reconfigure it in the dashboard.",
            ephemeral=True,
        )
        return
    assert channel is not None

    bot_member = interaction.guild.me
    if bot_member is None and context.bot.user is not None:
        bot_member = interaction.guild.get_member(context.bot.user.id)

    missing_permissions: list[str] = []
    if bot_member is not None:
        perms = channel.permissions_for(bot_member)
        if not perms.view_channel:
            missing_permissions.append("View Channel")
        if not perms.send_messages:
            missing_permissions.append("Send Messages")
        if not perms.embed_links:
            missing_permissions.append("Embed Links")
    else:
        missing_permissions.extend(["View Channel", "Send Messages", "Embed Links"])

    if missing_permissions:
        await interaction.response.send_message(
            "⚠️ I am missing the following permissions in the configured channel: "
            + ", ".join(missing_permissions)
            + ".",
            ephemeral=True,
        )
        return

    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    try:
        result = await cog.deploy_for_guild(interaction.guild)
    except Exception:
        log.exception("Failed to spawn archive menu for guild %s", interaction.guild.id)
        sender = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        await sender("❌ Failed to spawn the archive menu. Please try again later.", ephemeral=True)
        return

    if not result:
        message = f"✅ Archive menu deployed to {channel.mention}."
    elif "posted message" in result:
        message = f"✅ Archive menu posted in {channel.mention}."
    elif "updated message" in result:
        message = f"🔄 Archive menu refreshed in {channel.mention}."
    elif "No channel configured" in result:
        message = "⚠️ No archive channel configured. Configure one in the dashboard first."
    elif "Configured channel not found" in result:
        message = "⚠️ The configured archive channel could not be found. Reconfigure it in the dashboard."
    else:
        message = f"✅ Archive menu updated: {result}."

    sender = (
        interaction.followup.send
        if interaction.response.is_done()
        else interaction.response.send_message
    )
    await sender(message, ephemeral=True)


def register(context: SpectreContext) -> None:
    bot = context.bot

    slash_command_kwargs: dict[str, Any] = {
        "name": "spawn",
        "description": "Spawn the archive menu in the configured channel.",
        "guild_ids": context.slash_guild_ids,
        "dm_permission": False,
        "default_member_permissions": nextcord.Permissions(manage_guild=True),
    }

    try:
        slash_command = bot.slash_command(**slash_command_kwargs)
    except TypeError as exc:
        if "dm_permission" in str(exc):
            log.debug(
                "nextcord version does not support dm_permission, removing argument",
            )
            slash_command_kwargs.pop("dm_permission", None)
            slash_command = bot.slash_command(**slash_command_kwargs)
        else:
            raise

    @slash_command
    async def spawn(interaction: nextcord.Interaction) -> None:
        await spawn_archive_menu_command(context, interaction)


__all__ = ["register", "spawn_archive_menu_command"]
