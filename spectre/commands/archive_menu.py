"""Slash command entrypoint for (legacy) archive menu deployment."""

from __future__ import annotations

import logging
from typing import Any

import nextcord

from cogs.archive import ArchiveCog

from archivist import extract_menu_channel_id, refresh_menus
from server_config import get_server_config

from ..context import SpectreContext

log = logging.getLogger(__name__)


def _coerce_text_channel(channel: object) -> nextcord.abc.GuildChannel | None:
    if channel is None:
        return None
    channel_type = getattr(channel, "type", None)
    if channel_type is not None:
        try:
            if channel_type != nextcord.ChannelType.text:
                return None
        except AttributeError:
            return None
    required_attrs = ("permissions_for", "mention")
    if not all(hasattr(channel, attr) for attr in required_attrs):
        return None
    return channel  # type: ignore[return-value]


def _resolve_modern_menu_channel(
    guild: nextcord.Guild,
) -> tuple[nextcord.abc.GuildChannel | None, str | None, int | None]:
    """Resolve the configured archive menu channel via dashboard settings."""

    try:
        cfg = get_server_config(guild.id)
    except Exception:
        log.exception("Failed loading server configuration for guild %s", guild.id)
        return None, "Configuration unavailable", None

    channel_id = extract_menu_channel_id(cfg)
    if not channel_id:
        return None, "No channel configured", None

    getter = getattr(guild, "get_channel_or_thread", None)
    if callable(getter):
        channel = getter(channel_id)
    else:
        channel = guild.get_channel(channel_id)

    channel = _coerce_text_channel(channel)
    if channel is None:
        return None, "Configured channel not found", channel_id

    return channel, None, channel_id


async def spawn_archive_menu_command(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    """Deploy the archive menu while avoiding duplicate menu posts."""

    if not interaction.guild:
        await interaction.response.send_message(
            "⚠️ This command can only be used within a server.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    modern_channel, modern_error, modern_channel_id = _resolve_modern_menu_channel(guild)
    cog = interaction.client.get_cog("ArchiveCog")  # type: ignore[attr-defined]

    channel = modern_channel
    error = modern_error

    if channel is None and isinstance(cog, ArchiveCog):
        channel, error = cog._resolve_menu_channel(guild)

    if error == "No channel configured":
        await interaction.response.send_message(
            "⚠️ No archive channel configured yet. Configure one in the dashboard first.",
            ephemeral=True,
        )
        return
    if error == "Configured channel not found":
        await interaction.response.send_message(
            "⚠️ The configured archive channel could not be found. Reconfigure it in the dashboard.",
            ephemeral=True,
        )
        return
    if error == "Configuration unavailable":
        await interaction.response.send_message(
            "⚠️ The archive configuration could not be loaded. Please try again shortly.",
            ephemeral=True,
        )
        return
    if channel is None:
        await interaction.response.send_message(
            "⚠️ The archive subsystem is still starting up. Please try again shortly.",
            ephemeral=True,
        )
        return

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

    refresh_message: str | None = None
    refresh_failed = False
    menu_channel_override = None if modern_channel_id is not None else channel.id
    try:
        await refresh_menus(guild, menu_channel_override=menu_channel_override)
        refresh_message = f"✅ Archive console refreshed in {channel.mention}."
    except Exception:
        refresh_failed = True
        log.exception("Failed to refresh archive console for guild %s", guild.id)

    legacy_required = refresh_failed and modern_channel_id is None
    legacy_result: str | None = None
    legacy_error: str | None = None
    # We only fall back to the legacy deployment path when modern refresh fails
    # and no dashboard menu channel is configured. This keeps the command
    # resilient while preventing duplicate menu posts in healthy scenarios.
    if legacy_required and isinstance(cog, ArchiveCog):
        try:
            legacy_result = await cog.deploy_for_guild(guild)
        except Exception:
            log.exception("Failed to spawn archive menu for guild %s", guild.id)
            if legacy_required:
                sender = (
                    interaction.followup.send
                    if interaction.response.is_done()
                    else interaction.response.send_message
                )
                await sender(
                    "❌ Failed to spawn the archive menu. Please try again later.",
                    ephemeral=True,
                )
                return
            legacy_error = "⚠️ Legacy archive menu deployment failed."

    if refresh_failed and not refresh_message:
        refresh_message = "⚠️ Failed to refresh the modern archive console."

    message_parts: list[str] = []

    if refresh_message:
        message_parts.append(refresh_message)

    if legacy_result:
        if "posted message" in legacy_result:
            message_parts.append(f"✅ Archive menu posted in {channel.mention}.")
        elif "updated message" in legacy_result:
            message_parts.append(f"🔄 Archive menu refreshed in {channel.mention}.")
        elif "No channel configured" in legacy_result:
            message_parts.append(
                "⚠️ No archive channel configured. Configure one in the dashboard first."
            )
        elif "Configured channel not found" in legacy_result:
            message_parts.append(
                "⚠️ The configured archive channel could not be found. Reconfigure it in the dashboard."
            )
        elif legacy_result:
            message_parts.append(f"✅ Archive menu updated: {legacy_result}.")
    elif legacy_required and not refresh_message:
        message_parts.append(f"✅ Archive menu deployed to {channel.mention}.")

    if legacy_error:
        message_parts.append(legacy_error)

    if not message_parts:
        message_parts.append("⚠️ No archive changes were made. Please verify the dashboard configuration.")

    sender = (
        interaction.followup.send
        if interaction.response.is_done()
        else interaction.response.send_message
    )
    await sender("\n".join(message_parts), ephemeral=True)


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
