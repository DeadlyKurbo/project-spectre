"""Answer every interaction from a blacklisted Discord server with a ban notice."""

from __future__ import annotations

import asyncio
import logging

import nextcord
from nextcord.ext import commands

from guild_blacklist import is_guild_blacklisted

from .interactions import build_link_view

BLACKLISTED_NOTICE = (
    "⛔ **This server has been blacklisted from SPECTRE.**\n"
    "The administration has banned this server from using the bot, so it no longer "
    "responds to commands, buttons or forms here. To appeal, join our Discord server."
)
APPEAL_URL = "https://discord.gg/rF2CSjzrEd"


def install_blacklist_gate(bot: commands.Bot, logger: logging.Logger) -> None:
    """Refuse interactions from blacklisted servers before any command, button or form sees them.

    Slash commands, components and modals all arrive as one gateway event, so
    the gate wraps that event's parser. Interactions it refuses are never
    dispatched to views, modals or ``on_interaction`` listeners.
    """

    parsers = bot._connection.parsers
    original = parsers.get("INTERACTION_CREATE")
    if original is None:
        logger.error("Could not install the server blacklist gate: no INTERACTION_CREATE parser")
        return

    pending: set[asyncio.Task[None]] = set()

    def parse_interaction_create(data: dict) -> None:
        if not is_guild_blacklisted(data.get("guild_id")):
            original(data)
            return
        task = bot.loop.create_task(_refuse(bot.get_interaction(data=data), logger))
        pending.add(task)
        task.add_done_callback(pending.discard)

    # The gateway reads parsers from this same dict, so swap the entry in place.
    parsers["INTERACTION_CREATE"] = parse_interaction_create


async def _refuse(interaction: nextcord.Interaction, logger: logging.Logger) -> None:
    try:
        if interaction.type == nextcord.InteractionType.application_command_autocomplete:
            await interaction.response.send_autocomplete([])
        else:
            await interaction.response.send_message(
                BLACKLISTED_NOTICE, view=build_link_view("Appeal the ban", APPEAL_URL), ephemeral=True
            )
    except Exception:
        logger.warning(
            "Failed to send the blacklist notice in server %s", interaction.guild_id, exc_info=True
        )


__all__ = ["APPEAL_URL", "BLACKLISTED_NOTICE", "install_blacklist_gate"]
