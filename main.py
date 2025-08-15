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

# ---- Root prefix (S3_ROOT_PREFIX of 'dossiers') ----
ROOT_PREFIX = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")

def _cat_prefix(category: str) -> str:
    return f"{ROOT_PREFIX}/{category}".replace("//", "/")

def _with_ext(item_rel: str, ext: str) -> str:
    item_rel = item_rel.strip().strip("/")
    if item_rel.lower().endswith((".json", ".txt")):
        return item_rel
    return f"{item_rel}{ext}"

def _strip_ext(name: str) -> str:
    for ext in (".json", ".txt"):
        if name.lower().endswith(ext):
            return name[:-len(ext)]
    return name

def _find_existing_item_key(category: str, item_rel: str) -> tuple[str, str] | None:
    base = f"{ROOT_PREFIX}/{category}/{item_rel}".replace("//", "/").strip("/")
    candidates = (
        [base] if item_rel.lower().endswith((".json", ".txt"))
        else [base + ".json", base + ".txt"]
    )
    for key in candidates:
        try:
            _ = read_text(key)  # test read
            ext = ".json" if key.lower().endswith(".json") else ".txt"
            return key, ext
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return None

# ========= ACL in Spaces =========
ACL_KEY = f"{ROOT_PREFIX}/acl/clearance.json".replace("//", "/")

def load_clearance() -> dict:
    try:
        return read_json(ACL_KEY)
    except FileNotFoundError:
        return {}

def save_clearance(cfg: dict) -> None:
    ensure_dir(f"{ROOT_PREFIX}/acl")
    save_json(ACL_KEY, cfg)

def get_required_roles(category: str, item_rel_base: str) -> set:
    cf = load_clearance()
    roles = cf.get(category, {}).get(item_rel_base, [])
    return set(int(r) for r in roles)

def grant_file_clearance(category: str, item_rel_base: str, role_id: int) -> None:
    cf = load_clearance()
    cf.setdefault(category, {}).setdefault(item_rel_base, [])
    if role_id not in cf[category][item_rel_base]:
        cf[category][item_rel_base].append(role_id)
    save_clearance(cf)

def revoke_file_clearance(category: str, item_rel_base: str, role_id: int) -> None:
    cf = load_clearance()
    if category in cf and item_rel_base in cf[category]:
        cf[category][item_rel_base] = [r for r in cf[category][item_rel_base] if r != role_id]
        if not cf[category][item_rel_base]:
            del cf[category][item_rel_base]
        if not cf[category]:
            del cf[category]
        save_clearance(cf)

# ========= Dossiers listing =========
def list_categories() -> list[str]:
    dirs, _ = list_dir(ROOT_PREFIX)
    cats = [d[:-1] for d in dirs if d.endswith("/")]
    if not cats:
        cats = ["missions", "personnel", "intelligence"]
    return sorted(cats)

def list_items_recursive(category: str, max_items: int = 3000) -> list[str]:
    root = _cat_prefix(category).rstrip("/")
    items_base = set()
    stack = [root]
    while stack and len(items_base) < max_items:
        base = stack.pop()
        dirs, files = list_dir(base)
        for name, _size in files:
            if name.lower().endswith((".json", ".txt")):
                rel = f"{base}/{name}".replace("//", "/")
                rel_from_cat = rel[len(root):].strip("/").replace("\\", "/")
                items_base.add(_strip_ext(rel_from_cat))
        for d in dirs:
            stack.append(f"{base}/{d.strip('/')}".replace("//", "/"))
    return sorted(items_base)

def create_dossier_file(category: str, item_rel_input: str, content: str, prefer_txt_default: bool = True) -> None:
    item_rel_input = item_rel_input.strip().strip("/")
    has_ext = item_rel_input.lower().endswith((".json", ".txt"))
    if not has_ext:
        item_rel = _with_ext(item_rel_input, ".txt" if prefer_txt_default else ".json")
    else:
        item_rel = item_rel_input

    if _find_existing_item_key(category, item_rel_input):
        raise FileExistsError

    ensure_dir(_cat_prefix(category))
    # JSON proberen
    try:
        data = json.loads(content)
        key = f"{ROOT_PREFIX}/{category}/{_with_ext(item_rel, '.json')}".replace("//", "/") if not item_rel.lower().endswith(".txt") else f"{ROOT_PREFIX}/{category}/{item_rel}"
        if key.lower().endswith(".json"):
            save_json(key, data)
        else:
            save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        key = f"{ROOT_PREFIX}/{category}/{_with_ext(item_rel, '.txt')}".replace("//", "/")
        save_text(key, content)

