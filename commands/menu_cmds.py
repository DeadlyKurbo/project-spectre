import nextcord
from nextcord import Embed
from config import GUILD_ID, INTRO_TITLE, INTRO_DESC
from explorer_views import RootView

def register(bot: nextcord.Client):
    @bot.slash_command(name="summonmenu", description="Post the Archive menu in this channel.", guild_ids=[GUILD_ID] if GUILD_ID else None)
    async def summonmenu(inter: nextcord.Interaction):
        await inter.response.send_message("📡 Posting menu…", ephemeral=True)
        await inter.channel.send(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView(bot, INTRO_TITLE, INTRO_DESC)
        )
