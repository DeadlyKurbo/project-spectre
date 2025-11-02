"""Placeholder commands for future request handling features."""

from __future__ import annotations

import nextcord

from ..context import SpectreContext


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="request",
        description="Submit requests",
        guild_ids=context.guild_ids,
    )
    async def request_root(interaction: nextcord.Interaction) -> None:  # pragma: no cover - placeholder
        await interaction.response.send_message(
            "Request handling is not implemented yet.", ephemeral=True
        )


__all__ = ["register"]
