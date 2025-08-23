"""Roster management utilities for the Glacier Unit 9 Discord server.

This module exposes helpers to build a roster embed and a view with a few
basic interaction buttons.  The goal is to automate the message found in the
roster channel by generating it from guild data instead of editing it manually.

Only a small subset of behaviour is implemented to keep this module testable
without a live Discord connection.  The core piece of logic is the
``build_roster`` function which inspects roles and members of a guild object
and returns structured data.  Higher level utilities convert that data into a
``nextcord.Embed`` ready to be sent to Discord.

Actual button interaction callbacks are minimal and mostly wrappers around the
``send_roster`` coroutine which refreshes the message in place.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

import nextcord
from nextcord import Embed, SelectOption
from nextcord.ui import Button, View, Select
from nextcord import ButtonStyle

# Mapping of role IDs to display information.  Each entry contains the role ID,
# the emoji prefix used in the roster and the human friendly role name.  The
# IDs are defined by the user request and mirror the manual roster message.
ROSTER_ROLES: Sequence[Tuple[int, str, str]] = (
    (1365087286785474701, "👑", "Owner"),
    (1365087291424510022, "🛰️", "Fleet Admiral"),
    (1365087292473086102, "🛡️", "Officer Of The Deck"),
    (1365087305085223084, "⭐", "Captain"),
    (1402032805453627412, "🎯", "Veteran Officer"),
    (1365087307551740019, "⚙️", "Officer"),
    (1402033076967837768, "🧪", "Specialist"),
    (1365087308642127994, "📘", "Seamen"),
    (1402033315892039711, "🟡", "Trainee"),
    (1405932476089765949, "📚", "Lead-Archivist"),
    (1405757611919544360, "📚", "Archivist"),
)


def build_roster(guild: nextcord.Guild) -> List[Tuple[str, str, List[str]]]:
    """Return a list of ``(emoji, role_name, member_names)`` for the guild.

    The function gracefully skips roles that are missing from the guild and
    sorts the member names alphabetically to provide a deterministic output,
    which is convenient both for humans and for tests.
    """

    roster: List[Tuple[str, str, List[str]]] = []
    for role_id, emoji, role_name in ROSTER_ROLES:
        role = guild.get_role(role_id)
        if not role:
            # Role might not exist in smaller test guilds; simply skip it.
            continue
        members = sorted(
            getattr(role, "members", []), key=lambda m: getattr(m, "display_name", "").lower()
        )
        roster.append((emoji, role_name, [m.mention for m in members]))
    return roster


def roster_embed(guild: nextcord.Guild) -> Embed:
    """Create an embed representation of the roster for ``guild``."""

    embed = Embed(title="GLACIER UNIT 9 — PERSONNEL ROSTER")
    for emoji, role_name, members in build_roster(guild):
        if members:
            value = "\n".join(members)
        else:
            value = "—"
        embed.add_field(name=f"{emoji} {role_name}", value=value, inline=False)
    return embed


class RosterView(View):
    """Simple view containing refresh/add/remove buttons.

    The callbacks are intentionally lightweight – only the refresh button is
    wired to regenerate the roster embed.  The add/remove buttons are provided
    for completeness but require further implementation in a real bot.
    """

    def __init__(self, guild: nextcord.Guild):
        super().__init__(timeout=None)
        self.guild = guild

        refresh = Button(label="Refresh", style=ButtonStyle.primary)
        refresh.callback = self._refresh
        self.add_item(refresh)

        add = Button(label="Add", style=ButtonStyle.success)
        add.callback = self._not_implemented
        self.add_item(add)

        remove = Button(label="Remove", style=ButtonStyle.danger)
        remove.callback = self._not_implemented
        self.add_item(remove)

    async def _refresh(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.edit_message(embed=roster_embed(self.guild))

    async def _not_implemented(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.send_message(
            "This action is not yet implemented.", ephemeral=True
        )


class RosterSelect(Select):
    """Dropdown listing roster roles; shows members when selected."""

    def __init__(self, guild: nextcord.Guild):
        options = [
            SelectOption(label=name, value=str(role_id))
            for role_id, _emoji, name in ROSTER_ROLES
            if guild.get_role(role_id)
        ]
        super().__init__(
            placeholder="Select role…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="roster_role_v1",
        )
        self.guild = guild

    async def callback(self, interaction: nextcord.Interaction) -> None:
        role_id = int(self.values[0])
        role = self.guild.get_role(role_id)
        members = sorted(
            getattr(role, "members", []), key=lambda m: m.display_name.lower()
        )
        desc = "\n".join(m.mention for m in members) if members else "—"
        embed = Embed(title=f"{role.name} — Roster", description=desc)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RosterMenuView(View):
    """Root view mimicking the archive menu but for the roster."""

    def __init__(self, guild: nextcord.Guild):
        super().__init__(timeout=None)
        self.guild = guild
        self.add_item(RosterSelect(guild))
        refresh = Button(label="Refresh", style=ButtonStyle.primary, custom_id="roster_refresh_v1")

        async def _refresh(interaction: nextcord.Interaction) -> None:
            await interaction.response.edit_message(
                embed=roster_embed(guild), view=RosterMenuView(guild)
            )

        refresh.callback = _refresh
        self.add_item(refresh)


async def send_roster(channel: nextcord.abc.Messageable, guild: nextcord.Guild) -> None:
    """Send a roster menu message to ``channel``."""

    await channel.send(embed=roster_embed(guild), view=RosterMenuView(guild))
