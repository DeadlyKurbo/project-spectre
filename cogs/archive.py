#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import nextcord
from nextcord.ext import commands
from nextcord import Interaction, SlashOption, Embed

from typing import Optional

from utils.guild_store import (
    get_config, set_config,
    get_anchor, set_anchor, clear_anchor
)

# ---------------- Constants ----------------
PERSISTENT_IDS = {
    "open_personnel": "spectre:archive:open_personnel",
    "open_mission":   "spectre:archive:open_mission",
    "open_intel":     "spectre:archive:open_intel",
    "refresh":        "spectre:archive:refresh",
}

def archive_title(guild_id: int) -> str:
    cfg = get_config(guild_id)
    return cfg["archive_name"] or "Project SPECTRE — Archive"

def archive_embed(guild_id: int) -> nextcord.Embed:
    e = Embed(
        title=f"📁 {archive_title(guild_id)}",
        description="Kies een sectie hieronder. Gebruik **Refresh** na updates.",
        color=0x2F3136,
    )
    e.set_footer(text=f"Guild {guild_id} • Digital Archive")
    return e

class ArchiveView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.primary,
            label="Personnel Files",
            custom_id=PERSISTENT_IDS["open_personnel"]
        ))
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.secondary,
            label="Mission Logs",
            custom_id=PERSISTENT_IDS["open_mission"]
        ))
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.success,
            label="Intelligence",
            custom_id=PERSISTENT_IDS["open_intel"]
        ))
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.gray,
            label="Refresh",
            custom_id=PERSISTENT_IDS["refresh"]
        ))

# --------------- Cog ----------------
class ArchiveCog(commands.Cog, name="ArchiveCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._view = ArchiveView()

    # re-attach persistent view on boot
    def register_persistent_view(self):
        try:
            self.bot.add_view(self._view)
        except Exception as e:
            print(f"[Archive] WARN could not add persistent view: {e}")

    # -------- Slash: /archive-config --------
    @nextcord.slash_command(description="Bekijk of wijzig archief-instellingen (per server opgeslagen).")
    async def archive_config(self, interaction: Interaction):
        pass  # parent, subcommands below

    # /archive-config set-channel
    @archive_config.subcommand(description="Stel het kanaal in waar het archief-menu moet staan.")
    async def set_channel(
        self,
        interaction: Interaction,
        channel: nextcord.abc.GuildChannel = SlashOption(
            name="channel",
            description="Tekstkanaal voor het archiefmenu",
            required=True
        )
    ):
        await interaction.response.defer(ephemeral=True)
        if not isinstance(channel, nextcord.TextChannel):
            await interaction.followup.send("❌ Kies een tekstkanaal.", ephemeral=True)
            return
        set_config(interaction.guild_id, archive_channel_id=channel.id)
        await interaction.followup.send(f"✅ Archiefkanaal ingesteld op {channel.mention}.", ephemeral=True)

    # /archive-config set-name
    @archive_config.subcommand(description="Stel de archief-naam in (verschijnt bovenaan het menu/embeds).")
    async def set_name(
        self,
        interaction: Interaction,
        name: str = SlashOption(
            name="name",
            description="Laat leeg voor standaardnaam",
            required=False
        )
    ):
        await interaction.response.defer(ephemeral=True)
        safe = (name or "").strip() or None
        set_config(interaction.guild_id, archive_name=safe)
        shown = safe or "standaard"
        await interaction.followup.send(f"✅ Archief-naam ingesteld op **{shown}**.", ephemeral=True)

    # /archive-config show
    @archive_config.subcommand(description="Toon de huidige archief-instellingen voor deze server.")
    async def show(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = get_config(interaction.guild_id)
        ch = interaction.guild.get_channel(cfg.get("archive_channel_id") or 0)
        ch_txt = ch.mention if isinstance(ch, nextcord.TextChannel) else "`(niet ingesteld)`"
        name_txt = cfg.get("archive_name") or "standaard"
        anc = get_anchor(interaction.guild_id)
        anc_txt = f"<#{anc[0]}> / `{anc[1]}`" if anc else "`(geen)`"
        e = Embed(title="Archive settings", color=0x0FA3B1)
        e.add_field(name="Archive name", value=name_txt, inline=False)
        e.add_field(name="Archive channel", value=ch_txt, inline=False)
        e.add_field(name="Menu anchor", value=anc_txt, inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    # -------- Slash: /archive-deploy --------
    @nextcord.slash_command(description="Plaats of ververs het archief-menu in het ingestelde kanaal.")
    async def archive_deploy(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        cfg = get_config(interaction.guild_id)
        ch_id = cfg.get("archive_channel_id")
        if not ch_id:
            await interaction.followup.send(
                "❌ Geen kanaal ingesteld. Run eerst `/archive-config set-channel`.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(ch_id)
        if not isinstance(channel, nextcord.TextChannel):
            await interaction.followup.send(
                "❌ Het ingestelde kanaal bestaat niet meer. Stel opnieuw in.",
                ephemeral=True
            )
            return

        # Edit bestaand bericht indien bekend, anders nieuw bericht posten
        anchor = get_anchor(interaction.guild_id)
        view = self._view
        embed = archive_embed(interaction.guild_id)
        posted: Optional[nextcord.Message] = None

        if anchor:
            a_ch, a_msg = anchor
            if a_ch == channel.id:
                try:
                    old = await channel.fetch_message(a_msg)
                    await old.edit(embed=embed, view=view)
                    posted = old
                except Exception:
                    posted = None

        if posted is None:
            msg = await channel.send(embed=embed, view=view)
            set_anchor(interaction.guild_id, channel.id, msg.id)
            posted = msg

        await interaction.followup.send(
            f"✅ Archive menu actief in {channel.mention} (message id `{posted.id}`).",
            ephemeral=True
        )

    # -------- Buttons (component router) --------
    @commands.Cog.listener("on_interaction")
    async def route_buttons(self, interaction: Interaction):
        if interaction.type != nextcord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id")
        if cid not in PERSISTENT_IDS.values():
            return

        # Snel ack'en om timeouts te voorkomen
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
        except Exception:
            pass

        # Demo responses — hier jouw echte logic aan koppelen (per guild files)
        if cid == PERSISTENT_IDS["open_personnel"]:
            await interaction.followup.send("👤 Personnel Files (demo)", ephemeral=True)
        elif cid == PERSISTENT_IDS["open_mission"]:
            await interaction.followup.send("📝 Mission Logs (demo)", ephemeral=True)
        elif cid == PERSISTENT_IDS["open_intel"]:
            await interaction.followup.send("🛰️ Intelligence (demo)", ephemeral=True)
        elif cid == PERSISTENT_IDS["refresh"]:
            anc = get_anchor(interaction.guild_id)
            if not anc:
                await interaction.followup.send("⚠️ Geen anchor. Run `/archive-deploy`.", ephemeral=True)
                return
            ch = interaction.guild.get_channel(anc[0])
            if not isinstance(ch, nextcord.TextChannel):
                await interaction.followup.send("⚠️ Kanaal niet gevonden. Stel opnieuw in.", ephemeral=True)
                return
            try:
                m = await ch.fetch_message(anc[1])
                await m.edit(embed=archive_embed(interaction.guild_id), view=self._view)
                await interaction.followup.send("🔄 Menu refreshed.", ephemeral=True)
            except Exception:
                await interaction.followup.send("⚠️ Kon bericht niet verversen.", ephemeral=True)

def setup(bot: commands.Bot):
    bot.add_cog(ArchiveCog(bot))
