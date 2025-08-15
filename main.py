import os
import json
import datetime as dt
from typing import Tuple, Optional

import nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle, Interaction
from nextcord.ext import commands
from nextcord.ui import View, Select, Button, Modal, TextInput
from dotenv import load_dotenv
from config import get_log_channel, set_log_channel

# ==== Spaces storage ====
from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir
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

def _strip_ext(name: str) -> str:
    for ext in (".json", ".txt"):
        if name.lower().endswith(ext):
            return name[:-len(ext)]
    return name

def _find_existing_item_key(category: str, item_rel: str) -> Optional[Tuple[str, str]]:
    """Prefer .json, then .txt. Return (key, ext) or None."""
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
    item_rel = item_rel_input if has_ext else (item_rel_input + (".txt" if prefer_txt_default else ".json"))

    if _find_existing_item_key(category, item_rel_input):
        raise FileExistsError

    ensure_dir(_cat_prefix(category))
    # JSON proberen
    try:
        data = json.loads(content)
        if item_rel.lower().endswith(".json"):
            save_json(f"{ROOT_PREFIX}/{category}/{item_rel}".replace("//", "/"), data)
        else:
            # user vroeg .txt maar content is JSON → pretty text
            save_text(f"{ROOT_PREFIX}/{category}/{item_rel}".replace("//", "/"), json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        # plain text
        if not item_rel.lower().endswith(".txt"):
            item_rel += ".txt"
        save_text(f"{ROOT_PREFIX}/{category}/{item_rel}".replace("//", "/"), content)

def remove_dossier_file(category: str, item_rel_base: str) -> None:
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, _ = found
    delete_file(key)

# —— RP Intro (jouw tekst) ——  
INTRO_TITLE = "SPECTRE Archive Terminal"
INTRO_DESC  = (
    "Welcome, Operative.\n"
    "Access the Directorate’s secure archive. Navigation and actions are monitored.\n\n"
    "**Commands**\n"
    "• `/uploadfile` — **ARCHIVIST ONLY**\n"
    "• `/removefile` — **ARCHIVIST ONLY**\n"
    "• `/grantfileclearance` / `/revokefileclearance` — **ARCHIVIST ONLY**\n\n"
    "**Files:** `.json` or `.txt` *(IF FILE FAILS REPORT TO ARCHIVIST).*"
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

UPLOAD_CHANNEL_ID       = 1405751160819683348
DEFAULT_LOG_CHANNEL_ID  = 1402306158492123318

# ========= Bot =========
intents = nextcord.Intents.default()
bot     = commands.Bot(intents=intents)
LOG_CHANNEL_ID = get_log_channel() or DEFAULT_LOG_CHANNEL_ID

def _ts() -> str:
    # Mooie UTC timestamp zonder microseconds
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

async def log_action(message: str):
    if not LOG_CHANNEL_ID:
        return
    try:
        channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"{_ts()} {message}")
    except Exception:
        pass

# ========= Persistent Views (decorator-style) =========
class UploadMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="📤 Upload File", style=ButtonStyle.primary, custom_id="upload_btn_v2")
    async def upload_button(self, _btn: Button, interaction: Interaction):
        # Open wizard (ephemeral)
        await interaction.response.send_message(
            embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
            view=UploadFileView(), ephemeral=True
        )

    @nextcord.ui.button(label="🗑️ Remove File", style=ButtonStyle.danger, custom_id="remove_btn_v2")
    async def remove_button(self, _btn: Button, interaction: Interaction):
        user_roles = {r.id for r in interaction.user.roles}
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & ALLOWED_ASSIGN_ROLES)
        ):
            return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may remove files.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
            view=RemoveFileView(), ephemeral=True
        )

class UploadFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        # dynamische category list
        cats = list_categories()[:25]
        self.cat_select = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats],
            min_values=1, max_values=1, custom_id="upload_cat_select_v2"
        )
        self.cat_select.callback = self.select_category
        self.add_item(self.cat_select)

    async def select_category(self, interaction: Interaction):
        self.category = self.cat_select.values[0]
        self.clear_items()
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        self.role_select = Select(
            placeholder="Step 2: Select clearance role…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1, max_values=1, custom_id="upload_role_select_v2"
        )
        self.role_select.callback = self.select_role
        self.add_item(self.role_select)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary, custom_id="upload_open_modal_v2")
        submit.callback = self.open_modal
        self.add_item(submit)

        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description=f"Category: **{self.category}**\nSelect a role and enter details…", color=0x00FFCC),
            view=self
        )

    async def select_role(self, interaction: Interaction):
        self.role_id = int(self.role_select.values[0])
        await interaction.response.send_message(f"Clearance role set to <@&{self.role_id}>.", ephemeral=True)

    async def open_modal(self, interaction: Interaction):
        await interaction.response.send_modal(UploadDetailsModal(self))

