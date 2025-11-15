"""Commands that share external links such as invites and dashboards."""

from __future__ import annotations

import nextcord
from nextcord import Embed

from ..context import SpectreContext
from ..interactions import build_link_view


def register(context: SpectreContext) -> None:
    bot = context.bot

    @bot.slash_command(
        name="invite",
        description="Get the Spectre invite link",
        guild_ids=context.slash_guild_ids,
    )
    async def invite(interaction: nextcord.Interaction) -> None:
        if not context.settings.bot_invite_url:
            return await interaction.response.send_message(
                " Invite link is not configured.", ephemeral=True
            )

        embed = Embed(
            title="Invite Spectre",
            description="Use the button below to invite Spectre to another server.",
            color=0x5865F2,
        )
        await interaction.response.send_message(
            embed=embed,
            view=build_link_view("Invite Spectre", context.settings.bot_invite_url),
            ephemeral=True,
        )

    @bot.slash_command(
        name="dashboard",
        description="Open the Spectre dashboard",
        guild_ids=context.slash_guild_ids,
    )
    async def dashboard(interaction: nextcord.Interaction) -> None:
        if not context.settings.dashboard_url:
            return await interaction.response.send_message(
                " Dashboard URL is not configured.", ephemeral=True
            )

        embed = Embed(
            title="Spectre Dashboard",
            description="Access Spectre's dashboard using the button below.",
            color=0x0FA3B1,
        )
        await interaction.response.send_message(
            embed=embed,
            view=build_link_view("Open Dashboard", context.settings.dashboard_url),
            ephemeral=True,
        )


__all__ = ["register"]
