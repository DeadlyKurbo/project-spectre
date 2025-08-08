import os
import aiohttp
from aiohttp import web
import asyncio
import json
import datetime
import tempfile
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button
from dotenv import load_dotenv
# —— File Explorer UI ——
import math
from nextcord.errors import HTTPException

def _humanize_key(k: str) -> str:
    return k.replace("_", " ").title()

def _fmt_value(v) -> str:
    """Format JSON values for readable embeds (bullets for lists, K:V for dicts)."""
    if isinstance(v, list):
        if not v:
            return "_(empty list)_"
        return "\n".join(f"• {x}" for x in v)
    if isinstance(v, dict):
        if not v:
            return "_(empty object)_"
        return "\n".join(f"• {k}: {v}" for k, v in v.items())
    return str(v)

def _build_dossier_embed(category: str, item: str, data: dict) -> nextcord.Embed:
    title = f"{category} / {item}".replace("_", " ").title()
    e = nextcord.Embed(title=title, color=0x00FFCC)

    # Add fields (truncate overly long values to fit Discord limits)
    for k, v in data.items():
        val = _fmt_value(v)
        # Field hard limit is 1024 chars
        if len(val) > 1024:
            val = val[:1010] + "…"
        e.add_field(name=_humanize_key(k), value=val or "—", inline=False)

    return e

class ItemSelect(Select):
    def __init__(self, category: str):
        self.category = category
        folder_map = load_folder_map()
        items = folder_map.get(category, {}).get("items", {})
        options = [
            nextcord.SelectOption(
                label=key.replace("_", " ").title(), value=key
            )
            for key in sorted(items.keys())
        ] or [nextcord.SelectOption(label="(no items)", value="__none__", default=True)]
        super().__init__(placeholder="Select an item…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: nextcord.Interaction):
        if self.values[0] == "__none__":
            return await interaction.response.send_message("No items in this category.", ephemeral=True)

        item = self.values[0]
        folder_map = load_folder_map()
        file_id = folder_map[self.category]["items"][item]["id"]

        # Fetch dossier JSON from Drive
        try:
            data, pretty = fetch_dossier_json(file_id)
        except Exception as e:
            return await interaction.response.send_message(
                f"❌ Fout bij laden dossier: `{e}`", ephemeral=True
            )

        # Try pretty Embed first; fall back to .txt if it fails Discord limits
        embed = _build_dossier_embed(self.category, item, data)
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except HTTPException as ex:
            # If the embed is too big (code 50035 / invalid form body), send a txt file instead.
            if "50035" in str(ex) or "Invalid Form Body" in str(ex):
                # Build a readable plain-text version
                lines = [f"{self.category} / {item}".replace("_", " ").title(), "=" * 60, ""]
                for k, v in data.items():
                    lines.append(f"{_humanize_key(k)}:")
                    lines.append(_fmt_value(v))
                    lines.append("")
                text = "\n".join(lines)
                fname = f"{self.category}_{item}.txt".replace(" ", "_")
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(text)
                await interaction.response.send_message(
                    content="📎 Dossier is te lang voor een embed — zie bijgevoegde .txt",
                    file=nextcord.File(fname),
                    ephemeral=True,
                )
                os.remove(fname)
            else:
                # Unknown error: surface it
                await interaction.response.send_message(
                    f"❌ Fout bij weergeven: `{ex}`", ephemeral=True
                )

class CategorySelect(Select):
    def __init__(self):
        try:
            folder_map = load_folder_map()
            cat_names = sorted(folder_map.keys())
        except Exception as e:
            print(f"[ERROR] Failed to load folder_map: {e}")
            cat_names = []

        options = (
            [nextcord.SelectOption(label=n.replace("_"," ").title(), value=n) for n in cat_names]
            if cat_names else
            [nextcord.SelectOption(label="No categories available", value="__none__", default=True)]
        )

        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: nextcord.Interaction):
        if self.values[0] == "__none__":
            return await interaction.response.send_message("No categories available.", ephemeral=True)

        category = self.values[0]
        # Swap the view to show the item selector for this category
        v = View(timeout=None)
        v.add_item(ItemSelect(category))
        # Keep the refresh button too
        refresh_btn = Button(label="🔄 Refresh", style=ButtonStyle.primary)
        async def _do_refresh(i: nextcord.Interaction):
            await i.response.defer(ephemeral=True)
            try:
                folder_map = refresh_folder_map()
                with open("folder_map.json", "w", encoding="utf-8") as f:
                    json.dump(folder_map, f, indent=2, ensure_ascii=False)
                # Rebuild the view (category list may have changed)
                await i.followup.send("✅ Drive map en menu ververst.", ephemeral=True)
            except Exception as e:
                await i.followup.send(f"❌ Error tijdens Drive refresh: `{e}`", ephemeral=True)
        refresh_btn.callback = _do_refresh
        v.add_item(refresh_btn)

        await interaction.response.edit_message(
            embed=Embed(
                title="Project SPECTRE File Explorer",
                description=f"Category: **{category}**\nSelect an item…",
                color=0x00FFCC
            ),
            view=v
        )

