import os
import json
import datetime
import traceback
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle, TextInputStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button, Modal, TextInput
from dotenv import load_dotenv

# ==== External helpers (project-local) ====
from config import get_log_channel, set_log_channel
from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir
)

# ========= ENV / CONST =========
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID", "1402017286432227449"))
ROOT_PREFIX     = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")

# Roles (pas aan naar wens)
LEVEL1_ROLE_ID     = 1365097430713896992
LEVEL2_ROLE_ID     = 1402635734506016861
LEVEL3_ROLE_ID     = 1365096533069926460
LEVEL4_ROLE_ID     = 1365094103578181765
LEVEL5_ROLE_ID     = 1365093753035161712
CLASSIFIED_ROLE_ID = 1365093656859512863

ALLOWED_ASSIGN_ROLES = {
    LEVEL1_ROLE_ID, LEVEL2_ROLE_ID, LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID, LEVEL5_ROLE_ID, CLASSIFIED_ROLE_ID
}

UPLOAD_CHANNEL_ID      = 1405751160819683348
DEFAULT_LOG_CHANNEL_ID = 1402306158492123318

INTRO_TITLE = "Project SPECTRE File Explorer"
INTRO_DESC  = (
    "Welcome, Operative.\n"
    "Use the menus below to browse files. Actions are monitored. Do remember some file's need to be opened in google documents for full access.\n\n"
    "**Archivist Console** (ephemeral): `/archivist`\n"
    "• Upload / Remove files\n"
    "• Grant / Revoke file clearances\n\n"
    "**Files**: `.json` or `.txt`"
)

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
    """Directory-based existence check; returns (key, ext) or None."""
    base_rel = item_rel_base.strip().strip("/")
    subdir, fname = _split_dir_file(base_rel)
    dir_prefix = f"{_cat_prefix(category)}/{subdir}".strip("/").replace("//", "/")
    _dirs, files = _list_files_in(dir_prefix)
    candidates = [f"{fname}.json", f"{fname}.txt", fname]
    file_names = {n.lower(): n for (n, _sz) in files}
    for cand in candidates:
        low = cand.lower()
        if low in file_names:
            real = file_names[low]
            key = f"{dir_prefix}/{real}".replace("//", "/")
            ext = ".json" if real.lower().endswith(".json") else ".txt" if real.lower().endswith(".txt") else ""
            return key, (ext or ".txt")
    return None

# ========= ACL (stored in Spaces) =========
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

def get_required_roles(category: str, item_rel_base: str) -> set[int]:
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

# ========= Listing / IO =========
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

def create_dossier_file(category: str, item_rel_input: str, content: str, prefer_txt_default: bool = True) -> str:
    item_rel_input = item_rel_input.strip().strip("/")
    has_ext = item_rel_input.lower().endswith((".json", ".txt"))
    if not has_ext:
        item_base = item_rel_input
        target_name = item_base + (".txt" if prefer_txt_default else ".json")
    else:
        item_base    = _strip_ext(item_rel_input)
        target_name  = item_rel_input
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
            key += ".txt"
        save_text(key, content)
    return key

def remove_dossier_file(category: str, item_rel_base: str) -> None:
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, _ = found
    delete_file(key)

# ========= Bot / Logging =========
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

# ========= Explorer Views =========
class CategorySelect(Select):
    def __init__(self):
        cats = list_categories()
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats[:25]],
            min_values=1, max_values=1,
            custom_id="cat_select_v3"
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
                custom_id="cat_item_select_v3"
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
            custom_id="cat_item_select_again_v3"
        )
        select_another.callback = self.on_item

        back = Button(label="← Back to list", style=ButtonStyle.secondary, custom_id="back_to_list_v3")
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
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary, custom_id="refresh_root_v3")
        refresh.callback = self.refresh_menu
        self.add_item(refresh)

    async def refresh_menu(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView()
        )

# ========= Archivist Console =========
def _is_archivist(user: nextcord.Member) -> bool:
    user_roles = {r.id for r in user.roles}
    return (
        user.id == user.guild.owner_id
        or user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    )