class UploadDetailsModal(Modal):
    def __init__(self, parent_view: UploadFileView):
        super().__init__(title="Archive Upload")
        self.parent_view = parent_view
        self.item = TextInput(label="File name (subfolders ok, ext optional: .json or .txt)")
        self.content = TextInput(label="File content (JSON or Text)", style=TextInputStyle.paragraph)
        self.add_item(self.item); self.add_item(self.content)

    async def callback(self, interaction: Interaction):
        item_rel = self.item.value.strip().lower().replace(" ", "_").strip("/")
        content  = self.content.value
        if getattr(self.parent_view, "role_id", None) is None:
            return await interaction.response.send_message("❌ Select a clearance role first.", ephemeral=True)
        try:
            create_dossier_file(self.parent_view.category, item_rel, content, prefer_txt_default=True)
        except FileExistsError:
            return await interaction.response.send_message("❌ File already exists.", ephemeral=True)

        base = _strip_ext(item_rel)
        grant_file_clearance(self.parent_view.category, base, self.parent_view.role_id)
        await interaction.response.send_message(
            f"✅ Uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{self.parent_view.role_id}>.",
            ephemeral=True
        )
        await log_action(f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{self.parent_view.role_id}>.")

class RemoveFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        cats = list_categories()[:25]
        self.cat_select = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats],
            min_values=1, max_values=1, custom_id="remove_cat_select_v2"
        )
        self.cat_select.callback = self.select_category
        self.add_item(self.cat_select)

    async def select_category(self, interaction: Interaction):
        self.category = self.cat_select.values[0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Remove File", description=f"Category: **{self.category}**\n(No files found)", color=0xFF5555),
                view=self
            )
        self.item_select = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="remove_item_select_v2"
        )
        self.item_select.callback = self.delete_item
        self.add_item(self.item_select)
        await interaction.response.edit_message(
            embed=Embed(title="Remove File", description=f"Category: **{self.category}**\nSelect an item…", color=0xFF5555),
            view=self
        )

    async def delete_item(self, interaction: Interaction):
        base = self.item_select.values[0]
        try:
            remove_dossier_file(self.category, base)
        except FileNotFoundError:
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ Deleted `{self.category}/{base}`.", ephemeral=True)
        await log_action(f"🗑 {interaction.user} deleted `{self.category}/{base}`.")

class CategorySelect(View):
    """Explorer view (persistent)"""
    def __init__(self):
        super().__init__(timeout=None)
        cats = list_categories()[:25]
        self.sel = Select(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats],
            min_values=1, max_values=1, custom_id="cat_select_v2"
        )
        self.sel.callback = self.on_category
        self.add_item(self.sel)

    def build_item_list_view(self, category: str):
        items = list_items_recursive(category)
        embed = Embed(
            title=f"Archive: {category.replace('_',' ').title()}",
            description=("Select an item…" if items else "_No files in this category._"),
            color=0x00FFCC
        )
        view = View(timeout=None)
        if items:
            sel_item = Select(
                placeholder="Select an item…",
                options=[SelectOption(label=i, value=i) for i in items[:25]],
                min_values=1, max_values=1, custom_id="cat_item_select_v2"
            )
            async def on_item(_sel, inter: Interaction):
                await send_item_embed(inter, category, sel_item.values[0])
            sel_item.callback = on_item
            view.add_item(sel_item)
        return embed, view

    async def on_category(self, interaction: Interaction):
        category = self.sel.values[0]
        embed, view = self.build_item_list_view(category)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# —— Item rendering —— 
async def send_item_embed(interaction: Interaction, category: str, item_rel_base: str):
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
        await log_action(f"🚫 {interaction.user} attempted to access `{category}/{item_rel_base}{ext}` without clearance.")
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
            if k == "summary":
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

    await interaction.response.edit_message(embed=rpt, view=None)