class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary)
        async def _refresh(interaction: nextcord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                folder_map = refresh_folder_map()
                with open("folder_map.json", "w", encoding="utf-8") as f:
                    json.dump(folder_map, f, indent=2, ensure_ascii=False)
                await interaction.followup.send("✅ Drive map en menu ververst.", ephemeral=True)
                # Re-draw the menu root after refresh
                await interaction.message.edit(
                    embed=Embed(
                        title="Project SPECTRE File Explorer",
                        description=DESCRIPTION,
                        color=0x00FFCC
                    ),
                    view=RootView()
                )
            except Exception as e:
                await interaction.followup.send(f"❌ Error tijdens Drive refresh: `{e}`", ephemeral=True)
        refresh.callback = _refresh
        self.add_item(refresh)

from drive_storage import refresh_folder_map, load_folder_map, fetch_dossier_json, SCOPES
from utils import (
    load_clearance,
    get_required_roles,
    list_categories,
    list_items,
    create_dossier_file,
    grant_file_clearance,
    revoke_file_clearance,
    DOSSIERS_DIR,
)
from config import get_log_channel, set_log_channel

# —— Load ENV ——
load_dotenv()
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID"))

CLIENT_ID = os.getenv("GDRIVE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GDRIVE_CLIENT_SECRET")
REDIRECT_URI = "https://project-spectre-production.up.railway.app/oauth2callback"

routes = web.RouteTableDef()

# —— Clearance description ——  
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

LOG_CHANNEL_ID = get_log_channel()
LOG_FILE = os.path.join(os.path.dirname(__file__), "actions.log")

# —— OAuth2 Web Server ——
@routes.get("/oauth2callback")
async def oauth2callback(request):
    code = request.rel_url.query.get("code")
    if not code:
        return web.Response(text="Geen code ontvangen.")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=data) as resp:
            token_data = await resp.json()

    token_info = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_url,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scopes": SCOPES,
    }
    with open("token.json", "w") as f:
        json.dump(token_info, f, indent=2)

    return web.Response(text="✅ Autorisatie gelukt! Je kunt dit venster sluiten.")

