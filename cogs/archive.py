#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import nextcord
from nextcord.ext import commands
from nextcord import Embed
from typing import Optional

from utils.guild_store import get_config, set_config, get_anchor, set_anchor, clear_anchor

PERSISTENT_IDS = {
    "open_personnel": "spectre:archive:open_personnel",
    "open_mission":   "spectre:archive:open_mission",
    "open_intel":     "spectre:archive:open_intel",
    "refresh":        "spectre:archive:refresh",
}

def archive_title(gid: int) -> str:
    cfg = get_config(gid)
    return cfg.get("archive_title") or "Digital Archive"

def archive_embed(gid: int) -> nextcord.Embed:
    e = Embed(
        title=f"📁 {archive_title(gid)}",
        description="Kies een sectie. Gebruik **Refresh** na updates.",
        color=0x2F3136,
    )
    e.set_footer(text=f"Guild {gid} • Digital Archive")
    return e

class ArchiveView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(nextcord.ui.Button(style=nextcord.ButtonStyle.primary, label="Personnel Files", custom_id=PERSISTENT_IDS["open_personnel"]))
        self.add_item(nextcord.ui.Button(style=nextcord.ButtonStyle.p_
