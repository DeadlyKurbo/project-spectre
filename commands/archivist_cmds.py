import nextcord
from nextcord import Embed
from views.archivist_views import ArchivistConsoleView
from config import GUILD_ID

def register(bot: nextcord.Client):
    @bot.slash_command(name="archivist", description="Open the Archivist Console", guild_ids=[GUILD_ID])
    async def archivist_cmd(interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(title="Archivist Console", description="Select an action below.", color=0x00FFCC),
            view=ArchivistConsoleView(bot, interaction.user), ephemeral=True
        )
