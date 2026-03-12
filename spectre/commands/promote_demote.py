"""Promote and demote commands for user clearance level changes."""

from __future__ import annotations

import logging

import nextcord

from operator_login import detect_clearance, set_clearance
from server_config import get_roles_for_level

from ..context import SpectreContext

log = logging.getLogger(__name__)


def _get_member_display(member: nextcord.Member) -> str:
    """Return a display string for the member (mention or name)."""
    return member.mention if member else "Unknown"


async def promote_command(
    context: SpectreContext, interaction: nextcord.Interaction, user: nextcord.Member
) -> None:
    """Promote a user by one clearance level."""
    if not interaction.guild:
        await interaction.response.send_message(
            "This command can only be used within a server.", ephemeral=True
        )
        return

    guild_id = interaction.guild.id
    current_level = detect_clearance(user, guild_id)

    if current_level >= 6:
        await interaction.response.send_message(
            f"{_get_member_display(user)} is already at the highest clearance (Level 6 / High Command).",
            ephemeral=True,
        )
        return

    new_level = current_level + 1
    old_roles = get_roles_for_level(current_level, guild_id)
    new_roles = get_roles_for_level(new_level, guild_id)

    if not new_roles:
        await interaction.response.send_message(
            f"No roles configured for Level {new_level}. Check server configuration.",
            ephemeral=True,
        )
        return

    try:
        roles_to_remove = [r for r in interaction.guild.roles if r.id in old_roles]
        roles_to_add = [r for r in interaction.guild.roles if r.id in new_roles]

        if roles_to_remove:
            await user.remove_roles(*roles_to_remove, reason=f"Promoted from L{current_level} to L{new_level}")
        if roles_to_add:
            await user.add_roles(*roles_to_add, reason=f"Promoted to Level {new_level}")

        set_clearance(user.id, new_level)

        await interaction.response.send_message(
            f"Promoted {_get_member_display(user)} from Level {current_level} to Level {new_level}.",
            ephemeral=True,
        )

        log_msg = (
            f"{interaction.user.mention} promoted {_get_member_display(user)} "
            f"from Level {current_level} to Level {new_level}."
        )
        await context.log_action(
            log_msg,
            event_type="clearance_change",
            clearance=detect_clearance(interaction.user, guild_id),
            guild_id=guild_id,
        )
    except nextcord.Forbidden:
        log.warning("Promote failed: insufficient permissions for guild %s", guild_id)
        await interaction.response.send_message(
            "I don't have permission to modify roles. Ensure my role is above the level roles.",
            ephemeral=True,
        )
    except Exception:
        log.exception("Promote failed for user %s", user.id)
        await interaction.response.send_message(
            "Failed to promote. Check logs for details.",
            ephemeral=True,
        )


async def demote_command(
    context: SpectreContext, interaction: nextcord.Interaction, user: nextcord.Member
) -> None:
    """Demote a user by one clearance level."""
    if not interaction.guild:
        await interaction.response.send_message(
            "This command can only be used within a server.", ephemeral=True
        )
        return

    guild_id = interaction.guild.id
    current_level = detect_clearance(user, guild_id)

    if current_level <= 1:
        await interaction.response.send_message(
            f"{_get_member_display(user)} is already at the lowest clearance (Level 1).",
            ephemeral=True,
        )
        return

    new_level = current_level - 1
    old_roles = get_roles_for_level(current_level, guild_id)
    new_roles = get_roles_for_level(new_level, guild_id)

    if not new_roles:
        await interaction.response.send_message(
            f"No roles configured for Level {new_level}. Check server configuration.",
            ephemeral=True,
        )
        return

    try:
        roles_to_remove = [r for r in interaction.guild.roles if r.id in old_roles]
        roles_to_add = [r for r in interaction.guild.roles if r.id in new_roles]

        if roles_to_remove:
            await user.remove_roles(*roles_to_remove, reason=f"Demoted from L{current_level} to L{new_level}")
        if roles_to_add:
            await user.add_roles(*roles_to_add, reason=f"Demoted to Level {new_level}")

        set_clearance(user.id, new_level)

        await interaction.response.send_message(
            f"Demoted {_get_member_display(user)} from Level {current_level} to Level {new_level}.",
            ephemeral=True,
        )

        log_msg = (
            f"{interaction.user.mention} demoted {_get_member_display(user)} "
            f"from Level {current_level} to Level {new_level}."
        )
        await context.log_action(
            log_msg,
            event_type="clearance_change",
            clearance=detect_clearance(interaction.user, guild_id),
            guild_id=guild_id,
        )
    except nextcord.Forbidden:
        log.warning("Demote failed: insufficient permissions for guild %s", guild_id)
        await interaction.response.send_message(
            "I don't have permission to modify roles. Ensure my role is above the level roles.",
            ephemeral=True,
        )
    except Exception:
        log.exception("Demote failed for user %s", user.id)
        await interaction.response.send_message(
            "Failed to demote. Check logs for details.",
            ephemeral=True,
        )


def register(context: SpectreContext) -> None:
    bot = context.bot

    slash_kwargs: dict = {
        "guild_ids": context.slash_guild_ids,
        "dm_permission": False,
        "default_member_permissions": nextcord.Permissions(manage_roles=True),
    }

    @bot.slash_command(
        name="promote",
        description="Promote a user by one clearance level.",
        **slash_kwargs,
    )
    async def promote(
        interaction: nextcord.Interaction,
        user: nextcord.Member = nextcord.SlashOption(description="The user to promote"),
    ) -> None:
        await promote_command(context, interaction, user)

    @bot.slash_command(
        name="demote",
        description="Demote a user by one clearance level.",
        **slash_kwargs,
    )
    async def demote(
        interaction: nextcord.Interaction,
        user: nextcord.Member = nextcord.SlashOption(description="The user to demote"),
    ) -> None:
        await demote_command(context, interaction, user)


__all__ = ["register", "promote_command", "demote_command"]