def remove_dossier_file(category: str, item_rel_base: str) -> None:
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, _ = found
    delete_file(key)

# —— RP Intro ——  
INTRO_TITLE = "SPECTRE Archive Terminal"
INTRO_DESC = (
    "Welcome, Operative.\n"
    "Access the Directorate’s secure archive. Navigation and actions are monitored.\n\n"
    "**Commands**\n"
    "• `/uploadfile` — file + clearance in één flow\n"
    "• `/removefile` — verwijder een dossier\n"
    "• `/grantfileclearance` / `/revokefileclearance` — rollen beheren\n\n"
    "**Files**: `.json` *of* `.txt` (als JSON faalt, tonen we platte tekst)."
)

# —— Role-IDs ——
LEVEL1_ROLE_ID     = 1365097430713896992
LEVEL2_ROLE_ID     = 1402635734506016861
LEVEL3_ROLE_ID     = 1365096533069926460
LEVEL4_ROLE_ID     = 1365094103578181765
LEVEL5_ROLE_ID     = 1365093753035161712
CLASSIFIED_ROLE_ID = 1365093656859512863
ALLOWED_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID, LEVEL2_ROLE_ID, LEVEL3_ROLE_ID, LEVEL4_ROLE_ID, LEVEL5_ROLE_ID, CLASSIFIED_ROLE_ID
}

# Upload & log
UPLOAD_CHANNEL_ID = 1405751160819683348
DEFAULT_LOG_CHANNEL_ID = 1402306158492123318

# ========= Persistent Views =========
# We geven elke component een custom_id en registreren de Views met bot.add_view()
# zodat knoppen/menus blijven werken na restarts.

class CategorySelect(Select):
    def __init__(self):
        cats = list_categories()
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats[:25]],
            min_values=1, max_values=1,
            custom_id="cat_select_v1"
        )

    def build_item_list_view(self, category: str):
        items = list_items_recursive(category)
        embed = Embed(
            title=f"Archive: {category.replace('_',' ').title()}",
            description=("Select an item…" if items else "_No files in this category._"),
            color=0x00FFCC
        )
        view = View(timeout=None)
        if items:
            select_item = Select(
                placeholder="Select an item…",
                options=[SelectOption(label=i, value=i) for i in items[:25]],
                min_values=1, max_values=1,
                custom_id="cat_item_select_v1"
            )
            select_item.callback = self.on_item
            view.add_item(select_item)
        return embed, view

    async def callback(self, interaction: nextcord.Interaction):
        self.category = self.values[0]
        embed, view = self.build_item_list_view(self.category)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        category = getattr(self, "category", None)
        if not category:
            # Als we via persistent view na restart komen, haal category uit title van embed is tricky;
            # fallback: eerste optie
            category = list_categories()[0]

        found = _find_existing_item_key(category, item_rel_base)
        if not found:
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)
        key, ext = found

        required = get_required_roles(category, item_rel_base)
        user_roles = {r.id for r in interaction.user.roles}
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & required)
        ):
            await log_action(
                f"🚫 {interaction.user} attempted to access `{category}/{item_rel_base}{ext}` without clearance."
            )
            return await interaction.response.send_message("⛔ Insufficient clearance.", ephemeral=True)

        await log_action(f"📄 {interaction.user} accessed `{category}/{item_rel_base}{ext}`.")

        content_text = None
        parsed = None
        try:
            parsed = read_json(key)
        except Exception:
            try:
                content_text = read_text(key)
            except FileNotFoundError:
                return await interaction.response.send_message("❌ File not found.", ephemeral=True)

        title = item_rel_base.split("/")[-1].replace("_", " ").title()
        rpt = Embed(title=f"{title} — {category.title()}", color=0x00FFCC)

        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name="🔐 Required Clearance", value=", ".join(roles_needed), inline=False)

        if parsed is not None and isinstance(parsed, dict):
            summary = parsed.get("summary")
            if summary:
                rpt.description = summary
            for k, v in parsed.items():
                if k in {"summary"}:
                    continue
                if k == "pdf_link":
                    rpt.add_field(name="📎 Attached File", value=f"[Open]({v})", inline=False)
                else:
                    rpt.add_field(name=k.replace("_"," ").title(), value=str(v), inline=False)
        else:
            if parsed is not None and not isinstance(parsed, dict):
                content_text = json.dumps(parsed, ensure_ascii=False, indent=2)
            if not content_text:
                content_text = "(empty)"
            show = content_text if len(content_text) <= 1800 else content_text[:1800] + "\n…(truncated)"
            rpt.add_field(name="Contents", value=f"```txt\n{show}\n```", inline=False)

        items = list_items_recursive(category)
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1,
            custom_id="cat_item_select_again_v1"
        )
        select_another.callback = self.on_item

        back = Button(label="← Back to list", style=ButtonStyle.secondary, custom_id="back_to_list_v1")
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
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary, custom_id="refresh_root_v1")
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

    async def refresh_menu(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView()
        )

