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
    Choice
)
from nextcord.ext import commands
from nextcord.ui import View, Select, Button
from github import Github

# —— Load ENV ——
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID"))
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN")
GITHUB_REPO     = os.getenv("GITHUB_REPO")  # e.g. "DeadlyKurbo/project-spectre"

# —— Clearance description ——
DESCRIPTION = (
    "Use `/grantfileclearance` or `/revokefileclearance` to manage file access.\n\n"
    "**Clearance Levels:**\n"
    "• **Level 1 – Recruit**: Can view heavily redacted files only.\n"
    "• **Level 2 – Operator**: Can view low-sensitivity dossiers.\n"
    "• **Level 3 – Officer**: Can view standard dossiers.\n"
    "• **Level 4 – Commander**: Can view high-sensitivity dossiers.\n"
    "• **Level 5 – Director**: Can view all dossiers.\n"
    "• **Classified – Top Secret**: Owner only.\n\n"
    "Click below to browse files."
)

# —— Role-ID Constants ——
LEVEL1_ROLE_ID     = 1365094153901441075
LEVEL2_ROLE_ID     = 1365094153901441075
LEVEL3_ROLE_ID     = 1365096533069926460
LEVEL4_ROLE_ID     = 1365094103578181765
LEVEL5_ROLE_ID     = 1365093753035161712
CLASSIFIED_ROLE_ID = 1365093656859512863

ALLOWED_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID
}

# —— Paths ——
BASE_DIR        = os.path.dirname(__file__)
DOSSIERS_DIR    = os.path.join(BASE_DIR, "dossiers")
CLEARANCE_FILE  = os.path.join(BASE_DIR, "clearance.json")
MISSIONS_DIR    = os.path.join(DOSSIERS_DIR, "missions")

# —— Clearance JSON helpers ——
def load_clearance():
    with open(CLEARANCE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_clearance(data):
    with open(CLEARANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_required_roles(category: str, item: str):
    cf = load_clearance()
    return set(cf.get(category, {}).get(item, []))

# —— File listing helpers ——
def list_categories():
    return [
        d for d in os.listdir(DOSSIERS_DIR)
        if os.path.isdir(os.path.join(DOSSIERS_DIR, d))
    ]

def list_items(category: str):
    folder = os.path.join(DOSSIERS_DIR, category)
    if not os.path.isdir(folder):
        return []
    return [f[:-5] for f in os.listdir(folder) if f.lower().endswith(".json")]

# —— GitHub commit helper ——
def commit_to_github(path_in_repo: str, content: bytes, message: str):
    gh   = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPO)
    repo.create_file(path_in_repo, message, content)

# —— File Explorer UI ——
class CategorySelect(Select):
    def __init__(self):
        super().__init__(
            placeholder="Select a category…",
            options=[ SelectOption(label=c.replace("_"," ").title(), value=c)
                      for c in list_categories() ],
            min_values=1, max_values=1
        )

    async def callback(self, interaction: Interaction):
        self.category = self.values[0]
        items = list_items(self.category)
        embed = Embed(
            title=self.category.replace("_"," ").title(),
            description="Select an item…",
            color=0x3498DB
        )
        view = View(timeout=None)
        select_item = Select(
            placeholder="Select an item…",
            options=[ SelectOption(label=i.replace("_"," ").title(), value=i)
                      for i in items ],
            min_values=1, max_values=1
        )
        select_item.callback = self.on_item
        view.add_item(select_item)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_item(self, interaction: Interaction):
        item     = interaction.data["values"][0]
        category = self.category
        path     = os.path.join(DOSSIERS_DIR, category, f"{item}.json")
        if not os.path.isfile(path):
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)

        data = json.load(open(path, "r", encoding="utf-8"))
        required = get_required_roles(category, item)
        user_roles = {r.id for r in interaction.user.roles}

        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & required)
        ):
            return await interaction.response.send_message(
                "⛔ You lack the required clearance for this file.", ephemeral=True
            )

        embed = Embed(
            title=data.get("codename") or data.get("name") or item.replace("_"," ").title(),
            color=0x3498DB
        )
        for k, v in data.items():
            if k == "pdf_link": continue
            embed.add_field(name=k.replace("_"," ").title(), value=str(v), inline=False)
        if data.get("pdf_link"):
            embed.add_field(
                name="📎 AAR",
                value=f"[Click here for AAR]({data['pdf_link']})",
                inline=False
            )

        view = View(timeout=None)
        back = Button(label="← Back to list", style=ButtonStyle.secondary)
        async def on_back(btn, inter2: Interaction):
            embed2, view2 = CategorySelect().build_item_list_view(self.category)
            await inter2.response.edit_message(embed=embed2, view=view2)
        back.callback = on_back
        view.add_item(back)

        # allow selecting another directly
        sel2 = Select(
            placeholder="Select another…",
            options=[ SelectOption(label=i.replace("_"," ").title(), value=i)
                      for i in list_items(self.category) ],
            min_values=1, max_values=1
        )
        sel2.callback = self.on_item
        view.add_item(sel2)

        await interaction.response.edit_message(embed=embed, view=view)

    def build_item_list_view(self, category: str):
        items = list_items(category)
        embed = Embed(
            title=category.replace("_"," ").title(),
            description="Select an item…",
            color=0x3498DB
        )
        view = View(timeout=None)
        select_item = Select(
            placeholder="Select an item…",
            options=[ SelectOption(label=i.replace("_"," ").title(), value=i)
                      for i in items ],
            min_values=1, max_values=1
        )
        select_item.callback = self.on_item
        view.add_item(select_item)
        return embed, view

