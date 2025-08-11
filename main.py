# main.py — Project SPECTRE (hybride LOCAL/DRIVE backend)
import os
import json
import datetime
import base64
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# Config / ENV
# ─────────────────────────────────────────────────────────────────────────────
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID"))
BACKEND         = os.getenv("FILE_BACKEND", "local").lower().strip()  # 'local' (default) of 'drive'

DESCRIPTION = (
    "Use `/createfile`, `/grantfileclearance` or `/revokefileclearance` to manage files.\n\n"
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

# ─────────────────────────────────────────────────────────────────────────────
# Backend-adapter
#  - LOCAL  : gebruikt jouw bestaande utils + DOSSIERS_DIR (backup-gedrag)
#  - DRIVE  : gebruikt Google Drive (drive_storage.py)
# Alle UI-code onderaan werkt tegen deze wrapper-API.
# ─────────────────────────────────────────────────────────────────────────────
if BACKEND == "local":
    from utils import (
        load_clearance,
        get_required_roles as _local_get_required_roles,
        list_categories as _local_list_categories,
        list_items as _local_list_items,
        create_dossier_file as _local_create_dossier_file,
        grant_file_clearance as _local_grant_file_clearance,
        revoke_file_clearance as _local_revoke_file_clearance,
        DOSSIERS_DIR,
    )

    def list_categories():
        return _local_list_categories()

    def list_items(category: str):
        return _local_list_items(category)

    def fetch_dossier(category: str, item: str) -> dict:
        path = os.path.join(DOSSIERS_DIR, category, f"{item}.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_required_roles(category: str, item: str):
        return _local_get_required_roles(category, item)

    def create_dossier_file(category: str, item: str, content: str):
        _local_create_dossier_file(category, item, content)

    def grant_file_clearance(category: str, item: str, role_id: int):
        _local_grant_file_clearance(category, item, role_id)

    def revoke_file_clearance(category: str, item: str, role_id: int):
        _local_revoke_file_clearance(category, item, role_id)

elif BACKEND == "drive":
    # Drive backend
    from drive_storage import (
        load_folder_map, refresh_folder_map, fetch_dossier_json,
        get_file_acl, add_role_to_acl, remove_role_from_acl,
        create_json_file, SCOPES
    )
    # OAuth helpers (optioneel /authlink)
    import aiohttp
    from aiohttp import web
    from urllib.parse import urlencode

    REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "https://project-spectre-production.up.railway.app/oauth2callback")

    def _maybe_b64_or_json(value: str):
        if not value: return None
        s = value.strip().strip('"').strip("'")
        try:
            padded = s + "=" * (-len(s) % 4)
            return json.loads(base64.b64decode(padded).decode("utf-8"))
        except Exception:
            pass
        try:
            return json.loads(s)
        except Exception:
            return None

    def _extract_client_from_json(creds_json: dict):
        node = (creds_json or {}).get("web") or {}
        return node.get("client_id"), node.get("client_secret")

    def _resolve_google_client():
        cid = os.getenv("GDRIVE_CLIENT_ID")
        csec = os.getenv("GDRIVE_CLIENT_SECRET")
        if cid and csec:
            return cid, csec
        data = _maybe_b64_or_json(os.getenv("GDRIVE_CREDS_BASE64")) or _maybe_b64_or_json(os.getenv("GDRIVE_CREDS"))
        if data:
            cid2, csec2 = _extract_client_from_json(data)
            if cid2 and csec2:
                return cid2, csec2
        return None, None

    def build_auth_url() -> str:
        cid, csec = _resolve_google_client()
        if not cid or not csec:
            return "❌ CLIENT_ID/SECRET ontbreken. Zet GDRIVE_CLIENT_ID/GDRIVE_CLIENT_SECRET of GDRIVE_CREDS(_BASE64)."
        params = {
            "client_id": cid,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    # ---- wrapper API ----
    def list_categories():
        return sorted(load_folder_map().keys())

    def list_items(category: str):
        fm = load_folder_map()
        return sorted(fm.get(category, {}).get("items", {}).keys())

    def _file_id(category: str, item: str) -> str:
        fm = load_folder_map()
        return fm[category]["items"][item]["id"]

    def fetch_dossier(category: str, item: str) -> dict:
        data, _ = fetch_dossier_json(_file_id(category, item))
        return data

    def get_required_roles(category: str, item: str):
        return set(get_file_acl(_file_id(category, item)))

    def create_dossier_file(category: str, item: str, content: str):
        create_json_file(category, item, content)

    def grant_file_clearance(category: str, item: str, role_id: int):
        add_role_to_acl(_file_id(category, item), role_id)

    def revoke_file_clearance(category: str, item: str, role_id: int):
        remove_role_from_acl(_file_id(category, item), role_id)

else:
    raise RuntimeError(f"Unknown FILE_BACKEND: {BACKEND}. Use 'local' or 'drive'.")

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(__file__), "actions.log")
LOG_CHANNEL_ID = None
try:
    from config import get_log_channel, set_log_channel
    LOG_CHANNEL_ID = get_log_channel()
except Exception:
    pass

async def log_action(message: str, bot=None):
    timestamp = datetime.datetime.utcnow().isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    if bot and LOG_CHANNEL_ID:
        ch = bot.get_channel(LOG_CHANNEL_ID)
        if ch:
            await ch.send(message)

# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────
class CategorySelect(Select):
    def __init__(self):
        super().__init__(
            placeholder="Select a category…",
            options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
            min_values=1, max_values=1
        )

    def build_item_list_view(self, category: str):
        items = list_items(category)
        embed = Embed(title=category.replace("_"," ").title(), description="Select an item…", color=0x3498DB)
        view = View(timeout=None)
        select_item = Select(
            placeholder="Select an item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i) for i in items],
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

        # lees dossier via backend
        try:
            data = fetch_dossier(category, item)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Fout bij laden dossier: `{e}`", ephemeral=True)

        required = set(get_required_roles(category, item))
        user_roles = {r.id for r in interaction.user.roles}
        if not (
            interaction.user.id == interaction.guild.owner_id
            or interaction.user.guild_permissions.administrator
            or (user_roles & required)
        ):
            await log_action(
                f"🚫 {interaction.user} attempted to access `{category}/{item}.json` without sufficient clearance."
            )
            return await interaction.response.send_message("⛔ You lack the required clearance for this file.", ephemeral=True)

        await log_action(f"📄 {interaction.user} accessed `{category}/{item}.json`.")

        # Build detail embed
        title = data.get("codename") or data.get("name") or item.replace("_", " ").title()
        rpt = Embed(title=title, color=0x3498DB)

        roles_needed = [f"<@&{str(r)}>" for r in required] if required else ["None (public)"]
        rpt.add_field(name="🔐 Required Clearance", value=", ".join(roles_needed), inline=False)

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

        # dropdown to pick another item + back
        items = list_items(category)
        select_another = Select(
            placeholder="Select another item…",
            options=[SelectOption(label=i.replace("_"," ").title(), value=i) for i in items],
            min_values=1, max_values=1
        )
        select_another.callback = self.on_item
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
        async def _refresh(interaction: nextcord.Interaction):
            # bij DRIVE actueel maken, bij LOCAL alleen UI verversen
            if BACKEND == "drive":
                try:
                    from drive_storage import refresh_folder_map
                    refresh_folder_map()
                except Exception as e:
                    await interaction.response.send_message(f"❌ Drive refresh failed: `{e}`", ephemeral=True)
                    return
            await interaction.response.edit_message(
                embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
                view=RootView()
            )
        refresh.callback = _refresh
        self.add_item(refresh)

# ─────────────────────────────────────────────────────────────────────────────
# Bot setup & Commands
# ─────────────────────────────────────────────────────────────────────────────
intents = nextcord.Intents.default()
bot     = commands.Bot(intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Project SPECTRE online as {bot.user} (backend={BACKEND})")
    channel = bot.get_channel(MENU_CHANNEL_ID)
    if channel:
        await channel.send(
            embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
            view=RootView()
        )

@bot.slash_command(name="createfile", description="Create a dossier JSON file", guild_ids=[GUILD_ID])
async def createfile_cmd(interaction: nextcord.Interaction, category: str, item: str, content: str):
    user_roles = {r.id for r in interaction.user.roles}
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may create files.", ephemeral=True)
    try:
        create_dossier_file(category, item, content)
    except FileExistsError:
        return await interaction.response.send_message("❌ File already exists.", ephemeral=True)
    await interaction.response.send_message(f"✅ Created `{category}/{item}.json`.", ephemeral=True)
    await log_action(f"📁 {interaction.user} created `{category}/{item}.json`.", bot)

@bot.slash_command(name="grantfileclearance", description="Grant a clearance role access to a dossier", guild_ids=[GUILD_ID])
async def grantfileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may grant clearance.", ephemeral=True)
    # wizard
    sel = Select(placeholder="Step 1: Select category…",
                 options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
                 min_values=1, max_values=1)
    v = View(timeout=None)
    v.add_item(sel)
    async def sel_cat(i: nextcord.Interaction):
        cat = i.data["values"][0]
        v.clear_items()
        sel2 = Select(placeholder="Step 2: Select item…",
                      options=[SelectOption(label=x.replace("_"," ").title(), value=x) for x in list_items(cat)],
                      min_values=1, max_values=1)
        v.add_item(sel2)
        async def sel_item(i2: nextcord.Interaction):
            it = i2.data["values"][0]
            v.clear_items()
            roles = [r for r in i2.guild.roles if r.id in ALLOWED_ASSIGN_ROLES]
            sel3 = Select(placeholder="Step 3: Select clearance role…",
                          options=[SelectOption(label=r.name, value=str(r.id)) for r in roles],
                          min_values=1, max_values=1)
            v.add_item(sel3)
            async def do_grant(i3: nextcord.Interaction):
                rid = int(i3.data["values"][0])
                grant_file_clearance(cat, it, rid)
                await i3.response.send_message(f"✅ Granted <@&{rid}> access to `{cat}/{it}.json`.", ephemeral=True)
                await log_action(f"🔓 {i3.user} granted <@&{rid}> access to `{cat}/{it}.json`.", bot)
            sel3.callback = do_grant
            await i2.response.edit_message(embed=Embed(title="Grant File Clearance",
                description=f"Category: **{cat}**\nItem: **{it}**\nSelect a role…"), view=v)
        sel2.callback = sel_item
        await i.response.edit_message(embed=Embed(title="Grant File Clearance",
            description=f"Category: **{cat}**\nSelect an item…"), view=v)
    sel.callback = sel_cat
    await interaction.response.send_message(embed=Embed(title="Grant File Clearance",
        description="Step 1: Select category…", color=0x00FFCC), view=v, ephemeral=True)

@bot.slash_command(name="revokefileclearance", description="Revoke a clearance role's access", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(interaction: nextcord.Interaction):
    user_roles = {r.id for r in interaction.user.roles}
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await interaction.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may revoke clearance.", ephemeral=True)
    sel = Select(placeholder="Step 1: Select category…",
                 options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in list_categories()],
                 min_values=1, max_values=1)
    v = View(timeout=None)
    v.add_item(sel)
    async def sel_cat(i: nextcord.Interaction):
        cat = i.data["values"][0]
        v.clear_items()
        sel2 = Select(placeholder="Step 2: Select item…",
                      options=[SelectOption(label=x.replace("_"," ").title(), value=x) for x in list_items(cat)],
                      min_values=1, max_values=1)
        v.add_item(sel2)
        async def sel_item(i2: nextcord.Interaction):
            it = i2.data["values"][0]
            v.clear_items()
            # roles that currently have access
            req = set(get_required_roles(cat, it))
            roles = [rid for rid in req if i2.guild.get_role(rid)]
            opts = [SelectOption(label=i2.guild.get_role(rid).name, value=str(rid)) for rid in roles] or \
                   [SelectOption(label="(none)", value="__none__", default=True)]
            sel3 = Select(placeholder="Step 3: Select role to revoke…", options=opts, min_values=1, max_values=1)
            v.add_item(sel3)
            async def do_revoke(i3: nextcord.Interaction):
                rid = int(i3.data["values"][0])
                revoke_file_clearance(cat, it, rid)
                await i3.response.send_message(f"✅ Revoked <@&{rid}> from `{cat}/{it}.json`.", ephemeral=True)
                await log_action(f"🔒 {i3.user} revoked <@&{rid}> from `{cat}/{it}.json`.", bot)
            sel3.callback = do_revoke
            await i2.response.edit_message(embed=Embed(title="Revoke File Clearance",
                description=f"Category: **{cat}**\nItem: **{it}**\nSelect a role…", color=0xFF5555), view=v)
        sel2.callback = sel_item
        await i.response.edit_message(embed=Embed(title="Revoke File Clearance",
            description=f"Category: **{cat}**\nSelect an item…"), view=v)
    sel.callback = sel_cat
    await interaction.response.send_message(embed=Embed(title="Revoke File Clearance",
        description="Step 1: Select category…", color=0xFF5555), view=v, ephemeral=True)

@bot.slash_command(name="summonmenu", description="Resend the file explorer menu", guild_ids=[GUILD_ID])
async def summonmenu_cmd(interaction: nextcord.Interaction):
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("⛔ Only Admin or Owner may summon the menu.", ephemeral=True)
    await interaction.response.send_message(
        embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
        view=RootView()
    )

@bot.slash_command(name="setlogchannel", description="Set the logging channel", guild_ids=[GUILD_ID])
async def setlogchannel_cmd(interaction: nextcord.Interaction, channel: nextcord.TextChannel):
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("⛔ Only Admin or Owner may set the log channel.", ephemeral=True)
    global LOG_CHANNEL_ID
    from config import set_log_channel
    set_log_channel(channel.id)
    LOG_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)
    await log_action(f"🛠 {interaction.user} set the log channel to {channel.mention}.", bot)

# optional: only in DRIVE backend
if BACKEND == "drive":
    @bot.slash_command(name="authlink", description="Genereer Google OAuth link (Drive)", guild_ids=[GUILD_ID])
    async def authlink_cmd(interaction: nextcord.Interaction):
        url = build_auth_url()
        await interaction.response.send_message(url, ephemeral=True)

bot.run(TOKEN)