class UploadDetailsModal(Modal):
    def __init__(self, parent_view: "UploadFileView"):
        super().__init__(title="Archive Upload")
        self.parent_view = parent_view
        self.item = TextInput(label="File name (subfolders ok, ext optional: .json or .txt)")
        self.content = TextInput(label="File content (JSON or Text)", style=TextInputStyle.paragraph)
        self.add_item(self.item); self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        self.parent_view.item_rel = self.item.value.strip().lower().replace(" ", "_").strip("/")
        self.parent_view.content = self.content.value
        if getattr(self.parent_view, "role_id", None) is None:
            await interaction.response.send_message("❌ Select a clearance role first.", ephemeral=True)
            return
        try:
            create_dossier_file(self.parent_view.category, self.parent_view.item_rel, self.parent_view.content, prefer_txt_default=True)
        except FileExistsError:
            await interaction.response.send_message("❌ File already exists.", ephemeral=True)
            return

        item_base = _strip_ext(self.parent_view.item_rel)
        grant_file_clearance(self.parent_view.category, item_base, self.parent_view.role_id)
        await interaction.response.send_message(
            f"✅ Uploaded `{self.parent_view.category}/{self.parent_view.item_rel}` with clearance <@&{self.parent_view.role_id}>.",
            ephemeral=True,
        )
        await log_action(
            f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{self.parent_view.item_rel}` "
            f"with clearance <@&{self.parent_view.role_id}>."
        )

class UploadFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_", " ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1,
            custom_id="upload_cat_select_v1"
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
            custom_id="upload_role_select_v1"
        )
        sel_role.callback = self.select_role
        self.add_item(sel_role)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary, custom_id="upload_open_modal_v1")
        submit.callback = self.open_modal
        self.add_item(submit)

        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description=f"Category: **{self.category}**\nSelect a role and enter details…", color=0x00FFCC),
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
            custom_id="remove_cat_select_v1"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            await interaction.response.edit_message(
                embed=Embed(title="Remove File", description=f"Category: **{self.category}**\n(No files found)", color=0xFF5555),
                view=self
            )
            return
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1,
            custom_id="remove_item_select_v1"
        )
        sel_item.callback = self.delete_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Remove File", description=f"Category: **{self.category}**\nSelect an item…", color=0xFF5555),
            view=self,
        )

    async def delete_item(self, interaction: nextcord.Interaction):
        item_rel_base = interaction.data["values"][0]
        try:
            remove_dossier_file(self.category, item_rel_base)
        except FileNotFoundError:
            await interaction.response.send_message("❌ File not found.", ephemeral=True)
            return
        await interaction.response.send_message(f"🗑️ Deleted `{self.category}/{item_rel_base}`.", ephemeral=True)
        await log_action(f"🗑 {interaction.user} deleted `{self.category}/{item_rel_base}`.")

class UploadMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = Button(label="📤 Upload File", style=ButtonStyle.primary, custom_id="upload_btn_v1"); btn.callback = self.start_wizard
        self.add_item(btn)
        rm_btn = Button(label="🗑️ Remove File", style=ButtonStyle.danger, custom_id="remove_btn_v1"); rm_btn.callback = self.start_remove
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

# —— Bot setup & Commands ——
intents = nextcord.Intents.default()
bot     = commands.Bot(intents=intents)
LOG_CHANNEL_ID = get_log_channel() or DEFAULT_LOG_CHANNEL_ID

async def log_action(message: str):
    if not LOG_CHANNEL_ID:
        return
    try:
        channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"{datetime.datetime.utcnow().isoformat()} {message}")
    except Exception:
        pass

async def handle_upload(message: nextcord.Message):
    category = message.content.strip().lower().replace(" ", "_")
    if not category:
        await message.channel.send("❌ Add the category name in the message text.")
        return
    if category not in list_categories():
        await message.channel.send(f"❌ Unknown category `{category}`.")
        return

    processed = False
    for attachment in message.attachments:
        if not (attachment.filename.lower().endswith(".json") or attachment.filename.lower().endswith(".txt")):
            continue
        data = (await attachment.read()).decode("utf-8")
        item_rel_input = os.path.splitext(attachment.filename)[0] if attachment.filename.lower().endswith(".json") else attachment.filename
        try:
            create_dossier_file(category, item_rel_input, data, prefer_txt_default=True)
        except FileExistsError:
            await message.channel.send(f"⚠️ `{item_rel_input}` already exists.")
        else:
            await message.channel.send(f"✅ Added `{item_rel_input}` to `{category}`.")
            await log_action(f"⬆️ {message.author} uploaded `{category}/{item_rel_input}`.")
            processed = True

    if not processed:
        await message.channel.send("❌ No .json/.txt files found in the upload.")

@bot.event
async def on_message(message: nextcord.Message):
    if message.author.bot:
        return
    if message.channel.id != UPLOAD_CHANNEL_ID:
        return
    await handle_upload(message)

@bot.event
async def on_ready():
    print(f"✅ SPECTRE online as {bot.user}")

    # Maak basisstructuur zichtbaar
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence", "acl"):
        ensure_dir(f"{ROOT_PREFIX}/{cat}")

    # PERSISTENT VIEWS registreren (zodat knoppen/menus blijven werken na restarts)
    bot.add_view(RootView())
    bot.add_view(UploadMenuView())

    # Post (of opnieuw posten) menu’s
    main_ch = bot.get_channel(MENU_CHANNEL_ID)
    if main_ch:
        await main_ch.send(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView()
        )

    up_ch = bot.get_channel(UPLOAD_CHANNEL_ID)
    if up_ch:
        await up_ch.send(
            embed=Embed(
                title="Archive Uplink",
                description="Use the buttons below to **upload** a new dossier or **remove** an existing one.",
                color=0x00FFCC
            ),
            view=UploadMenuView(),
        )

@bot.slash_command(name="uploadfile", description="Create a dossier and set its clearance", guild_ids=[GUILD_ID])
async def uploadfile_cmd(interaction: nextcord.Interaction):
    if interaction.channel.id != UPLOAD_CHANNEL_ID:
        return await interaction.response.send_message("⛔ Use this in the upload channel.", ephemeral=True)
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may upload.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
        view=UploadFileView(), ephemeral=True,
    )

@bot.slash_command(name="removefile", description="Delete a dossier file", guild_ids=[GUILD_ID])
async def removefile_cmd(interaction: nextcord.Interaction):
    if interaction.channel.id != UPLOAD_CHANNEL_ID:
        return await interaction.response.send_message("⛔ Use this in the upload channel.", ephemeral=True)
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may remove.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
        view=RemoveFileView(), ephemeral=True,
    )

@bot.slash_command(name="grantfileclearance", description="Grant clearance to a dossier", guild_ids=[GUILD_ID])
async def grantfileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may grant.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Grant File Clearance", description="Step 1: Select category…", color=0x00FFCC),
        view=GrantFileClearanceView(), ephemeral=True
    )

@bot.slash_command(name="revokefileclearance", description="Revoke a dossier clearance", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may revoke.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Revoke File Clearance", description="Step 1: Select category…", color=0xFF5555),
        view=RevokeFileClearanceView(), ephemeral=True
    )

@bot.slash_command(name="summonmenu", description="Resend the explorer menu", guild_ids=[GUILD_ID])
async def summonmenu_cmd(interaction: nextcord.Interaction):
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
        view=RootView(),
    )
    await log_action(f"📣 {interaction.user} summoned the file explorer menu.")

@bot.slash_command(name="setlogchannel", description="Set the logging channel", guild_ids=[GUILD_ID])
async def setlogchannel_cmd(interaction: nextcord.Interaction, channel: nextcord.TextChannel):
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
    global LOG_CHANNEL_ID
    set_log_channel(channel.id)
    LOG_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)
    await log_action(f"🛠 {interaction.user} set the log channel to {channel.mention}.")

if __name__ == "__main__":
    bot.run(TOKEN)
