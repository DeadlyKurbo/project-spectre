import re
from collections import defaultdict
from datetime import datetime, UTC, timedelta

import nextcord
from nextcord.ext import commands

from config import set_log_channel
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
        """Ban newly created bot accounts on join."""
        if not member.bot:
            return
        age = datetime.now(UTC) - member.created_at
        if age < timedelta(days=7):
            try:
                await member.ban(reason="Suspicious bot account")
                import main

                await main.log_action(
                    f" {member.mention} banned as suspicious bot (account age {age.days}d)."
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