async def start_web_server():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    await site.start()

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
        grant_file_clearance(self.category, self.item, role_id)
        await interaction.response.send_message(
            content=(
                f"✅ Granted <@&{role_id}> access to "
                f"`{self.category}/{self.item}.json`."
            ),
            ephemeral=True
        )
        await log_action(
            f"🔓 {interaction.user} granted <@&{role_id}> access to `{self.category}/{self.item}.json`."
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
        revoke_file_clearance(self.category, self.item, role_id)
        await interaction.response.send_message(
            content=(
                f"✅ Revoked <@&{role_id}> from "
                f"`{self.category}/{self.item}.json`."
            ),
            ephemeral=True
        )
        await log_action(
            f"🔒 {interaction.user} revoked <@&{role_id}> from `{self.category}/{self.item}.json`."
        )

# —— Bot setup & Commands ——
bot = commands.Bot(command_prefix="/", intents=nextcord.Intents.all())

async def log_action(message: str):
    timestamp = datetime.datetime.utcnow().isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")

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

@bot.event
async def on_ready():
    await bot.sync_application_commands()
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
    name="createfile",
    description="Create a dossier JSON file",
    guild_ids=[GUILD_ID]
)
async def createfile_cmd(
    interaction: nextcord.Interaction,
    category: str,
    item: str,
    content: str,
):
    user_roles = {r.id for r in interaction.user.roles}
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
        or (user_roles & ALLOWED_ASSIGN_ROLES)
    ):
        return await interaction.response.send_message(
            "⛔ Only Level 5+, Classified, Admin or Owner may create files.",
            ephemeral=True,
        )
    try:
        create_dossier_file(category, item, content)
    except FileExistsError:
        return await interaction.response.send_message(
            "❌ File already exists.", ephemeral=True
        )
    await interaction.response.send_message(
        f"✅ Created `{category}/{item}.json`.", ephemeral=True
    )
    await log_action(
        f"📁 {interaction.user} created `{category}/{item}.json`."
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

@bot.slash_command(
    name="summonmenu",
    description="Resend the file explorer menu",
    guild_ids=[GUILD_ID],
)
async def summonmenu_cmd(interaction: nextcord.Interaction):
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
    ):
        return await interaction.response.send_message(
            "⛔ Only Admin or Owner may summon the menu.",
            ephemeral=True,
        )
    await interaction.response.send_message(
        embed=Embed(
            title="Project SPECTRE File Explorer",
            description=DESCRIPTION,
            color=0x00FFCC,
        ),
        view=RootView(),
    )
    await log_action(
        f"📣 {interaction.user} summoned the file explorer menu."
    )

@bot.slash_command(
    name="setlogchannel",
    description="Set the logging channel",
    guild_ids=[GUILD_ID],
)
async def setlogchannel_cmd(
    interaction: nextcord.Interaction,
    channel: nextcord.TextChannel,
):
    if not (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
    ):
        return await interaction.response.send_message(
            "⛔ Only Admin or Owner may set the log channel.",
            ephemeral=True,
        )
    global LOG_CHANNEL_ID
    set_log_channel(channel.id)
    LOG_CHANNEL_ID = channel.id
    await interaction.response.send_message(
        f"✅ Log channel set to {channel.mention}.", ephemeral=True
    )
    await log_action(
        f"🛠 {interaction.user} set the log channel to {channel.mention}."
    )

@bot.slash_command(name="debugtoken", description="Toon token scopes/bron", guild_ids=[GUILD_ID])
async def debugtoken_cmd(interaction: nextcord.Interaction):
    try:
        with open("token.json", "r", encoding="utf-8") as f:
            tok = json.load(f)
        scopes = tok.get("scopes")
        cid = tok.get("client_id")
        await interaction.response.send_message(
            f"**token.json aanwezig** ✅\n"
            f"**client_id**: `{cid}`\n"
            f"**scopes in token.json:**\n```json\n{json.dumps(scopes, indent=2)}\n```",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"**token.json NIET gevonden** ❌ `{e}`", ephemeral=True)

@bot.slash_command(name="debugdrive", description="Check SCOPES en env", guild_ids=[GUILD_ID])
async def debugdrive_cmd(interaction: nextcord.Interaction):
    try:
        from drive_storage import SCOPES
        env_folder = os.getenv("GDRIVE_FOLDER_ID")
        has_b64 = bool(os.getenv("GDRIVE_CREDS_BASE64"))
        await interaction.response.send_message(
            "**drive_storage.SCOPES**:\n"
            f"```json\n{json.dumps(SCOPES, indent=2)}\n```\n"
            f"**GDRIVE_FOLDER_ID**: `{env_folder}`\n"
            f"**GDRIVE_CREDS_BASE64 set**: `{has_b64}`",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"debugdrive error: `{e}`", ephemeral=True)

async def main():
    await start_web_server()
    await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
