"""Shared helpers for dealing with Nextcord interactions and UI widgets."""

from __future__ import annotations

import nextcord
from nextcord.ui import Button, View


def build_link_view(label: str, url: str) -> View:
    view = View()
    view.add_item(Button(label=label, url=url))
    return view


def guild_id_from_interaction(interaction: nextcord.Interaction) -> int | None:
    gid = getattr(interaction, "guild_id", None)
    if gid is None:
        guild_obj = getattr(interaction, "guild", None)
        if guild_obj is not None:
            gid = getattr(guild_obj, "id", None)
    return gid


__all__ = ["build_link_view", "guild_id_from_interaction"]
