#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

import nextcord
from nextcord.ext import commands
from nextcord import Embed, Permissions

from archivist import extract_menu_channel_id
from server_config import get_server_config
from utils.guild_store import (
    get_config,
    get_anchor,
    set_anchor,
    clear_anchor,
)


log = logging.getLogger(__name__)

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
        self.add_item(nextcord.ui.Button(style=nextcord.ButtonStyle.primary, label="Mission Logs",     custom_id=PERSISTENT_IDS["open_mission"]))
        self.add_item(nextcord.ui.Button(style=nextcord.ButtonStyle.primary, label="Intelligence",     custom_id=PERSISTENT_IDS["open_intel"]))
        self.add_item(nextcord.ui.Button(style=nextcord.ButtonStyle.gray,    label="Refresh",          custom_id=PERSISTENT_IDS["refresh"]))

class ArchiveCog(commands.Cog, name="ArchiveCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._view = ArchiveView()

    # persistent view registreren zodat buttons blijven werken na reboot
    def register_persistent_view(self):
        try:
            self.bot.add_view(self._view)
        except Exception as e:
            print(f"[Archive] WARN add_view: {e}")

    def _resolve_menu_channel_id(self, guild_id: int) -> int | None:
        """Return the configured archive menu channel for ``guild_id``."""

        cfg = get_config(guild_id)
        legacy_value = cfg.get("archive_channel_id") if isinstance(cfg, dict) else None
        channel_id: int | None = None
        if legacy_value is not None:
            try:
                coerced = int(legacy_value)
            except (TypeError, ValueError):
                coerced = 0
            if coerced > 0:
                channel_id = coerced

        if channel_id is None:
            remote_cfg = get_server_config(guild_id)
            channel_id = extract_menu_channel_id(remote_cfg)

        return channel_id

    def _resolve_menu_channel(
        self, guild: nextcord.Guild
    ) -> tuple[nextcord.TextChannel | None, str | None]:
        """Locate the configured archive menu channel for ``guild``."""

        channel_id = self._resolve_menu_channel_id(guild.id)
        if not channel_id:
            return None, "No channel configured"

        getter = getattr(guild, "get_channel_or_thread", None)
        if callable(getter):
            channel = getter(channel_id)
        else:
            channel = guild.get_channel(channel_id)
        if not isinstance(channel, nextcord.TextChannel):
            return None, "Configured channel not found"

        return channel, None

    # Programmatic deploy (website -> bot)
    async def deploy_for_guild(self, guild: nextcord.Guild) -> str:
        channel, error = self._resolve_menu_channel(guild)
        if error:
            return error
        assert channel is not None

        embed = archive_embed(guild.id)
        view  = self._view

        anchor = get_anchor(guild.id)
        if anchor and anchor[0] == channel.id:
            try:
                msg = await channel.fetch_message(anchor[1])
                await msg.edit(embed=embed, view=view)
                return f"updated message {msg.id}"
            except Exception:
                pass

        msg = await channel.send(embed=embed, view=view)
        set_anchor(guild.id, channel.id, msg.id)
        return f"posted message {msg.id}"

    @nextcord.slash_command(
        name="spawn",
        description="Spawn the archive menu in the configured channel.",
        dm_permission=False,
        default_member_permissions=Permissions(manage_guild=True),
    )
    async def spawn_archive_menu(self, interaction: nextcord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "⚠️ This command can only be used within a server.",
                ephemeral=True,
            )
            return

        channel, error = self._resolve_menu_channel(interaction.guild)
        if error == "No channel configured":
            await interaction.response.send_message(
                "⚠️ No archive channel configured yet. Configure one in the dashboard first.",
                ephemeral=True,
            )
            return
        if error:
            await interaction.response.send_message(
                "⚠️ The configured archive channel could not be found. Reconfigure it in the dashboard.",
                ephemeral=True,
            )
            return
        assert channel is not None

        bot_member = interaction.guild.me
        if bot_member is None and self.bot.user is not None:
            bot_member = interaction.guild.get_member(self.bot.user.id)

        missing_permissions: list[str] = []
        if bot_member is not None:
            perms = channel.permissions_for(bot_member)
            if not perms.view_channel:
                missing_permissions.append("View Channel")
            if not perms.send_messages:
                missing_permissions.append("Send Messages")
            if not perms.embed_links:
                missing_permissions.append("Embed Links")
        else:
            missing_permissions.extend(["View Channel", "Send Messages", "Embed Links"])

        if missing_permissions:
            await interaction.response.send_message(
                "⚠️ I am missing the following permissions in the configured channel: "
                + ", ".join(missing_permissions)
                + ".",
                ephemeral=True,
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            # If we cannot defer we still continue and try to respond directly afterwards.
            pass

        try:
            result = await self.deploy_for_guild(interaction.guild)
        except Exception:
            log.exception("Failed to spawn archive menu for guild %s", interaction.guild.id)
            sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await sender(
                "❌ Failed to spawn the archive menu. Please try again later.",
                ephemeral=True,
            )
            return

        if not result:
            message = f"✅ Archive menu deployed to {channel.mention}."
        elif "posted message" in result:
            message = f"✅ Archive menu posted in {channel.mention}."
        elif "updated message" in result:
            message = f"🔄 Archive menu refreshed in {channel.mention}."
        elif "No channel configured" in result:
            message = "⚠️ No archive channel configured. Configure one in the dashboard first."
        elif "Configured channel not found" in result:
            message = "⚠️ The configured archive channel could not be found. Reconfigure it in the dashboard."
        else:
            message = f"✅ Archive menu updated: {result}."

        sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await sender(message, ephemeral=True)

    @commands.Cog.listener("on_interaction")
    async def route_buttons(self, interaction: nextcord.Interaction):
        if interaction.type != nextcord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id")
        if cid not in PERSISTENT_IDS.values():
            return

        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
        except Exception:
            pass

        if cid == PERSISTENT_IDS["open_personnel"]:
            await interaction.followup.send("👤 Personnel Files (demo)", ephemeral=True)
        elif cid == PERSISTENT_IDS["open_mission"]:
            await interaction.followup.send("📝 Mission Logs (demo)", ephemeral=True)
        elif cid == PERSISTENT_IDS["open_intel"]:
            await interaction.followup.send("🛰️ Intelligence (demo)", ephemeral=True)
        elif cid == PERSISTENT_IDS["refresh"]:
            anc = get_anchor(interaction.guild_id)
            if not anc:
                await interaction.followup.send("⚠️ No anchor. Configure via website, then deploy.", ephemeral=True)
                return
            ch = interaction.guild.get_channel(anc[0])
            if not isinstance(ch, nextcord.TextChannel):
                await interaction.followup.send("⚠️ Channel missing. Reconfigure.", ephemeral=True)
                return
            try:
                m = await ch.fetch_message(anc[1])
                await m.edit(embed=archive_embed(interaction.guild_id), view=self._view)
                await interaction.followup.send("🔄 Menu refreshed.", ephemeral=True)
            except Exception:
                await interaction.followup.send("⚠️ Could not refresh.", ephemeral=True)

def setup(bot: commands.Bot):
    cog = ArchiveCog(bot)
    bot.add_cog(cog)
    # registreer de view direct bij laden (belangrijk voor persistent UI)
    cog.register_persistent_view()
