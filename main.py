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
GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN")      # nieuw
GITHUB_REPO      = os.getenv("GITHUB_REPO")       # bv. "DeadlyKurbo/project-spectre"

# --- Bot initialiseren ---
intents = nextcord.Intents.default()
bot = commands.Bot(intents=intents)

# --- Helpers voor clearance.json ---
def load_clearance():
    with open("clearance.json", "r") as f:
        return json.load(f)

def save_clearance(data):
    with open("clearance.json", "w") as f:
        json.dump(data, f, indent=2)

# --- Slash-commands voor clearancebeheer ---
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
    path = "dossiers/missions"
    missions = {}
    for fn in os.listdir(path):
        if fn.endswith(".json"):
            mid = fn[:-5]  # zonder .json
            with open(os.path.join(path, fn), "r", encoding="utf-8") as f:
                missions[mid] = json.load(f)
    return missions

# --- UI voor lijst en detail ---
class CategorySelect(nextcord.ui.Select):
    def __init__(self, missions):
        options = [
            nextcord.SelectOption(label=m["title"], value=mid)
            for mid, m in missions.items()
        ]
        super().__init__(placeholder="Selecteer missie…",
                         min_values=1, max_values=1,
                         options=options)
        self.missions = missions

    async def callback(self, interaction: Interaction):
        mid  = self.values[0]
        data = self.missions[mid]
        embed = nextcord.Embed(title=f"Operation {data['title']}")
        embed.add_field("Filed By", data["filed_by"], inline=False)
        embed.add_field("Date", data["date"], inline=False)
        embed.add_field("Status", data["status"], inline=False)
        embed.add_field("Operation Type", data["operation_type"], inline=False)
        embed.add_field("Honourable Mentions",
                        ", ".join(data.get("honourable_mentions", [])) or "None",
                        inline=False)
        embed.add_field("End", data["end"], inline=False)
        if data.get("pdf_path"):
            url = data["pdf_path"]
            embed.add_field("AAR", f"[Download PDF]({url})", inline=False)

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
        select = CategorySelect(missions)
        view = RootView()
        view.clear_items()
        view.add_item(select)
        await interaction.response.edit_message(embed=embed, view=view)

# --- Bot startup: publiceer de embed + menu éénmalig ---
@bot.event
async def on_ready():
    channel = bot.get_channel(MENU_CHANNEL_ID)
    missions = load_missions()
    embed = nextcord.Embed(
        title="Missions Archive",
        description="Kies een missie uit het dropdown-menu"
    )
    view = RootView()
    select = CategorySelect(missions)
    view.add_item(select)
    await channel.send(embed=embed, view=view)
    print(f"✅ {bot.user} is online!")

# --- NIEUW: /addmission slash-command ---
@bot.slash_command(name="addmission", guild_ids=[GUILD_ID])
async def addmission(
    interaction: Interaction,
    title: str = SlashOption(description="Titel van de operatie"),
    filed_by: str = SlashOption(description="Filed by"),
    date: str = SlashOption(description="Datum (YYYY-MM-DD)"),
    status: str = SlashOption(description="Status"),
    operation_type: str = SlashOption(description="Operation type"),
    honourable_mentions: str = SlashOption(
        description="Eervolle vermeldingen, komma-gescheiden", 
        required=False, default=""
    ),
    end: str = SlashOption(description="Einddatum (YYYY-MM-DD)"),
    pdf: Attachment = SlashOption(description="PDF bijlage", required=True)
):
    await interaction.response.defer(ephemeral=True)

    # 1) Sla PDF op lokaal
    missions_dir = "dossiers/missions"
    os.makedirs(missions_dir, exist_ok=True)
    mid = uuid.uuid4().hex[:8]
    pdf_fn  = f"mission-{mid}.pdf"
    pdf_path = os.path.join(missions_dir, pdf_fn)
    await pdf.save(pdf_path)

    # 2) Maak JSON
    data = {
        "title": title,
        "filed_by": filed_by,
        "date": date,
        "status": status,
        "operation_type": operation_type,
        "honourable_mentions": [
            m.strip() for m in honourable_mentions.split(",") if m.strip()
        ],
        "end": end,
        "pdf_path": pdf_fn
    }
    json_fn   = f"mission-{mid}.json"
    json_path = os.path.join(missions_dir, json_fn)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # 3) Commit naar GitHub
    gh   = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPO)
    # JSON
    with open(json_path, "rb") as f:
        repo.create_file(f"dossiers/missions/{json_fn}",
                         f"Add mission {title}",
                         f.read())
    # PDF
    with open(pdf_path, "rb") as f:
        repo.create_file(f"dossiers/missions/{pdf_fn}",
                         f"Add PDF for {title}",
                         f.read())

    await interaction.followup.send(
        f"✅ Mission **{title}** toegevoegd à dossier en gepusht naar GitHub!",
        ephemeral=True
    )

# --- Run de bot ---
bot.run(DISCORD_TOKEN)