import os
import json
import datetime
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button, Modal, TextInput
from dotenv import load_dotenv
from config import get_log_channel, set_log_channel

# ==== Spaces storage ====
from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir, presigned_url
)

# ========= ENV =========
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1402017286432227449"))

# Als je S3_ROOT_PREFIX=dossiers/ hebt gezet, gebruiken we '/'
# anders plaatsen we alles onder 'dossiers/'.
_HAS_ROOT_PREFIX = bool(os.getenv("S3_ROOT_PREFIX", "").strip())
BASE_PREFIX = "/" if _HAS_ROOT_PREFIX else "dossiers"

def _cat_prefix(category: str) -> str:
    return f"{BASE_PREFIX}/{category}"

def _item_key(category: str, item: str) -> str:
    return f"{BASE_PREFIX}/{category}/{item}.json"

# ========= ACL (in Spaces) =========
# Bestand: acl/clearance.json onder dezelfde root
ACL_KEY = ("acl/clearance.json" if _HAS_ROOT_PREFIX else f"{BASE_PREFIX}/../acl/clearance.json").replace("//", "/")
# Bovenstaande truc: bij geen rootprefix komt ACL gewoon op 'acl/...' naast 'dossiers'.
# Simpel houden: we zorgen dat map 'acl' zichtbaar is.
ensure_dir("acl")

def load_clearance() -> dict:
    try:
        return read_json(ACL_KEY)
    except FileNotFoundError:
        return {}

def save_clearance(cfg: dict) -> None:
    save_json(ACL_KEY, cfg)

def get_required_roles(category: str, item: str) -> set:
    cf = load_clearance()
    roles = cf.get(category, {}).get(item, [])
    return set(int(r) for r in roles)

def grant_file_clearance(category: str, item: str, role_id: int) -> None:
    cf = load_clearance()
    cf.setdefault(category, {}).setdefault(item, [])
    if role_id not in cf[category][item]:
        cf[category][item].append(role_id)
    save_clearance(cf)

def revoke_file_clearance(category: str, item: str, role_id: int) -> None:
    cf = load_clearance()
    if category in cf and item in cf[category]:
        cf[category][item] = [r for r in cf[category][item] if r != role_id]
        if not cf[category][item]:
            del cf[category][item]
        if not cf[category]:
            del cf[category]
        save_clearance(cf)

# ========= Dossiers listing =========
def list_categories() -> list[str]:
    # Haal top-level submappen onder BASE_PREFIX
    dirs, _ = list_dir(BASE_PREFIX)
    # 'dirs' zijn strings met trailing '/', zet om naar cat-namen
    cats = [d[:-1] for d in dirs if d.endswith("/")]
    return sorted(cats)

def list_items(category: str) -> list[str]:
    # Haal directe files onder category
    _, files = list_dir(_cat_prefix(category))
    items = []
    for name, _size in files:
        if name.lower().endswith(".json"):
            items.append(name[:-5])
    return sorted(items)

def create_dossier_file(category: str, item: str, content: str) -> None:
    # Bestaat al?
    try:
        _ = read_text(_item_key(category, item))
        raise FileExistsError
    except FileNotFoundError:
        pass
    # Zorg dat 'map' zichtbaar is
    ensure_dir(_cat_prefix(category))
    # Parse JSON (wizard levert JSON)
    try:
        data = json.loads(content)
    except Exception:
        # Als geen geldige JSON, sla op als tekst
        save_text(_item_key(category, item), content)
        return
    save_json(_item_key(category, item), data)

def remove_dossier_file(category: str, item: str) -> None:
    delete_file(_item_key(category, item))

