import re
from collections import defaultdict
from datetime import datetime, UTC, timedelta
import asyncio

import nextcord
from nextcord.ext import commands

from config import (
    set_log_channel,
    set_min_account_age_days,
    set_report_channel,
)
from constants import GUILD_ID
from mod_notes import list_member_notes

INVITE_PATTERN = re.compile(
    r"(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9]+",
    re.IGNORECASE,
)

WEBHOOK_PATTERN = re.compile(
    r"discord(?:app)?\.com/api/webhooks/\d+/\S+",
    re.IGNORECASE,
)


def contains_discord_invite(text: str) -> bool:
    """Return ``True`` if ``text`` contains a Discord invite link."""
    return bool(INVITE_PATTERN.search(text or ""))


def contains_discord_webhook(text: str) -> bool:
    """Return ``True`` if ``text`` contains a Discord webhook URL."""
    return bool(WEBHOOK_PATTERN.search(text or ""))


class ReportModal(nextcord.ui.Modal):
    """Modal for collecting a report reason and alerting moderators."""

    def __init__(self, target_message: nextcord.Message):
        super().__init__("Report to Moderators")
        self.target_message = target_message
        self.reason = nextcord.ui.TextInput(
            label="Reason",
            style=nextcord.TextInputStyle.paragraph,
            required=True,
            max_length=400,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction) -> None:
        import main

        channel = interaction.client.get_channel(main.REPORT_CHANNEL_ID)
        if channel is None:
            await interaction.response.send_message(
                " Reporting channel not configured.", ephemeral=True
            )
            return

        embed = nextcord.Embed(
            title="Message Report",
            description=self.target_message.content or "[no content]",
            timestamp=datetime.now(UTC),
            colour=0xE74C3C,
        )
        embed.add_field(name="Reporter", value=interaction.user.mention, inline=False)
        embed.add_field(
            name="Author", value=self.target_message.author.mention, inline=False
        )
        embed.add_field(
            name="Channel", value=self.target_message.channel.mention, inline=False
        )
        embed.add_field(
            name="Jump", value=f"[Link]({self.target_message.jump_url})", inline=False
        )
        embed.add_field(name="Reason", value=self.reason.value, inline=False)

        try:
            await channel.send(
                "@everyone",
                embed=embed,
                flags=nextcord.MessageFlags(suppress_notifications=True),
            )
        except Exception:
            pass

        await interaction.response.send_message("Report submitted.", ephemeral=True)
        await main.log_action(
            f" {interaction.user.mention} reported message {self.target_message.id} by {self.target_message.author.mention}: {self.reason.value}"
        )