class UploadDetailsModal(Modal):
    def __init__(self, parent_view: "UploadFileView"):
        super().__init__(title="Archive Upload")
        self.parent_view = parent_view
        self.item = TextInput(
            label="File path",
            placeholder="e.g. intel/hoot_alliance (ext optional)",
            min_length=1, max_length=4000
        )
        self.content = TextInput(
            label="Content",
            placeholder="Paste JSON or plain text",
            style=TextInputStyle.paragraph,
            min_length=1, max_length=4000
        )
        self.add_item(self.item); self.add_item(self.content)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            role_id = getattr(self.parent_view, "role_id", None)
            if role_id is None:
                return await interaction.response.send_message("❌ Select a clearance role first.", ephemeral=True)
            item_rel = self.item.value.strip().lower().replace(" ", "_").strip("/")
            content  = self.content.value
            key = create_dossier_file(self.parent_view.category, item_rel, content, prefer_txt_default=True)
            item_base = _strip_ext(item_rel)
            grant_file_clearance(self.parent_view.category, item_base, role_id)
            await interaction.response.send_message(
                f"✅ Uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>.",
                ephemeral=True,
            )
            await log_action(
                f"⬆️ {interaction.user} uploaded `{self.parent_view.category}/{item_rel}` with clearance <@&{role_id}>."
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
        self.role_id  = None
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="upload_cat_v3"
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
            min_values=1, max_values=1, custom_id="upload_role_v3"
        )
        sel_role.callback = self.select_role
        self.add_item(sel_role)

        submit = Button(label="Step 3: Enter file details", style=ButtonStyle.primary, custom_id="upload_modal_v3")
        async def open_modal(inter2: nextcord.Interaction):
            try: await inter2.response.send_modal(UploadDetailsModal(self))
            except Exception as e:
                await log_action(f"❗ open_modal error: {e}\n```{traceback.format_exc()[:1800]}```")
                try:    await inter2.response.send_message("❌ Could not open modal (see log).", ephemeral=True)
                except: await inter2.followup.send("❌ Could not open modal (see log).", ephemeral=True)
        submit.callback = open_modal
        self.add_item(submit)

        await interaction.response.edit_message(
            embed=Embed(title="Upload File", description=f"Category: **{self.category}**\nSelect role and enter details…", color=0x00FFCC),
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
            min_values=1, max_values=1, custom_id="remove_cat_v3"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Remove File", description=f"Category: **{self.category}**\n(No files found)", color=0xFF5555), view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="remove_item_v3"
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
            return await interaction.response.send_message("❌ File not found.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ Deleted `{self.category}/{item_rel_base}`.", ephemeral=True)
        await log_action(f"🗑 {interaction.user} deleted `{self.category}/{item_rel_base}`.")

# --- Grant / Revoke Views ---
class GrantClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        self.item     = None
        self.roles_to_add: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="grant_cat_v1"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Grant Clearance", description=f"Category: **{self.category}**\n(No files found)", color=0x00FFCC), view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="grant_item_v1"
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Grant Clearance", description=f"Category: **{self.category}**\nSelect an item…", color=0x00FFCC),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        # Show current + choose roles to add
        current = get_required_roles(self.category, self.item)
        roles = [r for r in interaction.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
        if not roles:
            return await interaction.response.edit_message(
                embed=Embed(title="Grant Clearance", description="No assignable roles configured.", color=0xFFAA00), view=self
            )
        sel_roles = Select(
            placeholder="Step 3: Select roles to GRANT…",
            options=[SelectOption(label=r.name, value=str(r.id), default=(r.id in current)) for r in roles],
            min_values=1, max_values=min(5, len(roles)), custom_id="grant_roles_v1"
        )
        async def choose_roles(inter2: nextcord.Interaction):
            self.roles_to_add = [int(v) for v in inter2.data["values"]]
            await inter2.response.send_message("Roles selected.", ephemeral=True)
        sel_roles.callback = choose_roles
        self.add_item(sel_roles)

        apply_btn = Button(label="Apply Grants", style=ButtonStyle.success, custom_id="apply_grant_v1")
        async def do_grant(inter2: nextcord.Interaction):
            if not self.roles_to_add:
                return await inter2.response.send_message("Select at least one role.", ephemeral=True)
            for rid in self.roles_to_add:
                grant_file_clearance(self.category, self.item, rid)
            await inter2.response.send_message(
                f"✅ Granted: {', '.join(f'<@&{r}>' for r in self.roles_to_add)} → `{self.category}/{self.item}`",
                ephemeral=True
            )
            await log_action(f"🟩 {inter2.user} granted {self.roles_to_add} on `{self.category}/{self.item}`.")
        apply_btn.callback = do_grant
        self.add_item(apply_btn)

        cancel = Button(label="← Back", style=ButtonStyle.secondary, custom_id="grant_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            await self.__init__()  # reset
            await inter2.response.edit_message(
                embed=Embed(title="Grant Clearance", description="Step 1: Select category…", color=0x00FFCC),
                view=self
            )
        cancel.callback = go_back
        self.add_item(cancel)

        # Show current state
        curr_names = [f"<@&{r}>" for r in current] if current else ["None (public)"]
        embed = Embed(title="Grant Clearance", color=0x00FFCC)
        embed.add_field(name="File", value=f"`{self.category}/{self.item}`", inline=False)
        embed.add_field(name="Current clearance", value=", ".join(curr_names), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

class RevokeClearanceView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.category = None
        self.item     = None
        self.roles_to_remove: list[int] = []
        sel = Select(
            placeholder="Step 1: Select category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1, custom_id="revoke_cat_v1"
        )
        sel.callback = self.select_category
        self.add_item(sel)

    async def select_category(self, interaction: nextcord.Interaction):
        self.category = interaction.data["values"][0]
        self.clear_items()
        items = list_items_recursive(self.category)
        if not items:
            return await interaction.response.edit_message(
                embed=Embed(title="Revoke Clearance", description=f"Category: **{self.category}**\n(No files found)", color=0xFF5555), view=self
            )
        sel_item = Select(
            placeholder="Step 2: Select item…",
            options=[SelectOption(label=i, value=i) for i in items[:25]],
            min_values=1, max_values=1, custom_id="revoke_item_v1"
        )
        sel_item.callback = self.select_item
        self.add_item(sel_item)
        await interaction.response.edit_message(
            embed=Embed(title="Revoke Clearance", description=f"Category: **{self.category}**\nSelect an item…", color=0xFF5555),
            view=self,
        )

    async def select_item(self, interaction: nextcord.Interaction):
        self.item = interaction.data["values"][0]
        self.clear_items()

        current = list(get_required_roles(self.category, self.item))
        if not current:
            return await interaction.response.edit_message(
                embed=Embed(title="Revoke Clearance", description="File is public; nothing to revoke.", color=0xFFAA00), view=self
            )
        # only show roles that are currently set
        options = []
        for rid in current:
            role = nextcord.utils.get(interaction.guild.roles, id=rid)
            label = role.name if role else str(rid)
            options.append(SelectOption(label=label, value=str(rid)))
        sel_roles = Select(
            placeholder="Step 3: Select roles to REVOKE…",
            options=options, min_values=1, max_values=min(5, len(options)), custom_id="revoke_roles_v1"
        )
        async def choose_roles(inter2: nextcord.Interaction):
            self.roles_to_remove = [int(v) for v in inter2.data["values"]]
            await inter2.response.send_message("Roles selected.", ephemeral=True)
        sel_roles.callback = choose_roles
        self.add_item(sel_roles)

        apply_btn = Button(label="Apply Revokes", style=ButtonStyle.danger, custom_id="apply_revoke_v1")
        async def do_revoke(inter2: nextcord.Interaction):
            if not self.roles_to_remove:
                return await inter2.response.send_message("Select at least one role.", ephemeral=True)
            for rid in self.roles_to_remove:
                revoke_file_clearance(self.category, self.item, rid)
            await inter2.response.send_message(
                f"✅ Revoked: {', '.join(f'<@&{r}>' for r in self.roles_to_remove)} ← `{self.category}/{self.item}`",
                ephemeral=True
            )
            await log_action(f"🟥 {inter2.user} revoked {self.roles_to_remove} on `{self.category}/{self.item}`.")
        apply_btn.callback = do_revoke
        self.add_item(apply_btn)

        cancel = Button(label="← Back", style=ButtonStyle.secondary, custom_id="revoke_back_v1")
        async def go_back(inter2: nextcord.Interaction):
            await self.__init__()  # reset
            await inter2.response.edit_message(
                embed=Embed(title="Revoke Clearance", description="Step 1: Select category…", color=0xFF5555),
                view=self
            )
        cancel.callback = go_back
        self.add_item(cancel)

        curr_names = [f"<@&{r}>" for r in current]
        embed = Embed(title="Revoke Clearance", color=0xFF5555)
        embed.add_field(name="File", value=f"`{self.category}/{self.item}`", inline=False)
        embed.add_field(name="Current clearance", value=", ".join(curr_names), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

class ArchivistConsoleView(View):
    """One-stop console for archivists; ephemeral."""
    def __init__(self, user: nextcord.Member):
        super().__init__(timeout=None)
        self.user = user

        self.btn_upload = Button(label="📤 Upload File", style=ButtonStyle.primary)
        self.btn_upload.callback = self.open_upload
        self.add_item(self.btn_upload)

        self.btn_remove = Button(label="🗑 Remove File", style=ButtonStyle.danger)
        self.btn_remove.callback = self.open_remove
        self.add_item(self.btn_remove)

        self.btn_grant  = Button(label="🟩 Grant Clearance", style=ButtonStyle.success)
        self.btn_grant.callback = self.open_grant
        self.add_item(self.btn_grant)

        self.btn_revoke = Button(label="🟥 Revoke Clearance", style=ButtonStyle.danger)
        self.btn_revoke.callback = self.open_revoke
        self.add_item(self.btn_revoke)

        self.btn_refresh = Button(label="🔄 Refresh", style=ButtonStyle.secondary)
        self.btn_refresh.callback = self.refresh
        self.add_item(self.btn_refresh)

    async def open_upload(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Upload File", description="Step 1: Select category…", color=0x00FFCC),
            view=UploadFileView(), ephemeral=True
        )

    async def open_remove(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Remove File", description="Step 1: Select category…", color=0xFF5555),
            view=RemoveFileView(), ephemeral=True
        )

    async def open_grant(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Grant Clearance", description="Step 1: Select category…", color=0x00FFCC),
            view=GrantClearanceView(), ephemeral=True
        )

    async def open_revoke(self, interaction: nextcord.Interaction):
        if not _is_archivist(interaction.user):
            return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
        await interaction.response.send_message(
            embed=Embed(title="Revoke Clearance", description="Step 1: Select category…", color=0xFF5555),
            view=RevokeClearanceView(), ephemeral=True
        )

    async def refresh(self, interaction: nextcord.Interaction):
        await interaction.response.edit_message(
            embed=Embed(
                title="Archivist Console",
                description="Select an action below.",
                color=0x00FFCC
            ),
            view=ArchivistConsoleView(interaction.user)
        )

# ========= Upload via channel message (attachments) =========
async def handle_upload(message: nextcord.Message):
    category = (message.content or "").strip().lower().replace(" ", "_")
    if not category:
        return await message.channel.send("❌ Add the category name in the message text.")
    if category not in list_categories():
        return await message.channel.send(f"❌ Unknown category `{category}`.")

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

# ========= Commands / Startup =========
@bot.event
async def on_ready():
    print(f"✅ SPECTRE online as {bot.user}")
    ensure_dir(ROOT_PREFIX)
    for cat in ("missions", "personnel", "intelligence", "acl"):
        ensure_dir(f"{ROOT_PREFIX}/{cat}")

    bot.add_view(RootView())  # persistent
    main_ch = bot.get_channel(MENU_CHANNEL_ID)
    if main_ch:
        await main_ch.send(
            embed=Embed(title=INTRO_TITLE, description=INTRO_DESC, color=0x00FFCC),
            view=RootView()
        )

    # Friendly hint in upload channel
    up_ch = bot.get_channel(UPLOAD_CHANNEL_ID)
    if up_ch:
        await up_ch.send(
            embed=Embed(
                title="Archive Uplink",
                description="Use `/archivist` for the full console or post attachments here with the category name as the message.",
                color=0x00FFCC
            )
        )

@bot.slash_command(name="archivist", description="Open the Archivist Console", guild_ids=[GUILD_ID])
async def archivist_cmd(interaction: nextcord.Interaction):
    if not _is_archivist(interaction.user):
        return await interaction.response.send_message("⛔ Archivist only.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Archivist Console", description="Select an action below.", color=0x00FFCC),
        view=ArchivistConsoleView(interaction.user), ephemeral=True
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
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(TOKEN)