# —— Clearance description ——  
DESCRIPTION = (
    "Use `/uploadfile`, `/removefile`, `/grantfileclearance` or `/revokefileclearance` to manage files.\n\n"
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
LEVEL2_ROLE_ID     = 1402635734506016861
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

# Upload channel & logging
UPLOAD_CHANNEL_ID = 1405751160819683348
DEFAULT_LOG_CHANNEL_ID = 1402306158492123318
LOG_CHANNEL_ID = get_log_channel() or DEFAULT_LOG_CHANNEL_ID
LOG_FILE = os.path.join(os.path.dirname(__file__), "actions.log")  # lokale auditkopie (optioneel)

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

        # Lees direct uit Spaces
        try:
            data = read_json(_item_key(category, item))
        except FileNotFoundError:
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)

        required = get_required_roles(category, item)
        user_roles = {r.id for r in interaction.user.roles}

        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & required)
        ):
            await log_action(
                f"🚫 {interaction.user} attempted to access `{category}/{item}.json` without sufficient clearance."
            )
            return await interaction.response.send_message(
                "⛔ You lack the required clearance for this file.", ephemeral=True
            )

        await log_action(f"📄 {interaction.user} accessed `{category}/{item}.json`.")

        # build detail embed
        title = data.get("codename") or data.get("name") or item.replace("_", " ").title()
        rpt = Embed(title=title, color=0x3498DB)

        # show required clearance
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name="🔐 Required Clearance", value=", ".join(roles_needed), inline=False)

        # show dossier details
        summary = data.get("summary")
        if summary:
            rpt.description = summary
        for key, value in data.items():
            if key in {"codename", "name", "summary"}:
                continue
            if key == "pdf_link":
                rpt.add_field(name="📎 Attached File", value=f"[Open]({value})", inline=False)
            else:
                rpt.add_field(name=key.replace("_", " ").title(), value=str(value), inline=False)

        # dropdown to pick another item
        items = list_items(category)
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i) for i in items],
            min_values=1, max_values=1
        )
        select_another.callback = self.on_item

        # back to item list
        back = Button(label="← Back to list", style=ButtonStyle.secondary)
        async def on_back(_btn, inter2: nextcord.Interaction):
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

