import os
import json
import datetime
import traceback
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button, Modal, TextInput
from dotenv import load_dotenv

# ====== External helpers (unchanged) ======
from config import get_log_channel, set_log_channel
from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir, presigned_url
)

# ========= ENV =========
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1402017286432227449"))

ROOT_PREFIX = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")

# ========= Utils =========
def ts() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()

def _cat_prefix(category: str) -> str:
    return f"{ROOT_PREFIX}/{category}".replace("//", "/").strip("/")

def _strip_ext(name: str) -> str:
    low = name.lower()
    for ext in (".json", ".txt"):
        if low.endswith(ext):
            return name[: -len(ext)]
    return name

def _split_dir_file(rel: str):
    rel = rel.strip().strip("/")
    if "/" in rel:
        d, f = rel.rsplit("/", 1)
        return d, f
    return "", rel

def _list_files_in(path_prefix: str):
    try:
        return list_dir(path_prefix)
    except FileNotFoundError:
        return [], []
    except Exception:
        return [], []

def _find_existing_item_key(category: str, item_rel_base: str):
    base_rel = item_rel_base.strip().strip("/")
    subdir, fname = _split_dir_file(base_rel)
    dir_prefix = f"{_cat_prefix(category)}/{subdir}".strip("/").replace("//", "/")
    dirs, files = _list_files_in(dir_prefix)

    candidates = [f"{fname}.json", f"{fname}.txt", fname]
    file_names = {n.lower(): n for (n, _sz) in files}
    for cand in candidates:
        low = cand.lower()
        if low in file_names:
            real = file_names[low]
            key = f"{dir_prefix}/{real}".replace("//", "/")
            ext = ".json" if real.lower().endswith(".json") else ".txt" if real.lower().endswith(".txt") else ""
            return key, ext or (".json" if real.endswith(".json") else ".txt")
    return None

# ========= ACL in Spaces =========
ACL_KEY = f"{ROOT_PREFIX}/acl/clearance.json".replace("//", "/")

def load_clearance() -> dict:
    try:
        return read_json(ACL_KEY)
    except FileNotFoundError:
        return {}
    except Exception:
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
    dirs, _files = _list_files_in(ROOT_PREFIX)
    cats = [d[:-1] for d in dirs if d.endswith("/")]
    if not cats:
        cats = ["missions", "personnel", "intelligence"]
    return sorted(set(cats))

def list_items_recursive(category: str, max_items: int = 3000) -> list[str]:
    root = _cat_prefix(category)
    items_base = set()
    stack = [root]
    seen = set()
    while stack and len(items_base) < max_items:
        base = stack.pop()
        if base in seen:
            continue
        seen.add(base)

        dirs, files = _list_files_in(base)
        for name, _size in files:
            if name.lower().endswith((".json", ".txt")):
                rel = f"{base}/{name}".replace("//", "/")
                rel_from_cat = rel[len(root):].strip("/").replace("\\", "/")
                items_base.add(_strip_ext(rel_from_cat))
        for d in dirs:
            stack.append(f"{base}/{d.strip('/')}".replace("//", "/"))
    return sorted(items_base)

# ========= Create/Remove =========
def create_dossier_file(category: str, item_rel_input: str, content: str, prefer_txt_default: bool = True) -> str:
    item_rel_input = item_rel_input.strip().strip("/")
    has_ext = item_rel_input.lower().endswith((".json", ".txt"))
    if not has_ext:
        item_base = item_rel_input
        target_name = item_base + (".txt" if prefer_txt_default else ".json")
    else:
        item_base = _strip_ext(item_rel_input)
        target_name = item_rel_input

    if _find_existing_item_key(category, item_base):
        raise FileExistsError

    subdir, _fname = _split_dir_file(item_base)
    dir_prefix = f"{_cat_prefix(category)}/{subdir}".strip("/").replace("//", "/")
    ensure_dir(dir_prefix)

    key = f"{dir_prefix}/{target_name}".replace("//", "/")
    try:
        data = json.loads(content)
        if key.lower().endswith(".json"):
            save_json(key, data)
        else:
            save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        if not key.lower().endswith((".json", ".txt")):
            key = key + ".txt"
        save_text(key, content)
    return key

