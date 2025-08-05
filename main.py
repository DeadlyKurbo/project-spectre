#!/usr/bin/env python3
import os
import json
import uuid
from dotenv import load_dotenv

import nextcord
from nextcord import Interaction, SlashOption, Attachment
from nextcord.ext import commands
from github import Github

# --- ENV-vars laden ---
load_dotenv()
DISCORD_TOKEN    = os.getenv("DISCORD_TOKEN")
GUILD_ID         = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID  = int(os.getenv("MENU_CHANNEL_ID"))
GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN")
GITHUB_REPO      = os.getenv("GITHUB_REPO")

# --- Bot initialiseren ---
intents = nextcord.Intents.default()
bot = commands.Bot(intents=intents)

# --- Clearance helpers ---
def load_clearance():
    with open("clearance.json", "r") as f:
        return json.load(f)

def save_clearance(data):
    with open("clearance.json", "w") as f:
        json.dump(data, f, indent=2)

# --- Slash-commands voor clearance ---
@bot.slash_command(name="grantfileclearance", guild_ids=[GUILD_ID])
async def grantfileclearance(
    interaction: Interaction,
    member: nextcord.Member,
    level: int = SlashOption(description="Clearance level (int)")
):
    data = load_clearance()
    data[str(member.id)] = level
    save_clearance(data)
    await interaction.response.send_message(f"Granted clearance level {level} to {member.mention}.", ephemeral=True)

@bot.slash_command(name="revokefileclearance", guild_ids=[GUILD_ID])
async def revokefileclearance(
    interaction: Interaction,
    member: nextcord.Member
):
    data = load_clearance()
    if str(member.id) in data:
        data.pop(str(member.id))
        save_clearance(data)
        await interaction.response.send_message(f"Revoked clearance for {member.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"{member.mention} heeft geen clearance.", ephemeral=True)

# --- Missions loader ---
def load_missions():
    missions = {}
    path = "dossiers/missions"
    for fn in os.listdir(path):
        if not fn.endswith(".json"):
            continue
        mid = fn[:-5]
        with open(os.path.join(path, fn), "r", encoding="utf-8") as f:
            data = json.load(f)
        # fallback title
        data["title"] = data.get("title", mid)
        missions[mid] = data
    return missions

# --- UI: dropdown + navigation ---
class CategorySelect(nextcord.ui.Select):
    def __init__(self, missions):
        options = [
            nextcord.SelectOption(label=m["title"], value=mid)
            for mid, m in missions.items()
        ]
        super().__init__(
            placeholder="Selecteer missie…",
            min_values=1,
            max_values=1,
            options=options
        )
        self.missions = missions

    async def callback(self, interaction: Interaction):
        mid  = self.values[0]
        data = self.missions[mid]
        title = data.get("title", mid)
        embed = nextcord.Embed(title=f"Operation {title}")
        embed.add_field("Filed By", data["filed_by"], inline=False)
        embed.add_field("Date", data["date"], inline=False)
        embed.add_field("Status", data["status"], inline=False)
        embed.add_field("Operation Type", data["operation_type"], inline=False)
        embed.add_field(
            "Honourable Mentions",
            ", ".join(data.get("honourable_mentions", [])) or "None",
            inline=False
        )
        embed.add_field("End", data["end"], inline=False)

        # PDF-link: support both old (pdf_link) and new (pdf_path)
        pdf_ref = data.get("pdf_path") or data.get("pdf_link")
        if pdf_ref:
            # raw GitHub URL (pas 'main' aan als je andere branch gebruikt)
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/dossiers/missions/{pdf_ref}"
            embed.add_field("AAR", f"[Download PDF]({raw_url})", inline=False)

        view = RootView()
        view.current_mid = mid
        await interaction.response.edit_message(embed=embed, view=view)

class RootView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.current_mid = None

    @nextcord.ui.button(label="Back to list", style=nextcord.ButtonStyle.secondary, custom_id="back")
    async def back(self, button, interaction: Interaction):
        await self.show_list(interaction)

    @nextcord.ui.button(label="Refresh", style=nextcord.ButtonStyle.primary, custom_id="refresh")
    async def refresh(self, button, interaction: Interaction):
        await self.show_list(interaction)

    async def show_list(self, interaction: Interaction):
        missions = load_missions()
        embed = nextcord.Embed(
            title="Missions Archive",
            description="Kies een missie uit het dropdown-menu"
        )
        view = RootView()
        view.clear_items()
        view.add_item(CategorySelect(missions))
        await interaction.response.edit_message(embed=embed, view=view)

# --- Bot startup: post embed + menu éénmalig ---
@bot.event
async def on_ready():
    channel = bot.get_channel(MENU_CHANNEL_ID)
    missions = load_missions()
    embed = nextcord.Embed(
        title="Missions Archive",
        description="Kies een missie uit het dropdown-menu"
    )
    view = RootView()
    view.add_item(CategorySelect(missions))
    await channel.send(embed=embed, view=view)
    print(f"✅ {bot.user} is online!")

# --- /addmission: vul vanaf Discord en push naar GitHub ---
@bot.slash_command(name="addmission", guild_ids=[GUILD_ID])
async def addmission(
    interaction: Interaction,
    title: str = SlashOption(description="Titel van de operatie"),
    filed_by: str = SlashOption(description="Filed by"),
    date: str = SlashOption(description="Datum (YYYY-MM-DD)"),
    status: str = SlashOption(description="Status"),
    operation_type: str = SlashOption(description="Operation type"),
    end: str = SlashOption(description="Einddatum (YYYY-MM-DD)"),
    pdf: Attachment = SlashOption(description="PDF bijlage"),
    honourable_mentions: str = SlashOption(
        description="Eervolle vermeldingen, komma-gescheiden",
        required=False, default=""
    )
):
    await interaction.response.defer(ephemeral=True)

    # 1) PDF opslaan
    missions_dir = "dossiers/missions"
    os.makedirs(missions_dir, exist_ok=True)
    mid = uuid.uuid4().hex[:8]
    pdf_fn = f"mission-{mid}.pdf"
    await pdf.save(os.path.join(missions_dir, pdf_fn))

    # 2) JSON aanmaken
    data = {
        "title": title,
        "filed_by": filed_by,
        "date": date,
        "status": status,
        "operation_type": operation_type,
        "honourable_mentions": [m.strip() for m in honourable_mentions.split(",") if m.strip()],
        "end": end,
        "pdf_path": pdf_fn
    }
    json_fn = f"mission-{mid}.json"
    json_path = os.path.join(missions_dir, json_fn)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # 3) Commit + push naar GitHub
    gh_repo = Github(GITHUB_TOKEN).get_repo(GITHUB_REPO)
    with open(json_path, "rb") as f:
        gh_repo.create_file(f"dossiers/missions/{json_fn}",
                            f"Add mission {title}",
                            f.read())
    with open(os.path.join(missions_dir, pdf_fn), "rb") as f:
        gh_repo.create_file(f"dossiers/missions/{pdf_fn}",
                            f"Add PDF for mission {title}",
                            f.read())

    await interaction.followup.send(
        f"✅ Mission **{title}** toegevoegd en gepusht naar GitHub!",
        ephemeral=True
    )

# --- Bot runnen ---
bot.run(DISCORD_TOKEN)