class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary)
        async def refresh_cb(btn, inter: Interaction):
            await inter.response.edit_message(
                embed=Embed(
                    title="Project SPECTRE File Explorer",
                    description=DESCRIPTION,
                    color=0x00FFCC
                ),
                view=RootView()
            )
        refresh.callback = refresh_cb
        self.add_item(refresh)

# —— Grant File Clearance Wizard ——
class GrantFileClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c)
                     for c in list_categories()],
            min_values=1, max_values=1
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i)
                     for i in list_items(self.category)],
            min_values=1, max_values=1
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Grant File Clearance",
                description=f"Category: **{self.category}**\nSelect an item…"
            ),
            view=self
        )

    async def select_item(self, interaction: Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        sel_role = Select(
            placeholder="Step 3: Select clearance role…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1, max_values=1
        )
        sel_role.callback = self.grant_role
        self.add_item(sel_role)
        await interaction.response.edit_message(
            embed=Embed(
                title="Grant File Clearance",
                description=(
                    f"Category: **{self.category}**\n"
                    f"Item: **{self.item}**\nSelect a role…"
                )
            ),
            view=self
        )

    async def grant_role(self, interaction: Interaction):
        role_id = int(interaction.data["values"][0])
        cf = load_clearance()
        cf.setdefault(self.category, {})
        cf[self.category].setdefault(self.item, [])
        if role_id not in cf[self.category][self.item]:
            cf[self.category][self.item].append(role_id)
        save_clearance(cf)
        await interaction.response.send_message(
            f"✅ Granted <@&{role_id}> access to `{self.category}/{self.item}.json`.",
            ephemeral=True
        )

# —— Revoke File Clearance Wizard ——
class RevokeFileClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c)
                     for c in list_categories()],
            min_values=1, max_values=1
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i)
                     for i in list_items(self.category)],
            min_values=1, max_values=1
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(
                title="Revoke File Clearance",
                description=f"Category: **{self.category}**\nSelect an item…"
            ),
            view=self
        )

    async def select_item(self, interaction: Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()
        cf = load_clearance()
        roles = cf.get(self.category, {}).get(self.item, [])
        sel_role = Select(
            placeholder="Step 3: Select role to revoke…",
            options=[SelectOption(label=interaction.guild.get_role(rid).name, value=str(rid))
                     for rid in roles],
            min_values=1, max_values=1
        )
        sel_role.callback = self.revoke_role
        self.add_item(sel_role)
        await interaction.response.edit_message(
            embed=Embed(
                title="Revoke File Clearance",
                description=(
                    f"Category: **{self.category}**\n"
                    f"Item: **{self.item}**\nSelect a role…"
                )
            ),
            view=self
        )

    async def revoke_role(self, interaction: Interaction):
        role_id = int(interaction.data["values"][0])
        cf = load_clearance()
        if role_id in cf.get(self.category, {}).get(self.item, []):
            cf[self.category][self.item].remove(role_id)
        save_clearance(cf)
        await interaction.response.send_message(
            f"✅ Revoked <@&{role_id}> from `{self.category}/{self.item}.json`.",
            ephemeral=True
        )

# —— Bot setup & Commands ——
bot = commands.Bot(intents=nextcord.Intents.default())

@bot.event
async def on_ready():
    print(f"✅ Project SPECTRE online as {bot.user}")
    channel = bot.get_channel(MENU_CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.embeds:
                if msg.embeds[0].title.startswith("Project SPECTRE File Explorer"):
                    await msg.edit(
                        embed=Embed(
                            title="Project SPECTRE File Explorer",
                            description=DESCRIPTION,
                            color=0x00FFCC
                        ),
                        view=RootView()
                    )
                    break
        else:
            await channel.send(
                embed=Embed(
                    title="Project SPECTRE File Explorer",
                    description=DESCRIPTION,
                    color=0x00FFCC
                ),
                view=RootView()
            )

# Clearance slash-commands
@bot.slash_command(name="grantfileclearance", description="Grant clearance", guild_ids=[GUILD_ID])
async def grantfileclearance_cmd(interaction: Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await interaction.response.send_message("⛔ Insufficient permissions.", ephemeral=True)
    await interaction.response.send_message(embed=Embed(title="Grant File Clearance", description="Step 1: Select category…", color=0x00FFCC), view=GrantFileClearanceView(), ephemeral=True)

@bot.slash_command(name="revokefileclearance", description="Revoke clearance", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(interaction: Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await interaction.response.send_message("⛔ Insufficient permissions.", ephemeral=True)
    await interaction.response.send_message(embed=Embed(title="Revoke File Clearance", description="Step 1: Select category…", color=0xFF5555), view=RevokeFileClearanceView(), ephemeral=True)

# Pre-build /addmission category choices
_category_choices = [Choice(name=c.replace("_"," ").title(), value=c) for c in list_categories()]

@bot.slash_command(name="addmission", description="Voeg nieuwe mission toe", guild_ids=[GUILD_ID])
async def addmission(
    interaction: Interaction,
    category: str = SlashOption(description="Selecteer categorie", choices=_category_choices),
    title: str = SlashOption(description="Titel"),
    filed_by: str = SlashOption(description="Filed by"),
    date: str = SlashOption(description="Date YYYY-MM-DD"),
    status: str = SlashOption(description="Status"),
    operation_type: str = SlashOption(description="Operation type"),
    end: str = SlashOption(description="End date YYYY-MM-DD"),
    honourable_mentions: str = SlashOption(description="Eervolle vermeldingen (komma-gescheiden)", required=False, default=""),
    pdf: Attachment = SlashOption(description="Upload PDF")
):
    await interaction.response.defer(ephemeral=True)

    os.makedirs(MISSIONS_DIR, exist_ok=True)
    mid = uuid.uuid4().hex[:8]
    pdf_fn = f"mission-{mid}.pdf"
    pdf_path = os.path.join(MISSIONS_DIR, pdf_fn)
    await pdf.save(pdf_path)

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
    json_path = os.path.join(MISSIONS_DIR, json_fn)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    with open(json_path, "rb") as f:
        commit_to_github(f"dossiers/missions/{json_fn}", f.read(), f"Add mission {title}")
    with open(pdf_path, "rb") as f:
        commit_to_github(f"dossiers/missions/{pdf_fn}", f.read(), f"Add PDF for {title}")

    await interaction.followup.send(f"✅ Mission **{title}** toegevoegd in **{category}** en gepusht!", ephemeral=True)

# —— Run Bot ——
bot.run(TOKEN)
