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
            "[GLACIER UNIT 7 — OPERATOR IDENTIFICATION CARD]\n"
            "Operator: [REDACTED]\n"
            "ID Number: [REDACTED]\n"
            "Clearance: [REDACTED]\n"
            "Status: [REDACTED]\n"
            "Session: [REDACTED]"
        )
        return await interaction.response.send_message(card)

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
    card = (
        "[GLACIER UNIT 7 — OPERATOR IDENTIFICATION CARD]\n"
        f"Operator: {member.mention}\n"
        f"ID Number: {op.id_code}\n"
        f"Clearance: Level-{op.clearance}\n"
        "Status: ACTIVE\n"
        f"Session: {ts}"
    )
    await interaction.response.send_message(card)


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
