import nextcord
from nextcord import Embed
from config import GUILD_ID, INTRO_TITLE, INTRO_DESC, MENU_CHANNEL_ID
from config import set_log_channel
from views.explorer_views import RootView

def register(bot: nextcord.Client):
    @bot.slash_command(name="summonmenu", description="Resend the explorer menu", guild_ids=[GUILD_ID])
    async def summonmenu_cmd(interaction: nextcord.Interaction):
        if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView(bot, INTRO_TITLE, INTRO_DESC),
        )

    @bot.slash_command(name="setlogchannel", description="Set the logging channel", guild_ids=[GUILD_ID])
    async def setlogchannel_cmd(interaction: nextcord.Interaction, channel: nextcord.TextChannel):
        if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
        set_log_channel(channel.id)
        await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)
