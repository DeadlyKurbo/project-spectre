"""Slash command for mission report submission."""

from __future__ import annotations

import nextcord

from mission_reports import is_mission_reports_enabled, open_submit_flow

from ..context import SpectreContext
from ..interactions import guild_id_from_interaction


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="mission-report",
        description="Submit a structured mission report for review.",
        guild_ids=context.slash_guild_ids,
    )
    async def mission_report(interaction: nextcord.Interaction) -> None:
        gid = guild_id_from_interaction(interaction)
        if not gid or not is_mission_reports_enabled(gid):
            await interaction.response.send_message(
                "Mission reports are not enabled on this server.", ephemeral=True
            )
            return
        await open_submit_flow(interaction)
