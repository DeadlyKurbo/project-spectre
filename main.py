#!/usr/bin/env python3
import os
import json
import uuid
from dotenv import load_dotenv

import nextcord
from nextcord import (
    Interaction,
    SlashOption,
    Attachment,
    Embed,
    SelectOption,
    ButtonStyle,
)
from nextcord.ext import commands
from nextcord.ui import View, Select, Button
from github import Github

# —— Load ENV ——
load_dotenv()
DISCORD_TOKEN    = os.getenv("DISCORD_TOKEN")
GUILD_ID         = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID  = int(os.getenv("MENU_CHANNEL_ID"))
GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN")
GITHUB_REPO      = os.getenv("GITHUB_REPO")  # e.g. "DeadlyKurbo/project-spectre"

# —— Paths ——
BASE_DIR        = os.path.dirname(__file__)
DOSSIERS_DIR    = os.path.join(BASE_DIR, "dossiers")
MISSIONS_DIR    = os.path.join(DOSSIERS_DIR, "missions")
CLEARANCE_FILE  = os.path.join(BASE_DIR, "clearance.json")

# —— Clearance helpers ——
def load_clearance():
    with open(CLEARANCE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_clearance(data):
    with open(CLEARANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# —— File listing helpers ——
def list_categories():
    return [
        d for d in os.listdir(DOSSIERS_DIR)
        if os.path.isdir(os.path.join(DOSSIERS_DIR, d))
    ]

def list_items(category: str):
    folder = os.path.join(DOSSIERS_DIR, category)
    return [
        fn[:-5]
        for fn in os.listdir(folder)
        if fn.lower().endswith(".json")
    ]

def load_missions():
    os.makedirs(MISSIONS_DIR, exist_ok=True)
    missions = {}
    for fn in os.listdir(MISSIONS_DIR):
        if not fn.endswith(".json"):
            continue
        mid = fn[:-5]
        with open(os.path.join(MISSIONS_DIR, fn), "r", encoding="utf-8") as f:
            data = json.load(f)
        data["title"] = data.get("title", mid)
        missions[mid] = data
    return missions

# —— GitHub commit helper ——
def commit_file(path_in_repo: str, content: bytes, message: str):
    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPO)
    repo.create_file(path_in_repo, message, content)

# —— UI Components ——
class CategorySelect(Select):
    def __init__(self):
        super().__init__(
            placeholder="Selecteer categorie…",
            options=[
                SelectOption(label=c.replace("_", " ").title(), value=c)
                for c in list_categories()
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: Interaction):
        category = self.values[0]
        items = list_items(category)
        embed = Embed(
            title=category.replace("_", " ").title(),
            description="Selecteer dossier…",
            color=0x3498DB
        )
        view = View(timeout=None)
        select_item = Select(
            placeholder="Selecteer item…",
            options=[
                SelectOption(label=i.replace("_", " ").title(), value=i)
                for i in items
            ],
            min_values=1,
            max_values=1
        )
        select_item.callback = lambda inter: self.on_item(inter, category)
        view.add_item(select_item)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_item(self, interaction: Interaction, category: str):
        try:
            item = interaction.data["values"][0]
            path = os.path.join(DOSSIERS_DIR, category, f"{item}.json")
            if not os.path.isfile(path):
                return await interaction.response.send_message(
                    "❌ File not found.", ephemeral=True
                )

            data = json.load(open(path, "r", encoding="utf-8"))
            embed = Embed(
                title=data.get("title", item.replace("_", " ").title()),
                color=0x3498DB
            )
            for k, v in data.items():
                if k in ("pdf_path", "pdf_link"):
                    continue
                embed.add_field(name=k.replace("_", " ").title(), value=str(v), inline=False)

            pdf_ref = data.get("pdf_path") or data.get("pdf_link")
            if pdf_ref:
                raw_url = (
                    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/"
                    f"dossiers/missions/{pdf_ref}"
                )
                embed.add_field(name="AAR", value=f"[Download PDF]({raw_url})", inline=False)

            view = View(timeout=None)
            back = Button(label="← Back to list", style=ButtonStyle.secondary)
            async def go_back(btn, inter2):
                await CategorySelect().callback(inter2)
            back.callback = go_back
            view.add_item(back)

            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Error reading file: {e}", ephemeral=True
            )

class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary)
        async def do_refresh(btn, inter):
            await inter.response.edit_message(
                embed=Embed(
                    title="Missions Archive",
                    description="Browse de dossiers…",
                    color=0x00FFCC
                ),
                view=RootView()
            )
        refresh.callback = do_refresh
        self.add_item(refresh)