# ========= Message handler for uploads =========
async def handle_upload(message: nextcord.Message):
    category = message.content.strip().lower().replace(" ", "_")
    if not category:
        return await message.channel.send("❌ Add the category name in the message text.")
    if category not in list_categories():
        return await message.channel.send(f"❌ Unknown category `{category}`.")

    processed = False
    for att in message.attachments:
        if not att.filename.lower().endswith((".json", ".txt")):
            continue
        data = (await att.read()).decode("utf-8")
        item_rel = os.path.splitext(att.filename)[0] if att.filename.lower().endswith(".json") else att.filename
        try:
            create_dossier_file(category, item_rel, data, prefer_txt_default=True)
        except FileExistsError:
            await message.channel.send(f"⚠️ `{item_rel}` already exists.")
        else:
            await message.channel.send(f"✅ Added `{item_rel}` to `{category}`.")
            await log_action(f"⬆️ {message.author} uploaded `{category}/{item_rel}`.")
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

    # Persistent views registreren (moet vóór er interacties binnenkomen)
    bot.add_view(UploadMenuView())
    bot.add_view(CategorySelect())

    # Post menu’s
    main_ch = bot.get_channel(MENU_CHANNEL_ID)
    if main_ch:
        await main_ch.send(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=CategorySelect()
        )
    up_ch = bot.get_channel(UPLOAD_CHANNEL_ID)
    if up_ch:
        await up_ch.send(
            embed=Embed(
                title="Archive Uplink",
                description="Use the buttons below to **upload** a new dossier or **remove** an existing one.",
                color=0x00FFCC
            ),
            view=UploadMenuView()
        )

# ========= Slash commands =========
@bot.slash_command(name="uploadfile", description="Create a dossier and set its clearance", guild_ids=[GUILD_ID])
async def uploadfile_cmd(inter: Interaction):
    if inter.channel.id != UPLOAD_CHANNEL_ID:
        return await inter.response.send_message("⛔ Use this in the upload channel.", ephemeral=True)
    user_roles = {r.id for r in inter.user.roles}
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await inter.response.send_message("⛔ ARCHIVIST ONLY.", ephemeral=True)
    await inter.response.send_message(
        embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
        view=UploadFileView(), ephemeral=True
    )

@bot.slash_command(name="removefile", description="Delete a dossier file", guild_ids=[GUILD_ID])
async def removefile_cmd(inter: Interaction):
    if inter.channel.id != UPLOAD_CHANNEL_ID:
        return await inter.response.send_message("⛔ Use this in the upload channel.", ephemeral=True)
    user_roles = {r.id for r in inter.user.roles}
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await inter.response.send_message("⛔ ARCHIVIST ONLY.", ephemeral=True)
    await inter.response.send_message(
        embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
        view=RemoveFileView(), ephemeral=True
    )

@bot.slash_command(name="grantfileclearance", description="Grant clearance to a dossier", guild_ids=[GUILD_ID])
async def grantfileclearance_cmd(inter: Interaction):
    user_roles = {r.id for r in inter.user.roles}
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await inter.response.send_message("⛔ ARCHIVIST ONLY.", ephemeral=True)
    # Hergebruik upload wizard voor role picken ⇒ kort houden:
    await inter.response.send_message("Use the explorer to pick a file, then `/grantfileclearance` is automatic via the UI soon.", ephemeral=True)

@bot.slash_command(name="revokefileclearance", description="Revoke clearance", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(inter: Interaction):
    user_roles = {r.id for r in inter.user.roles}
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await inter.response.send_message("⛔ ARCHIVIST ONLY.", ephemeral=True)
    await inter.response.send_message("Use the explorer to manage revokes (coming next).", ephemeral=True)

@bot.slash_command(name="summonmenu", description="Resend the explorer menu", guild_ids=[GUILD_ID])
async def summonmenu_cmd(inter: Interaction):
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator):
        return await inter.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
    await inter.response.send_message(
        embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
        view=CategorySelect()
    )
    await log_action(f"📣 {inter.user} summoned the file explorer menu.")

@bot.slash_command(name="setlogchannel", description="Set the logging channel", guild_ids=[GUILD_ID])
async def setlogchannel_cmd(inter: Interaction, channel: nextcord.TextChannel):
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator):
        return await inter.response.send_message("⛔ Admin/Owner only.", ephemeral=True)
    global LOG_CHANNEL_ID
    set_log_channel(channel.id)
    LOG_CHANNEL_ID = channel.id
    await inter.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)
    await log_action(f"🛠 {inter.user} set the log channel to {channel.mention}.")

if __name__ == "__main__":
    bot.run(TOKEN)