def remove_dossier_file(category: str, item_rel_base: str) -> None:
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, _ = found
    delete_file(key)

# —— RP Intro ——  
INTRO_TITLE = "Project SPECTRE File Explorer"
INTRO_DESC = (
    "Welcome, Operative.\n"
    "Access the Directorate’s secure archive. Navigation and actions are monitored.\n\n"
    "**Commands**\n"
    "• `/uploadfile` — Only level 5 and above\n"
    "• `/removefile` — ARCHIVIST ONLY\n"
    "• `/grantfileclearance` / `/revokefileclearance` — Manage clearances - level 5 only\n\n"
    "**Files**: `.json` *or* `.txt`."
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

# ========= Bot =========
intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(intents=intents)
LOG_CHANNEL_ID = get_log_channel() or DEFAULT_LOG_CHANNEL_ID
LOG_FILE = os.path.join(os.path.dirname(__file__), "actions.log")

async def log_action(message: str):
    line = f"{ts()} {message}"
    try:
        if LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
            if channel:
                await channel.send(message)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

# ========= Views =========
class CategorySelect(Select):
    def __init__(self):
        cats = list_categories()
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats[:25]],
            min_values=1, max_values=1,
            custom_id="cat_select_v2"
        )
        self.category = None

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
                custom_id="cat_item_select_v2"
            )
            select_item.callback = self.on_item
            view.add_item(select_item)
        return embed, view

    async def callback(self, interaction: nextcord.Interaction):
        self.category = self.values[0]
        embed, view = self.build_item_list_view(self.category)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_item(self, interaction: nextcord.Interaction):
        category = self.category or list_categories()[0]
        item_rel_base = interaction.data["values"][0]

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

        rpt = Embed(
            title=f"{item_rel_base.split('/')[-1].replace('_',' ').title()} — {category.title()}",
            color=0x00FFCC
        )
        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name="🔐 Required Clearance", value=", ".join(roles_needed), inline=False)

        try:
            data = read_json(key)
            if isinstance(data, dict):
                if "summary" in data and data["summary"]:
                    rpt.description = str(data["summary"])
                for k, v in data.items():
                    if k == "summary":
                        continue
                    if k == "pdf_link":
                        rpt.add_field(name="📎 Attached File", value=f"[Open]({v})", inline=False)
                    else:
                        rpt.add_field(name=k.replace("_"," ").title(), value=str(v), inline=False)
            else:
                raise ValueError("JSON root not dict")
        except Exception:
            try:
                blob = read_text(key)
            except Exception:
                return await interaction.response.send_message("❌ Could not read file.", ephemeral=True)
            show = blob if len(blob) <= 1800 else blob[:1800] + "\n…(truncated)"
            rpt.add_field(name="Contents", value=f"```txt\n{show}\n```", inline=False)

        items = list_items_recursive(category)
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1,
            custom_id="cat_item_select_again_v2"
        )
        select_another.callback = self.on_item

        back = Button(label="← Back to list", style=ButtonStyle.secondary, custom_id="back_to_list_v2")
        async def on_back(inter2: nextcord.Interaction):
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
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary, custom_id="refresh_root_v2")
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
        # <= 45 chars labels
        self.item = TextInput(
            label="File path",
            placeholder="e.g. intelligence/hoot_alliance (ext optional)",
            min_length=1, max_length=4000
        )
        self.content = TextInput(
            label="Content",
            placeholder="Paste JSON or plain text",
            style=TextInputStyle.paragraph,
            min_length=1, max_length=4000
        )
        self.add_item(self.item)
        self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            role_id = getattr(self.parent_view, "role_id", None)
            if role_id is None:
                return await interaction.response.send_message("❌ Select a clearance role first.", ephemeral=True)

            item_rel = self.item.value.strip().lower().replace(" ", "_").strip("/")
            content = self.content.value

            key = create_dossier_file(self.parent_view.category, item_rel, content, prefer_txt_default=True)
            item_base = _strip_ext(item_rel)
            grant_file_clearance(self.parent_view.category, item_base, role_id)

            await interaction.response.send_message(
                f"✅ Uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>.",
                ephemeral=True,
            )
            await log_action(
                f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{item_rel}` "
                f"with clearance <@&{role_id}>."
            )
        except FileExistsError:
            await interaction.response.send_message("❌ File already exists.", ephemeral=True)
        except Exception as e:
            await log_action(f"❗ Upload modal error: {e}\n```{traceback.format_exc()[:1800]}```")
            try:
                await interaction.response.send_message("❌ Upload failed (see log).", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Upload failed (see log).", ephemeral=True)

class UploadFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        self.role_id = None

        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_", " ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1,
            custom_id="upload_cat_select_v2"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()

        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(title="Upload File", description="No assignable clearance roles configured.", color=0xFF5555),
                view=self,
            )

        sel_role = Select(
            placeholder="Step 2: Select clearance role…",
            options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
            min_values=1, max_values=1,
            custom_id="upload_role_select_v2"
        )
        sel_role.callback = self.select_role
        self.add_item(sel_role)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary, custom_id="upload_open_modal_v2")
        async def open_modal(interaction2: nextcord.Interaction):
            try:
                await interaction2.response.send_modal(UploadDetailsModal(self))
            except Exception as e:
                await log_action(f"❗ open_modal error: {e}\n```{traceback.format_exc()[:1800]}```")
                try:
                    await interaction2.response.send_message("❌ Could not open modal (see log).", ephemeral=True)
                except Exception:
                    await interaction2.followup.send("❌ Could not open modal (see log).", ephemeral=True)
        submit.callback = open_modal
        self.add_item(submit)

        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description=f"Category: **{self.category}**\nSelect a role and enter details…", color=0x00FFCC),
            view=self,
        )

    async def select_role(self, interaction: nextcord.Interaction):
        self.role_id = int(interaction.data["values"][0])
        await interaction.response.send_message(f"Clearance role set to <@&{self.role_id}>.", ephemeral=True)

class RemoveFileView(View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_", " ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1,
            custom_id="remove_cat_select_v2"
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
            custom_id="remove_item_select_v2"
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
        btn = Button(label="📤 Upload File", style=ButtonStyle.primary, custom_id="upload_btn_v2")
        btn.callback = self.start_wizard
        self.add_item(btn)
        rm_btn = Button(label="🗑️ Remove File", style=ButtonStyle.danger, custom_id="remove_btn_v2")
        rm_btn.callback = self.start_remove
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

# ========= Commands & events =========
async def handle_upload(message: nextcord.Message):
    category = (message.content or "").strip().lower().replace(" ", "_")
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
        data = (await attachment.read()).decode("utf-8", errors="replace")
        is_json = attachment.filename.lower().endswith(".json")
        item_rel_input = os.path.splitext(attachment.filename)[0] if is_json else attachment.filename
        try:
            key = create_dossier_file(category, item_rel_input, data, prefer_txt_default=not is_json)
        except FileExistsError:
            await message.channel.send(f"⚠️ `{item_rel_input}` already exists.")
        else:
            await message.channel.send(f"✅ Added `{item_rel_input}` to `{category}`.")
            await log_action(f"⬆️ {message.author} uploaded `{category}/{item_rel_input}` → `{key}`.")
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
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence", "acl"):
        ensure_dir(f"{ROOT_PREFIX}/{cat}")

    bot.add_view(RootView())
    bot.add_view(UploadMenuView())

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
    await interaction.response.send_message("ℹ️ Grant UI not implemented in this build.", ephemeral=True)

@bot.slash_command(name="revokefileclearance", description="Revoke a dossier clearance", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may revoke.", ephemeral=True)
    await interaction.response.send_message("ℹ️ Revoke UI not implemented in this build.", ephemeral=True)

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
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(TOKEN)
