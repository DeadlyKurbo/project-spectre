import re
from collections import defaultdict
from datetime import datetime, UTC, timedelta
import asyncio

import nextcord
from nextcord.ext import commands

from config import set_log_channel, set_join_log_channel, set_min_account_age_days
from constants import GUILD_ID

INVITE_PATTERN = re.compile(
    r"(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9]+",
    re.IGNORECASE,
)


def contains_discord_invite(text: str) -> bool:
    """Return ``True`` if ``text`` contains a Discord invite link."""
    return bool(INVITE_PATTERN.search(text or ""))


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
        name="setjoinlog", description="Set the join log channel", guild_ids=[GUILD_ID]
    )
    async def set_join_log_channel_cmd(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        """Persist ``channel`` as the destination for join logs."""
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        set_join_log_channel(channel.id)
        import main

        main.JOIN_LOG_CHANNEL_ID = channel.id
        await interaction.response.send_message(
            f" Join log channel set to {channel.mention}", ephemeral=True
        )
        await main.log_action(
            f" {interaction.user.mention} set join log channel to {channel.mention}."
        )

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
    ):
        """Ban ``member`` with an optional ``reason``."""
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(
                " Insufficient permissions.", ephemeral=True
            )
        await interaction.guild.ban(member, reason=reason)
        await interaction.response.send_message(
            f" {member} has been banned.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} banned {member.mention}: {reason}"
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
        user = await self.bot.fetch_user(user_id)
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(
            f" {user} has been unbanned.", ephemeral=True
        )
        import main

        await main.log_action(
            f" {interaction.user.mention} unbanned {user.mention}: {reason}"
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
        """Automatically ban users posting external Discord invite links."""
        if message.author.bot:
            return
        if contains_discord_invite(message.content):
            try:
                await message.author.ban(reason="Posting invite links")
                await message.delete()
                import main

                await main.log_action(
                    f" {message.author.mention} auto-banned for posting invite link."
                )
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: nextcord.Member):
        """Log detailed info and enforce account age limits on join."""
        import main

        age = datetime.now(UTC) - member.created_at
        channel = self.bot.get_channel(main.JOIN_LOG_CHANNEL_ID) or self.bot.get_channel(
            main.LOG_CHANNEL_ID
        )

        embed = nextcord.Embed(
            title="Member joined", timestamp=datetime.now(UTC), colour=0x00AAFF
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="User ID", value=str(member.id), inline=False)
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
                now = datetime.now(UTC)
                times = self._channel_creations[user.id]
                times[:] = [t for t in times if now - t < timedelta(seconds=10)]
                times.append(now)
                if len(times) >= 3:
                    await guild.ban(
                        user, reason="Nuke prevention: excessive channel creation"
                    )
                    import main

                    await main.log_action(
                        f" {user.mention} banned for mass channel creation."
                    )
        except Exception:
            pass