class Moderation(commands.Cog):
    """Moderation helpers including logging and auto-moderation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track channel creations per user for nuke prevention
        self._channel_creations: defaultdict[int, list[datetime]] = defaultdict(list)

    # Slash commands -----------------------------------------------------

    @nextcord.slash_command(
        name="setlog", description="Set the moderation log channel", guild_ids=[GUILD_ID]
    )
    async def set_log_channel_cmd(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        """Persist ``channel`` as the destination for moderation logs."""
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        set_log_channel(channel.id)
        # Update main.LOG_CHANNEL_ID without circular import issues
        import main  # Local import to avoid circular dependency

        main.LOG_CHANNEL_ID = channel.id
        await interaction.response.send_message(
            f" Log channel set to {channel.mention}", ephemeral=True
        )
        await main.log_action(
            f" {interaction.user.mention} set log channel to {channel.mention}."
        )

    @nextcord.slash_command(
        name="setreport",
        description="Set the moderator report channel",
        guild_ids=[GUILD_ID],
    )
    async def set_report_channel_cmd(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        """Persist ``channel`` as the destination for user reports."""
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        set_report_channel(channel.id)
        import main

        main.REPORT_CHANNEL_ID = channel.id
        await interaction.response.send_message(
            f" Report channel set to {channel.mention}", ephemeral=True
        )
        await main.log_action(
            f" {interaction.user.mention} set report channel to {channel.mention}."
        )

    @nextcord.message_command(
        name="Report to Mods", guild_ids=[GUILD_ID]
    )
    async def report_to_mods(
        self, interaction: nextcord.Interaction, message: nextcord.Message
    ):
        """Prompt reporter for a reason and forward to moderators."""
        modal = ReportModal(message)
        await interaction.response.send_modal(modal)

    @nextcord.slash_command(
        name="setminage",
        description="Set minimum account age in days",
        guild_ids=[GUILD_ID],
    )
    async def set_min_account_age_cmd(
        self, interaction: nextcord.Interaction, days: int
    ):
        """Require joining accounts to be at least ``days`` old."""
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        set_min_account_age_days(days)
        import main

        main.MIN_ACCOUNT_AGE_DAYS = days
        await interaction.response.send_message(
            f" Minimum account age set to {days} days", ephemeral=True
        )
        await main.log_action(
            f" {interaction.user.mention} set minimum account age to {days} days."
        )

    @nextcord.slash_command(
        name="mute", description="Mute a member", guild_ids=[GUILD_ID]
    )
    async def mute_member(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member,
        minutes: int,
        reason: str = "No reason provided",
    ):
        """Timeout ``member`` for ``minutes`` with an optional ``reason``."""
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        duration = timedelta(minutes=minutes)
        try:
            await member.send(
                f"You have been muted in {interaction.guild.name} by {interaction.user.mention}.\n"
                f"Reason: {reason}\nDuration: {minutes} minutes"
            )
        except Exception:
            pass
        await member.timeout(duration, reason=reason)
        await interaction.response.send_message(
            f" {member} has been muted for {minutes} minutes.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} muted {member.mention} for {minutes}m: {reason}"
        )

    @nextcord.slash_command(
        name="kick", description="Kick a member", guild_ids=[GUILD_ID]
    )
    async def kick_member(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member,
        reason: str = "No reason provided",
    ):
        """Kick ``member`` with an optional ``reason``."""
        if not interaction.user.guild_permissions.kick_members:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        try:
            await member.send(
                f"You have been kicked from {interaction.guild.name} by {interaction.user.mention}.\n"
                f"Reason: {reason}\nDuration: N/A"
            )
        except Exception:
            pass
        await interaction.guild.kick(member, reason=reason)
        await interaction.response.send_message(
            f" {member} has been kicked.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} kicked {member.mention}: {reason}"
        )

    @nextcord.slash_command(
        name="ban", description="Ban a member", guild_ids=[GUILD_ID]
    )
    async def ban_member(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member,
        reason: str = "No reason provided",
        duration: int | None = None,
        unit: str = nextcord.SlashOption(
            name="unit",
            choices={
                "minutes": "minutes",
                "hours": "hours",
                "days": "days",
                "weeks": "weeks",
                "months": "months",
                "years": "years",
            },
            default="minutes",
            description="Duration unit",
        ),
    ):
        """Ban ``member`` with an optional ``reason`` and duration."""
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        duration_text = f"{duration} {unit}" if duration else "Permanent"
        try:
            await member.send(
                f"You have been banned from {interaction.guild.name} by {interaction.user.mention}.\n"
                f"Reason: {reason}\nDuration: {duration_text}"
            )
        except Exception:
            pass
        await interaction.guild.ban(member, reason=reason)
        if duration:
            unit_seconds = {
                "minutes": 60,
                "hours": 60 * 60,
                "days": 24 * 60 * 60,
                "weeks": 7 * 24 * 60 * 60,
                "months": 30 * 24 * 60 * 60,
                "years": 365 * 24 * 60 * 60,
            }
            delay = duration * unit_seconds[unit]
            self.bot.loop.create_task(
                self._schedule_unban(interaction.guild, member.id, delay)
            )
        await interaction.response.send_message(
            f" {member} has been banned.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} banned {member.mention} ({duration_text}): {reason}"
        )

    @nextcord.slash_command(
        name="unban", description="Unban a user", guild_ids=[GUILD_ID]
    )
    async def unban_member(
        self,
        interaction: nextcord.Interaction,
        user_id: int,
        reason: str = "No reason provided",
    ):
        """Unban a previously banned user by ``user_id``."""
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        bans = await interaction.guild.bans()
        entry = next((b for b in bans if b.user.id == user_id), None)
        if entry is None:
            return await interaction.response.send_message(
                " User is not banned.", ephemeral=True
            )
        await interaction.guild.unban(entry.user, reason=reason)
        await interaction.response.send_message(
            f" {entry.user} has been unbanned.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} unbanned {entry.user.mention}: {reason}"
        )

    @nextcord.slash_command(
        name="purge", description="Delete recent messages", guild_ids=[GUILD_ID]
    )
    async def purge_messages(
        self, interaction: nextcord.Interaction, count: int
    ):
        """Delete ``count`` recent messages from the current channel."""
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        deleted = await interaction.channel.purge(limit=count)
        await interaction.response.send_message(
            f" Deleted {len(deleted)} messages.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} purged {len(deleted)} messages in {interaction.channel.mention}"
        )

    # Event listeners ----------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Automatically ban users posting external invite or webhook links."""
        if message.author.bot:
            return
        if contains_discord_invite(message.content):
            try:
                try:
                    await message.author.send(
                        f"You have been banned from {message.guild.name} by AutoMod.\n"
                        "Reason: Posting invite links\nDuration: Permanent"
                    )
                except Exception:
                    pass
                await message.author.ban(reason="Posting invite links")
                await message.delete()
                import main

                await main.log_action(
                    f" {message.author.mention} auto-banned for posting invite link."
                )
            except Exception:
                pass
        elif contains_discord_webhook(message.content):
            try:
                try:
                    await message.author.send(
                        f"You have been banned from {message.guild.name} by AutoMod.\n"
                        "Reason: Posting webhook links\nDuration: Permanent"
                    )
                except Exception:
                    pass
                await message.author.ban(reason="Posting webhook links")
                await message.delete()
                import main

                await main.log_action(
                    f" {message.author.mention} auto-banned for posting webhook link."
                )
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        """Log detailed info and enforce account age limits on join."""
        import main

        age = datetime.now(UTC) - member.created_at
        channel = self.bot.get_channel(main.LOG_CHANNEL_ID)
        about_me = None
        try:
            http = getattr(self.bot, "http", None)
            if http and hasattr(http, "get_user_profile"):
                profile = await http.get_user_profile(member.id)
                about_me = profile.get("bio") or profile.get("about_me")
        except Exception:
            pass

        notes = list_member_notes(member.id)

        embed = nextcord.Embed(
            title="Member joined", timestamp=datetime.now(UTC), colour=0x00AAFF
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=str(member.id), inline=False)
        embed.add_field(name="Avatar", value=member.display_avatar.url, inline=False)
        embed.add_field(
            name="Account created",
            value=f"<t:{int(member.created_at.timestamp())}:F>",
            inline=False,
        )
        embed.add_field(
            name="Account age",
            value=f"{age.days}d {age.seconds // 3600}h",
            inline=False,
        )
        embed.add_field(name="Bot", value=str(member.bot), inline=False)
        if about_me:
            embed.add_field(name="About me", value=about_me[:1024], inline=False)
        if notes:
            embed.add_field(
                name="Previous moderation",
                value="\n".join(notes[-5:])[:1024],
                inline=False,
            )
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        if roles:
            embed.add_field(name="Roles", value=" ".join(roles), inline=False)

        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

        await main.log_action(
            f" {member.mention} joined (account age {age.days}d)."
        )

        # Heuristic alt account detection by matching usernames
        suspects = [
            m for m in member.guild.members if m.id != member.id and m.name == member.name
        ]
        banned_matches = [
            b.user
            for b in await member.guild.bans()
            if b.user.name == member.name
        ]
        if suspects or banned_matches:
            parts = []
            if suspects:
                parts.append("members: " + ", ".join(m.mention for m in suspects))
            if banned_matches:
                parts.append("banned: " + ", ".join(u.name for u in banned_matches))
            msg = "Possible alt detected matching " + "; ".join(parts)
            if channel:
                try:
                    await channel.send(f"⚠️ {msg}")
                except Exception:
                    pass
            await main.log_action(f" {member.mention} flagged as alt account: {msg}")

        min_days = main.MIN_ACCOUNT_AGE_DAYS
        if min_days and age < timedelta(days=min_days):
            until = member.created_at + timedelta(days=min_days)
            delay = (until - datetime.now(UTC)).total_seconds()
            try:
                try:
                    await member.send(
                        f"You have been temporarily banned from {member.guild.name} by AutoMod.\n"
                        f"Reason: Account age below {min_days} day minimum\n"
                        f"Duration: until <t:{int(until.timestamp())}:F>"
                    )
                except Exception:
                    pass
                await member.guild.ban(
                    member,
                    reason=f"Account age below {min_days} day minimum",
                )
                if channel:
                    await channel.send(
                        f" {member.mention} temp banned until <t:{int(until.timestamp())}:F>"
                    )
                await main.log_action(
                    f" {member.mention} temp banned for being {age.days}d old (< {min_days}d)."
                )
                self.bot.loop.create_task(
                    self._schedule_unban(member.guild, member.id, delay)
                )
            except Exception:
                pass

    async def _schedule_unban(
        self, guild: nextcord.Guild, user_id: int, delay: float
    ):
        """Unban ``user_id`` from ``guild`` after ``delay`` seconds."""
        try:
            await asyncio.sleep(max(0, delay))
            user = await self.bot.fetch_user(user_id)
            await guild.unban(user, reason="Account age requirement met")
            import main

            await main.log_action(
                f" {user.mention} automatically unbanned (account age requirement met)."
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: nextcord.Member):
        """Log member departures."""
        import main

        await main.log_action(f" {member.mention} left the server.")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: nextcord.abc.GuildChannel):
        """Nuke prevention – ban users who create channels too quickly."""
        try:
            guild = channel.guild
            async for entry in guild.audit_logs(
                limit=1, action=nextcord.AuditLogAction.channel_create
            ):
                if entry.target.id != channel.id:
                    continue
                user = entry.user
                import main

                await main.log_action(
                    f" Channel {getattr(channel, 'mention', str(channel.id))} created by {user.mention}."
                )
                now = datetime.now(UTC)
                times = self._channel_creations[user.id]
                times[:] = [t for t in times if now - t < timedelta(seconds=10)]
                times.append(now)
                if len(times) >= 3:
                    try:
                        await user.send(
                            f"You have been banned from {guild.name} by AutoMod.\n"
                            "Reason: Nuke prevention: excessive channel creation\nDuration: Permanent"
                        )
                    except Exception:
                        pass
                    await guild.ban(
                        user, reason="Nuke prevention: excessive channel creation"
                    )
                    import main

                    await main.log_action(
                        f" {user.mention} banned for mass channel creation."
                    )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: nextcord.abc.GuildChannel):
        """Log channel deletions."""
        try:
            guild = channel.guild
            async for entry in guild.audit_logs(
                limit=1, action=nextcord.AuditLogAction.channel_delete
            ):
                if entry.target.id != channel.id:
                    continue
                import main

                await main.log_action(
                    f" Channel {getattr(channel, 'name', str(channel.id))} deleted by {entry.user.mention}."
                )
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: nextcord.Message):
        """Log deleted messages."""
        if not getattr(message, "guild", None):
            return
        import main

        content = (message.content or "[no content]")[:100]
        await main.log_action(
            f" Message by {message.author.mention} deleted in {message.channel.mention}: {content}"
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: nextcord.Message, after: nextcord.Message
    ):
        """Log message edits."""
        if not getattr(before, "guild", None):
            return
        if before.content == after.content:
            return
        import main

        before_content = (before.content or "[no content]")[:100]
        after_content = (after.content or "[no content]")[:100]
        await main.log_action(
            f" Message edited by {before.author.mention} in {before.channel.mention}: {before_content} -> {after_content}"
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: nextcord.RawMessageDeleteEvent):
        """Log deletions for uncached messages."""
        if not payload.guild_id:
            return
        import main

        channel = self.bot.get_channel(payload.channel_id)
        channel_mention = getattr(channel, "mention", f"<#{payload.channel_id}>")
        await main.log_action(
            f" Message ID {payload.message_id} deleted in {channel_mention}"
        )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(
        self, payload: nextcord.RawBulkMessageDeleteEvent
    ):
        """Log bulk deletions for uncached messages."""
        if not payload.guild_id:
            return
        import main

        channel = self.bot.get_channel(payload.channel_id)
        channel_mention = getattr(channel, "mention", f"<#{payload.channel_id}>")
        await main.log_action(
            f" {len(payload.message_ids)} messages bulk deleted in {channel_mention}"
        )

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: nextcord.RawMessageUpdateEvent):
        """Log edits for uncached messages."""
        if not payload.guild_id:
            return
        import main

        channel = self.bot.get_channel(payload.channel_id)
        channel_mention = getattr(channel, "mention", f"<#{payload.channel_id}>")
        author = None
        content = None
        if channel:
            try:
                message = await channel.fetch_message(payload.message_id)
                author = getattr(message.author, "mention", None)
                content = (message.content or "[no content]")[:100]
            except Exception:
                pass
        parts = [" Message edited"]
        if author:
            parts.append(f" by {author}")
        parts.append(f" in {channel_mention}")
        if content:
            parts.append(f": {content}")
        else:
            parts.append(f" (ID {payload.message_id})")
        await main.log_action("".join(parts))

    @commands.Cog.listener()
    async def on_member_update(
        self, before: nextcord.Member, after: nextcord.Member
    ):
        """Log profile picture changes."""
        if before.display_avatar.url == after.display_avatar.url:
            return
        import main

        await main.log_action(f" {after.mention} changed profile picture.")

    @commands.Cog.listener()
    async def on_invite_create(self, invite: nextcord.Invite):
        """Log invite link creation."""
        import main

        creator = invite.inviter.mention if invite.inviter else "Unknown"
        channel = invite.channel.mention if invite.channel else "Unknown"
        await main.log_action(
            f" Invite {invite.code} created by {creator} for {channel}."
        )

    @commands.Cog.listener()
    async def on_guild_update(
        self, before: nextcord.Guild, after: nextcord.Guild
    ):
        """Log server setting changes."""
        changes = []
        if before.name != after.name:
            changes.append(f"name changed to '{after.name}'")
        if before.icon != after.icon:
            changes.append("icon updated")
        if not changes:
            return
        import main

        await main.log_action(f" Guild updated: {', '.join(changes)}")