# —— Upload File Wizard ——
class UploadDetailsModal(Modal):
    def __init__(self, parent_view: "UploadFileView"):
        super().__init__(title="Upload File")
        self.parent_view = parent_view
        self.item = TextInput(label="File name")
        self.content = TextInput(label="File content (JSON)", style=TextInputStyle.paragraph)
        self.add_item(self.item); self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        self.parent_view.item = self.item.value.strip().lower().replace(" ", "_")
        self.parent_view.content = self.content.value
        if getattr(self.parent_view, "role_id", None) is None:
            await interaction.response.send_message("❌ Please select a clearance role first.", ephemeral=True)
            return
        try:
            create_dossier_file(self.parent_view.category, self.parent_view.item, self.parent_view.content)
        except FileExistsError:
            await interaction.response.send_message("❌ File already exists.", ephemeral=True)
            return

        grant_file_clearance(self.parent_view.category, self.parent_view.item, self.parent_view.role_id)
        await interaction.response.send_message(
            f"✅ Uploaded `{self.parent_view.category}/{self.parent_view.item}.json` with clearance <@&{self.parent_view.role_id}>.",
            ephemeral=True,
        )
        await log_action(
            f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{self.parent_view.item}.json` "
            f"with clearance <@&{self.parent_view.role_id}>."
        )

class UploadFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_", " ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1,
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        sel_role = Select(
            placeholder="Step 2: Select clearance role…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1, max_values=1,
        )
        sel_role.callback = self.select_role
        self.add_item(sel_role)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary)
        submit.callback = self.open_modal
        self.add_item(submit)

        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description=f"Category: **{self.category}**\nSelect a role and enter details…"),
            view=self,
        )

    async def select_role(self, interaction: nextcord.Interaction):
        self.role_id = int(interaction.data["values"][0])
        await interaction.response.send_message(f"Clearance role set to <@&{self.role_id}>.", ephemeral=True)

    async def open_modal(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(UploadDetailsModal(self))

class RemoveFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_", " ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1,
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i.replace("_", " ").title(), value=i) for i in list_items(self.category)],
            min_values=1, max_values=1,
        )
        sel_item.callback = self.delete_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Remove File", description=f"Category: **{self.category}**\nSelect an item…", color=0xFF5555),
            view=self,
        )

    async def delete_item(self, interaction: nextcord.Interaction):
        item = interaction.data["values"][0]
        try:
            remove_dossier_file(self.category, item)
        except FileNotFoundError:
            await interaction.response.send_message("❌ File not found.", ephemeral=True)
            return
        await interaction.response.send_message(f"🗑️ Deleted `{self.category}/{item}.json`.", ephemeral=True)
        await log_action(f"🗑 {interaction.user} deleted `{self.category}/{item}.json`.")

class UploadMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = Button(label="📤 Upload File", style=ButtonStyle.primary); btn.callback = self.start_wizard
        self.add_item(btn)
        rm_btn = Button(label="🗑️ Remove File", style=ButtonStyle.danger); rm_btn.callback = self.start_remove
        self.add_item(rm_btn)

    async def start_wizard(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(
            embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
            view=UploadFileView(), ephemeral=True,
        )

    async def start_remove(self, interaction: nextcord.Interaction):
        user_roles = {r.id for r in interaction.user.roles}
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & ALLOWED_ASSIGN_ROLES)
        ):
            return await interaction.response.send_message(
                "⛔ Only Level 5+, Classified, Admin or Owner may remove files.",
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
            view=RemoveFileView(), ephemeral=True,
        )

# —— Grant/Revoke Wizards ——
class GrantFileClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i) for i in list_items(self.category)],
            min_values=1, max_values=1
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Grant File Clearance", description=f"Category: **{self.category}**\nSelect an item…"),
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
                description=(f"Category: **{self.category}**\nItem: **{self.item}**\nSelect a role…")
            ),
            view=self
        )

    async def grant_role(self, interaction: nextcord.Interaction):
        role_id = int(interaction.data["values"][0])
        grant_file_clearance(self.category, self.item, role_id)
        await interaction.response.send_message(
            content=f"✅ Granted <@&{role_id}> access to `{self.category}/{self.item}.json`.",
            ephemeral=True
        )
        await log_action(f"🔓 {interaction.user} granted <@&{role_id}> access to `{self.category}/{self.item}.json`.")

class RevokeFileClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        # items
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i) for i in list_items(self.category)],
            min_values=1, max_values=1
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Revoke File Clearance", description=f"Category: **{self.category}**\nSelect an item…"),
            view=self
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()
        cf = load_clearance()
        roles = cf.get(self.category, {}).get(self.item, [])
        sel_role = Select(
            placeholder="Step 3: Select role to revoke…",
            options=[SelectOption(label=interaction.guild.get_role(int(rid)).name, value=str(rid)) for rid in roles],
            min_values=1, max_values=1
        )
        sel_role.callback = self.revoke_role
        self.add_item(sel_role)
        await interaction.response.edit_message(
            embed=Embed(
                title="Revoke File Clearance",
                description=(f"Category: **{self.category}**\nItem: **{self.item}**\nSelect a role…")
            ),
            view=self
        )

    async def revoke_role(self, interaction: nextcord.Interaction):
        role_id = int(interaction.data["values"][0])
        revoke_file_clearance(self.category, self.item, role_id)
        await interaction.response.send_message(
            content=f"✅ Revoked <@&{role_id}> from `{self.category}/{self.item}.json`.",
            ephemeral=True
        )
        await log_action(f"🔒 {interaction.user} revoked <@&{role_id}> from `{self.category}/{self.item}.json`.")

# —— Bot setup & Commands ——
intents = nextcord.Intents.default()
bot     = commands.Bot(intents=intents)

async def log_action(message: str):
    """Record administrative message to a local file and the log channel."""
    timestamp = datetime.datetime.utcnow().isoformat()
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {message}\n")
    except Exception:
        pass
    if not LOG_CHANNEL_ID:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except nextcord.HTTPException:
            return
    if channel:
        await channel.send(message)

async def handle_upload(message: nextcord.Message):
    """Persist JSON attachments from message into the dossier store."""
    category = message.content.strip().lower().replace(" ", "_")
    if not category:
        await message.channel.send("❌ Please specify a category in the message content.")
        return
    if category not in list_categories():
        await message.channel.send(f"❌ Unknown category `{category}`.")
        return

    processed = False
    for attachment in message.attachments:
        if not attachment.filename.lower().endswith(".json"):
            continue
        data = (await attachment.read()).decode("utf-8")
        item = os.path.splitext(attachment.filename)[0]
        try:
            create_dossier_file(category, item, data)
        except FileExistsError:
            await message.channel.send(f"⚠️ `{item}` already exists in `{category}`.")
        else:
            await message.channel.send(f"✅ Added `{item}` to `{category}`.")
            await log_action(f"⬆️ {message.author} uploaded `{category}/{item}.json`.")
            processed = True

    if not processed:
        await message.channel.send("❌ No JSON files found in the upload.")

@bot.event
async def on_message(message: nextcord.Message):
    if message.author.bot:
        return
    if message.channel.id != UPLOAD_CHANNEL_ID:
        return
    await handle_upload(message)

@bot.event
async def on_ready():
    print(f"✅ Project SPECTRE online as {bot.user}")
    # Zorg dat basisstructuur zichtbaar is
    ensure_dir(BASE_PREFIX if BASE_PREFIX != "/" else "dossiers")  # toont root-map indien nodig
    for cat in ("missions", "personnel", "intelligence"):
        ensure_dir(_cat_prefix(cat))

    channel = bot.get_channel(MENU_CHANNEL_ID)
    if channel:
        await channel.send(
            embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
            view=RootView()
        )
    upload_channel = bot.get_channel(UPLOAD_CHANNEL_ID)
    if upload_channel:
        await upload_channel.send(
            embed=Embed(title="Upload New Dossier", description="Use the buttons below to upload or remove files.", color=0x00FFCC),
            view=UploadMenuView(),
        )

@bot.slash_command(name="uploadfile", description="Create a dossier and set its clearance in one step", guild_ids=[GUILD_ID])
async def uploadfile_cmd(interaction: nextcord.Interaction):
    if interaction.channel.id != UPLOAD_CHANNEL_ID:
        return await interaction.response.send_message("⛔ This command can only be used in the upload channel.", ephemeral=True)
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may upload files.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
        view=UploadFileView(), ephemeral=True,
    )

@bot.slash_command(name="removefile", description="Delete a dossier JSON file", guild_ids=[GUILD_ID])
async def removefile_cmd(interaction: nextcord.Interaction):
    if interaction.channel.id != UPLOAD_CHANNEL_ID:
        return await interaction.response.send_message("⛔ This command can only be used in the upload channel.", ephemeral=True)
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may remove files.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
        view=RemoveFileView(), ephemeral=True,
    )

@bot.slash_command(name="grantfileclearance", description="Grant a clearance role access to a dossier", guild_ids=[GUILD_ID])
async def grantfileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may grant clearance.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Grant File Clearance", description="Step 1: Select category…", color=0x00FFCC),
        view=GrantFileClearanceView(), ephemeral=True
    )

@bot.slash_command(name="revokefileclearance", description="Revoke a clearance role's access from a dossier", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may revoke clearance.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Revoke File Clearance", description="Step 1: Select category…", color=0xFF5555),
        view=RevokeFileClearanceView(), ephemeral=True
    )

@bot.slash_command(name="summonmenu", description="Resend the file explorer menu", guild_ids=[GUILD_ID])
async def summonmenu_cmd(interaction: nextcord.Interaction):
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("⛔ Only Admin or Owner may summon the menu.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
        view=RootView(),
    )
    await log_action(f"📣 {interaction.user} summoned the file explorer menu.")

@bot.slash_command(name="setlogchannel", description="Set the logging channel", guild_ids=[GUILD_ID])
async def setlogchannel_cmd(interaction: nextcord.Interaction, channel: nextcord.TextChannel):
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("⛔ Only Admin or Owner may set the log channel.", ephemeral=True)
    global LOG_CHANNEL_ID
    set_log_channel(channel.id)
    LOG_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)
    await log_action(f"🛠 {interaction.user} set the log channel to {channel.mention}.")

if __name__ == "__main__":
    bot.run(TOKEN)
