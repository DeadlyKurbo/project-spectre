"""Slash commands for interacting with the Archivist console."""

from __future__ import annotations

import asyncio
import random

import nextcord
from nextcord import Embed

import archivist
import constants as _constants_module
from constants import (
    HIGH_COMMAND_DESC,
    HIGH_COMMAND_TITLE,
    LEAD_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    REG_ARCHIVIST_DESC,
    REG_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    TRAINEE_ARCHIVIST_TITLE,
)

from ..context import SpectreContext
from ..interactions import guild_id_from_interaction


async def maybe_simulate_hiccup(context: SpectreContext, interaction: nextcord.Interaction) -> bool:
    if random.random() < context.settings.hiccup_chance:
        await interaction.response.send_message(
            " Node ECHO-04 failed to respond, rerouting… please hold.",
            ephemeral=True,
        )
        await asyncio.sleep(random.randint(3, 5))
        await interaction.edit_original_message(
            content=" Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        await context.log_action(
            " Node ECHO-04 failed to respond, rerouting… please hold. Connection restored."
        )
        return True
    return False


async def open_archivist_console(
    context: SpectreContext, interaction: nextcord.Interaction
) -> None:
    if not archivist._is_archivist(interaction.user):
        return await interaction.response.send_message(" Archivist only.", ephemeral=True)
    sender = interaction.response.send_message
    if await maybe_simulate_hiccup(context, interaction):
        sender = interaction.followup.send
    is_high = archivist._is_high_command(interaction.user)
    if archivist.is_archive_locked() and not is_high:
        return await sender(" Archive access locked.", ephemeral=True)
    is_lead = is_high or archivist._is_lead_archivist(interaction.user)
    user_roles = {r.id for r in interaction.user.roles}
    trainee_role_id = getattr(_constants_module, "TRAINEE_ROLE_ID", 0)
    archivist_role_id = getattr(_constants_module, "ARCHIVIST_ROLE_ID", 0)
    is_trainee = (
        trainee_role_id in user_roles
        and not is_lead
        and archivist_role_id not in user_roles
    )
    gid = guild_id_from_interaction(interaction)
    view = (
        archivist.ArchivistConsoleView(interaction.user, guild_id=gid)
        if is_lead
        else archivist.ArchivistTraineeConsoleView(interaction.user, guild_id=gid)
        if is_trainee
        else archivist.ArchivistLimitedConsoleView(interaction.user, guild_id=gid)
    )
    if is_high:
        embed = Embed(
            title=HIGH_COMMAND_TITLE,
            description=HIGH_COMMAND_DESC,
            color=0xFF0000,
        )
    elif is_lead:
        embed = Embed(
            title=LEAD_ARCHIVIST_TITLE,
            description=LEAD_ARCHIVIST_DESC,
            color=0x3C2E7D,
        )
    elif is_trainee:
        embed = Embed(
            title=TRAINEE_ARCHIVIST_TITLE,
            description=TRAINEE_ARCHIVIST_DESC,
            color=0x00FFCC,
        )
    else:
        embed = Embed(
            title=REG_ARCHIVIST_TITLE,
            description=REG_ARCHIVIST_DESC,
            color=0x0FA3B1,
        )
    await sender(embed=embed, view=view, ephemeral=True)


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="archivist",
        description="Open the Archivist Console",
        guild_ids=context.guild_ids,
    )
    async def archivist_cmd(interaction: nextcord.Interaction) -> None:
        await open_archivist_console(context, interaction)


__all__ = ["register", "maybe_simulate_hiccup", "open_archivist_console"]
