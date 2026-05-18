"""Slash commands for the mission reports menu."""

from __future__ import annotations

import logging
from typing import Any

import nextcord

from mission_reports import is_mission_reports_enabled, refresh_mission_reports_menu
from server_config import get_server_config

from ..context import SpectreContext
from ..interactions import guild_id_from_interaction

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


def _resolve_menu_channel(guild: nextcord.Guild) -> tuple[nextcord.abc.GuildChannel | None, str | None, int | None]:
    try:
        cfg = get_server_config(guild.id)
    except Exception:
        log.exception("Failed loading server configuration for guild %s", guild.id)
        return None, "Configuration unavailable", None

    channel_id = cfg.get("MISSION_REPORTS_MENU_CHANNEL_ID")
    if not channel_id:
        mr = cfg.get("mission_reports")
        if isinstance(mr, dict):
            channel_id = mr.get("menu_channel")
    try:
        channel_id = int(channel_id) if channel_id else 0
    except (TypeError, ValueError):
        channel_id = 0
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


async def spawn_mission_reports_menu_command(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    if not interaction.guild:
        await interaction.response.send_message(
            "This command can only be used within a server.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    if not is_mission_reports_enabled(guild.id):
        await interaction.response.send_message(
            "Mission reports are not enabled on this server. Enable them in the dashboard first.",
            ephemeral=True,
        )
        return

    channel, error, channel_id = _resolve_menu_channel(guild)
    if error == "No channel configured":
        await interaction.response.send_message(
            "No mission reports menu channel configured yet. Set one in the dashboard first.",
            ephemeral=True,
        )
        return
    if error == "Configured channel not found":
        await interaction.response.send_message(
            "The configured mission reports channel could not be found.",
            ephemeral=True,
        )
        return
    if error == "Configuration unavailable" or channel is None:
        await interaction.response.send_message(
            "Configuration could not be loaded. Please try again shortly.",
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
            "Missing permissions in the configured channel: " + ", ".join(missing_permissions) + ".",
            ephemeral=True,
        )
        return

    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    message: str
    try:
        await refresh_mission_reports_menu(guild, menu_channel_override=channel_id)
        message = f"Mission reports menu deployed in {channel.mention}."
    except ValueError as exc:
        message = f"Could not deploy menu: {exc}"
    except Exception:
        log.exception("Failed to deploy mission reports menu for guild %s", guild.id)
        message = "Failed to deploy the mission reports menu."

    sender = (
        interaction.followup.send
        if interaction.response.is_done()
        else interaction.response.send_message
    )
    await sender(message, ephemeral=True)


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="mission-report",
        description="Submit a structured mission report for review.",
        guild_ids=context.slash_guild_ids,
    )
    async def mission_report(interaction: nextcord.Interaction) -> None:
        from mission_reports import open_submit_flow

        gid = guild_id_from_interaction(interaction)
        if not gid or not is_mission_reports_enabled(gid):
            await interaction.response.send_message(
                "Mission reports are not enabled on this server.", ephemeral=True
            )
            return
        await open_submit_flow(interaction)

    spawn_kwargs: dict[str, Any] = {
        "name": "spawn-mission-reports",
        "description": "Spawn the mission reports menu in the configured channel.",
        "guild_ids": context.slash_guild_ids,
        "dm_permission": False,
        "default_member_permissions": nextcord.Permissions(manage_guild=True),
    }
    try:
        spawn_cmd = bot.slash_command(**spawn_kwargs)
    except TypeError as exc:
        if "dm_permission" in str(exc):
            spawn_kwargs.pop("dm_permission", None)
            spawn_cmd = bot.slash_command(**spawn_kwargs)
        else:
            raise

    @spawn_cmd
    async def spawn_mission_reports(interaction: nextcord.Interaction) -> None:
        await spawn_mission_reports_menu_command(context, interaction)