# —— Bot setup ——
bot = commands.Bot(intents=nextcord.Intents.default())

_first_ready = True

@bot.event
async def on_ready():
    global _first_ready
    if not _first_ready:
        return
    _first_ready = False

    channel = bot.get_channel(MENU_CHANNEL_ID)
    if not channel:
        print("⚠️ Menu channel not found.")
        return

    # update existing embed if present
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            if msg.embeds[0].title == "Missions Archive":
                await msg.edit(
                    embed=Embed(
                        title="Missions Archive",
                        description="Browse de dossiers…",
                        color=0x00FFCC
                    ),
                    view=RootView()
                )
                print("♻️ Updated existing archive embed")
                break
    else:
        await channel.send(
            embed=Embed(
                title="Missions Archive",
                description="Browse de dossiers…",
                color=0x00FFCC
            ),
            view=RootView()
        )
        print("✅ Posted new archive embed")

# —— Clearance slash-commands ——
@bot.slash_command(name="grantfileclearance", guild_ids=[GUILD_ID])
async def grantfileclearance(
    interaction: Interaction,
    member: nextcord.Member,
    level: int = SlashOption(description="Clearance level (int)")
):
    data = load_clearance()
    data[str(member.id)] = level
    save_clearance(data)
    await interaction.response.send_message(
        f"Granted clearance level {level} to {member.mention}.", ephemeral=True
    )

@bot.slash_command(name="revokefileclearance", guild_ids=[GUILD_ID])
async def revokefileclearance(
    interaction: Interaction,
    member: nextcord.Member
):
    data = load_clearance()
    if str(member.id) in data:
        data.pop(str(member.id))
        save_clearance(data)
        await interaction.response.send_message(
            f"Revoked clearance for {member.mention}.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"{member.mention} heeft geen clearance.", ephemeral=True
        )

# —— Pre-build category choices for /addmission ——
_category_choices = [
    nextcord.SlashOptionChoice(name=c.replace("_", " ").title(), value=c)
    for c in list_categories()
]

# —— /addmission Slash-Command ——
@bot.slash_command(name="addmission", guild_ids=[GUILD_ID])
async def addmission(
    interaction: Interaction,
    category: str = SlashOption(
        description="Selecteer categorie",
        choices=_category_choices
    ),
    title: str = SlashOption(description="Titel van de operatie"),
    filed_by: str = SlashOption(description="Filed by"),
    date: str = SlashOption(description="Datum (YYYY-MM-DD)"),
    status: str = SlashOption(description="Status"),
    operation_type: str = SlashOption(description="Operation type"),
    end: str = SlashOption(description="Einddatum (YYYY-MM-DD)"),
    honourable_mentions: str = SlashOption(
        description="Eervolle vermeldingen (komma-gescheiden)",
        required=False,
        default=""
    ),
    pdf: Attachment = SlashOption(description="PDF bijlage")
):
    await interaction.response.defer(ephemeral=True)

    # 1) Save PDF
    os.makedirs(MISSIONS_DIR, exist_ok=True)
    mid = uuid.uuid4().hex[:8]
    pdf_fn = f"mission-{mid}.pdf"
    pdf_path = os.path.join(MISSIONS_DIR, pdf_fn)
    await pdf.save(pdf_path)

    # 2) Build JSON
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
    json_fn = f"mission-{mid}.json"
    json_path = os.path.join(MISSIONS_DIR, json_fn)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # 3) Commit to GitHub
    with open(json_path, "rb") as f:
        commit_file(f"dossiers/missions/{json_fn}", f.read(), f"Add mission {title}")
    with open(pdf_path, "rb") as f:
        commit_file(f"dossiers/missions/{pdf_fn}", f.read(), f"Add PDF for {title}")

    await interaction.followup.send(
        f"✅ Mission **{title}** toegevoegd onder **{category}** en gepusht!", ephemeral=True
    )

# —— Run Bot ——
bot.run(DISCORD_TOKEN)