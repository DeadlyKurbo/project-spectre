"""Operator registration and identification commands."""

from __future__ import annotations

from datetime import UTC, datetime

import nextcord

from operator_login import (
    detect_clearance,
    get_or_create_operator,
    has_classified_clearance,
    list_operators,
    set_clearance,
)
from registration import start_registration

from async_utils import run_blocking
from ..context import SpectreContext


async def show_id_command(context: SpectreContext, interaction: nextcord.Interaction) -> None:
    if has_classified_clearance(interaction.user):
        card = (
            "[SPECTRE — OPERATOR IDENTIFICATION CARD]\n"
            "Operator: [REDACTED]\n"
            "ID Number: [REDACTED]\n"
            "Clearance: [REDACTED]\n"
            "Status: [REDACTED]\n"
            "Session: [REDACTED]"
        )
        return await interaction.response.send_message(card, ephemeral=True)

    op = next(
        (o for o in list_operators() if o.user_id == interaction.user.id and o.password_hash),
        None,
    )
    if not op:
        return await interaction.response.send_message(
            "No operator ID on file. Use /create-id to register.", ephemeral=True
        )

    member = getattr(interaction.guild, "get_member", lambda x: None)(op.user_id) or interaction.user
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    embed = nextcord.Embed(
        title="SPECTRE COMMAND — OPERATOR IDENTIFICATION CARD",
        color=0x2F3136,
    )
    display_name = getattr(member, "display_name", None) or getattr(member, "name", str(member))
    profile_name = op.name or display_name
    embed.add_field(name="Name", value=profile_name, inline=True)
    embed.add_field(
        name="Age",
        value=str(op.age) if op.age else "Unspecified",
        inline=True,
    )
    embed.add_field(name="Operator ID", value=op.id_code, inline=False)
    embed.add_field(name="Occupation", value=op.occupation or "Unassigned", inline=True)
    embed.add_field(name="Clearance", value=f"Level-{op.clearance}", inline=True)
    specialties_value = op.specialties or "Unspecified"
    embed.add_field(name="Specialties", value=specialties_value, inline=False)
    embed.add_field(name="Status", value=f"ACTIVE — Session {ts}", inline=False)
    avatar = getattr(member, "display_avatar", None)
    if avatar:
        embed.set_thumbnail(avatar.url)
    embed.set_author(name=display_name, icon_url=avatar.url if avatar else None)
    await interaction.response.send_message(interaction.user.mention, embed=embed, ephemeral=True)


async def create_id_command(context: SpectreContext, interaction: nextcord.Interaction) -> None:
    if has_classified_clearance(interaction.user):
        return await interaction.response.send_message(
            "Classified operatives are exempt from ID registration.", ephemeral=True
        )
    level = detect_clearance(interaction.user)

    op = await run_blocking(get_or_create_operator, interaction.user.id)
    if op.clearance != level:
        await run_blocking(set_clearance, interaction.user.id, level)
    if op.password_hash:
        return await interaction.response.send_message(
            "Operator ID already exists.", ephemeral=True
        )
    await start_registration(interaction, op, interaction.user)


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="show-id",
        description="Display operator ID cards",
        guild_ids=context.slash_guild_ids,
    )
    async def show_id(interaction: nextcord.Interaction) -> None:
        await show_id_command(context, interaction)

    @bot.slash_command(
        name="create-id",
        description="Begin operator ID registration",
        guild_ids=context.slash_guild_ids,
    )
    async def create_id(interaction: nextcord.Interaction) -> None:
        await create_id_command(context, interaction)


__all__ = ["register", "create_id_command", "show_id_command"]
