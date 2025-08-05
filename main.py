import os
import json
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button
from dotenv import load_dotenv

# —— Load ENV ——
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID"))

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
LEVEL1_ROLE_ID     = 1365097430713896992
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

# —— File Explorer UI ——
class CategorySelect(Select):
    def __init__(self):
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c)
                     for c in list_categories()],
            min_values=1, max_values=1
        )

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
            options=[SelectOption(label=i.replace("_"," ").title(), value=i)
                     for i in items],
            min_values=1, max_values=1
        )
        select_item.callback = self.on_item
        view.add_item(select_item)
        return embed, view

    async def callback(self, interaction: nextcord.Interaction):
        self.category = self.values[0]
        embed, view = self.build_item_list_view(self.category)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_item(self, interaction: nextcord.Interaction):
        item     = interaction.data["values"][0]
        category = self.category
        path     = os.path.join(DOSSIERS_DIR, category, f"{item}.json")
        if not os.path.isfile(path):
            return await interaction.response.send_message(
                "❌ File not found.", ephemeral=True
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
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

        # build detail embed
        title = data.get("codename") or data.get("name") or item.replace("_", " ").title()
        rpt = Embed(title=title, color=0x3498DB)

        # show required clearance
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(
            name="🔐 Required Clearance",
            value=", ".join(roles_needed),
            inline=False,
        )

        # show dossier details
        summary = data.get("summary")
        if summary:
            rpt.description = summary
        for key, value in data.items():
            if key in {"codename", "name", "summary"}:
                continue
            if key == "pdf_link":
                rpt.add_field(
                    name="📎 Attached File",
                    value=f"[Open]({value})",
                    inline=False,
                )
            else:
                rpt.add_field(
                    name=key.replace("_", " ").title(),
                    value=str(value),
                    inline=False,
                )

        # dropdown to pick another item
        items = list_items(category)
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i)
                     for i in items],
            min_values=1, max_values=1
        )
        select_another.callback = self.on_item

        # back to item list
        back = Button(label="← Back to list", style=ButtonStyle.secondary)
        async def on_back(btn, inter2: nextcord.Interaction):
            embed2, view2 = self.build_item_list_view(category)
            await inter2.response.edit_message(embed=embed2, view=view2)
        back.callback = on_back

        view = View(timeout=None)
        view.add_item(select_another)
        view.add_item(back)

        await interaction.response.edit_message(embed=rpt, view=view)

class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary)
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

    async def refresh_menu(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(
                title="Project SPECTRE File Explorer",
                description=DESCRIPTION,
                color=0x00FFCC
            ),
            view=RootView()
        )

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

    async def select_category(self, interaction: nextcord.Interaction):
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

    async def select_item(self, interaction: nextcord.Interaction):
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
                    f"Item: **{self.item}**\n"
                    "Select a role…"
                )
            ),
            view=self
        )

    async def grant_role(self, interaction: nextcord.Interaction):
        role_id = int(interaction.data["values"][0])
        cf = load_clearance()
        cf.setdefault(self.category, {})
        cf[self.category].setdefault(self.item, [])
        if role_id not in cf[self.category][self.item]:
            cf[self.category][self.item].append(role_id)
        save_clearance(cf)
        await interaction.response.send_message(
            content=(
                f"✅ Granted <@&{role_id}> access to "
                f"`{self.category}/{self.item}.json`."
            ),
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

    async def select_category(self, interaction: nextcord.Interaction):
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

    async def select_item(self, interaction: nextcord.Interaction):
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
                    f"Item: **{self.item}**\n"
                    "Select a role…"
                )
            ),
            view=self
        )

    async def revoke_role(self, interaction: nextcord.Interaction):
        role_id = int(interaction.data["values"][0])
        cf = load_clearance()
        if role_id in cf.get(self.category, {}).get(self.item, []):
            cf[self.category][self.item].remove(role_id)
        save_clearance(cf)
        await interaction.response.send_message(
            content=(
                f"✅ Revoked <@&{role_id}> from "
                f"`{self.category}/{self.item}.json`."
            ),
            ephemeral=True
        )

# —— Bot setup & Commands ——
intents = nextcord.Intents.default()
bot     = commands.Bot(intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Project SPECTRE online as {bot.user}")
    channel = bot.get_channel(MENU_CHANNEL_ID)
    if channel:
        await channel.send(
            embed=Embed(
                title="Project SPECTRE File Explorer",
                description=DESCRIPTION,
                color=0x00FFCC
            ),
            view=RootView()
        )

@bot.slash_command(
    name="grantfileclearance",
    description="Grant a clearance role access to a dossier",
    guild_ids=[GUILD_ID]
)
async def grantfileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message(
            "⛔ Only Level 5+, Classified, Admin or Owner may grant clearance.",
            ephemeral=True
        )
    await interaction.response.send_message(
        embed=Embed(
            title="Grant File Clearance",
            description="Step 1: Select category…",
            color=0x00FFCC
        ),
        view=GrantFileClearanceView(),
        ephemeral=True
    )

@bot.slash_command(
    name="revokefileclearance",
    description="Revoke a clearance role's access from a dossier",
    guild_ids=[GUILD_ID]
)
async def revokefileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message(
            "⛔ Only Level 5+, Classified, Admin or Owner may revoke clearance.",
            ephemeral=True
        )
    await interaction.response.send_message(
        embed=Embed(
            title="Revoke File Clearance",
            description="Step 1: Select category…",
            color=0xFF5555
        ),
        view=RevokeFileClearanceView(),
        ephemeral=True
    )

bot.run(TOKEN)
