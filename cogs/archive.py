import json
from pathlib import Path
import nextcord
from nextcord.ext import commands
from nextcord import Interaction, SlashOption

from utils.interaction_safety import auto_ack, safe_followup, AlreadyResponded

DATA_DIR = Path("data")
ARCHIVE_STORE = DATA_DIR / "archive_menu.json"
ARCHIVE_STORE.parent.mkdir(exist_ok=True)

PERSISTENT_CUSTOM_IDS = {
    "open_personnel": "spectre:archive:open_personnel",
    "open_mission":   "spectre:archive:open_mission",
    "open_intel":     "spectre:archive:open_intel",
    "refresh":        "spectre:archive:refresh",
}

# ---------- Embed + View ----------
def archive_embed() -> nextcord.Embed:
    e = nextcord.Embed(
        title="📁 Project SPECTRE — Archive",
        description="Kies een sectie hieronder om te openen.\n"
                    "Gebruik **Refresh** als de inhoud is geüpdatet.",
        color=0x2F3136
    )
    e.set_footer(text="Glacier Unit • Digital Archive")
    return e

class ArchiveView(nextcord.ui.View):
    def __init__(self):
        # Persistent view: timeout=None
        super().__init__(timeout=None)
        # Buttons met stabiele custom_ids (vereist voor persistent views)
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.primary,
            label="Personnel Files",
            custom_id=PERSISTENT_CUSTOM_IDS["open_personnel"]
        ))
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.secondary,
            label="Mission Logs",
            custom_id=PERSISTENT_CUSTOM_IDS["open_mission"]
        ))
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.success,
            label="Intelligence",
            custom_id=PERSISTENT_CUSTOM_IDS["open_intel"]
        ))
        self.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.gray,
            label="Refresh",
            custom_id=PERSISTENT_CUSTOM_IDS["refresh"]
        ))

class ArchiveCog(commands.Cog, name="ArchiveCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Maak één instance van de view die we persistent registreren
        self._persistent_view = ArchiveView()

    # ---------- Persistent View registreren bij startup ----------
    def register_persistent_view(self):
        # Belangrijk: NIET opnieuw message sturen — alleen view registreren
        try:
            self.bot.add_view(self._persistent_view)
        except Exception as e:
            print(f"[WARN] Could not re-register ArchiveView: {e}")

    # ---------- Helper: opslag voor message/channel ----------
    @staticmethod
    def save_anchor(channel_id: int, message_id: int):
        ARCHIVE_STORE.write_text(json.dumps({
            "channel_id": channel_id,
            "message_id": message_id
        }, indent=2))

    @staticmethod
    def load_anchor():
        if not ARCHIVE_STORE.exists():
            return None
        try:
            data = json.loads(ARCHIVE_STORE.read_text())
            return int(data["channel_id"]), int(data["message_id"])
        except Exception:
            return None

    # ---------- Slash: /archive-deploy (eenmalig) ----------
    @nextcord.slash_command(description="Plaats of vervang het permanente Archive-menu in een kanaal.")
    async def archive_deploy(
        self,
        interaction: Interaction,
        channel: nextcord.abc.GuildChannel = SlashOption(
            name="channel",
            description="Kanaal waar het Archive-menu moet komen te staan",
            required=True
        )
    ):
        await interaction.response.defer(ephemeral=True, with_message=True)

        # Check kanaal type (TextChannel verwacht)
        if not isinstance(channel, nextcord.TextChannel):
            await safe_followup(interaction, "❌ Kies een tekstkanaal.", ephemeral=True)
            return

        # Stuur/Update message
        embed = archive_embed()
        view = self._persistent_view

        # Als er al een anchor is, probeer die te editen i.p.v. nieuwe spam
        anchor = self.load_anchor()
        posted = None
        if anchor:
            channel_id, message_id = anchor
            if channel_id == channel.id:
                try:
                    old_msg = await channel.fetch_message(message_id)
                    await old_msg.edit(embed=embed, view=view)
                    posted = old_msg
                except Exception:
                    posted = None

        if posted is None:
            # Post nieuwe message en opslaan
            posted = await channel.send(embed=embed, view=view)
            self.save_anchor(channel.id, posted.id)

        await safe_followup(
            interaction,
            f"✅ Archive menu staat nu in {channel.mention} (message id `{posted.id}`).",
            ephemeral=True
        )

    # ---------- Component handlers (buttons) ----------
    @commands.Cog.listener("on_interaction")
    async def archive_button_router(self, interaction: Interaction):
        # Hook alleen op onze custom_ids
        if not interaction.type == nextcord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id")
        if cid not in PERSISTENT_CUSTOM_IDS.values():
            return

        # Altijd snel ack'en
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
        except AlreadyResponded:
            # is al deferred; ga door
            pass
        except Exception:
            # fall-through
            pass

        # Route
        try:
            if cid == PERSISTENT_CUSTOM_IDS["open_personnel"]:
                await self.handle_open_personnel(interaction)
            elif cid == PERSISTENT_CUSTOM_IDS["open_mission"]:
                await self.handle_open_mission(interaction)
            elif cid == PERSISTENT_CUSTOM_IDS["open_intel"]:
                await self.handle_open_intel(interaction)
            elif cid == PERSISTENT_CUSTOM_IDS["refresh"]:
                await self.handle_refresh(interaction)
        except Exception as e:
            await safe_followup(interaction, f"❌ Error: {e}", ephemeral=True)

    # ----- Concrete handlers (hier kun je je eigen logic inpluggen) -----
    @auto_ack
    async def handle_open_personnel(self, interaction: Interaction):
        # TODO: vervang door echte content loader
        await safe_followup(interaction, "👤 Opening **Personnel Files**… (demo)", ephemeral=True)

    @auto_ack
    async def handle_open_mission(self, interaction: Interaction):
        await safe_followup(interaction, "📝 Opening **Mission Logs**… (demo)", ephemeral=True)

    @auto_ack
    async def handle_open_intel(self, interaction: Interaction):
        await safe_followup(interaction, "🛰️ Opening **Intelligence**… (demo)", ephemeral=True)

    @auto_ack
    async def handle_refresh(self, interaction: Interaction):
        # Rebuild embed/view of update caches etc.
        anchor = self.load_anchor()
        if not anchor:
            await safe_followup(interaction, "⚠️ Geen anchor gevonden. Run `/archive-deploy` eerst.", ephemeral=True)
            return
        channel_id, message_id = anchor
        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, nextcord.TextChannel):
            await safe_followup(interaction, "⚠️ Kanaal niet gevonden. Deploy opnieuw.", ephemeral=True)
            return
        try:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=archive_embed(), view=self._persistent_view)
            await safe_followup(interaction, "🔄 Archive menu refreshed.", ephemeral=True)
        except Exception:
            await safe_followup(interaction, "⚠️ Kon de message niet verversen. Deploy opnieuw.", ephemeral=True)

def setup(bot: commands.Bot):
    bot.add_cog(ArchiveCog(bot))
