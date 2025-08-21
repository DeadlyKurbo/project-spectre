import nextcord
from nextcord import Embed
from config import GUILD_ID

# Hardcoded Archivist rollen + monitor-kanaal
LEAD_ARCHIVIST_ROLE_ID = 1405932476089765949
ARCHIVIST_ROLE_ID      = 1405757611919544360
ARCHIVIST_MONITOR_CHANNEL_ID = 1402306158492123318  # “beter monitored” kanaal

def _roles(member: nextcord.Member) -> set[int]:
    return {r.id for r in member.roles}

def _is_owner_admin(member: nextcord.Member) -> bool:
    return member.id == member.guild.owner_id or member.guild_permissions.administrator

def _is_lead(member: nextcord.Member) -> bool:
    rs = _roles(member)
    return _is_owner_admin(member) or (LEAD_ARCHIVIST_ROLE_ID in rs)

def _is_archivist(member: nextcord.Member) -> bool:
    rs = _roles(member)
    return _is_lead(member) or (ARCHIVIST_ROLE_ID in rs)

def register(bot: nextcord.Client):
    # local import om circulars te voorkomen
    from views.archivist_views import ArchivistConsoleView

    @bot.slash_command(name="archivist", description="Open the Archivist Console", guild_ids=[GUILD_ID])
    async def archivist_cmd(interaction: nextcord.Interaction):
        user = interaction.user
        if not _is_archivist(user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)

        # Archivist (geen lead) moet het in het monitor-kanaal doen
        if not _is_lead(user) and interaction.channel.id != ARCHIVIST_MONITOR_CHANNEL_ID:
            ch = bot.get_channel(ARCHIVIST_MONITOR_CHANNEL_ID) or await bot.fetch_channel(ARCHIVIST_MONITOR_CHANNEL_ID)
            if ch:
                return await interaction.response.send_message(
                    f"⚠️ Gebruik dit in {ch.mention} voor logging & toezicht.", ephemeral=True
                )

        await interaction.response.send_message(
            embed=Embed(title="Archivist Console", description="Select an action below.", color=0x00FFCC),
            view=ArchivistConsoleView(bot, user), ephemeral=True
        )
