# main.py — Project SPECTRE (Drive backend, robust OAuth + debug cmds)
import os, json, datetime, base64, asyncio, aiohttp
from aiohttp import web
import nextcord
from nextcord import Embed, SelectOption, ButtonStyle
from nextcord.ext import commands
from nextcord.ui import View, Select, Button
from nextcord.errors import HTTPException
from dotenv import load_dotenv
from urllib.parse import urlencode

from drive_storage import (
    refresh_folder_map, load_folder_map, fetch_dossier_json,
    add_role_to_acl, remove_role_from_acl, get_file_acl,
    create_json_file, SCOPES
)

# ── ENV ─────────────────────────────────────────────────────────────────────
load_dotenv()
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")
GUILD_ID        = int(os.getenv("GUILD_ID"))
MENU_CHANNEL_ID = int(os.getenv("MENU_CHANNEL_ID"))
REDIRECT_URI    = os.getenv("OAUTH_REDIRECT_URI", "https://project-spectre-production.up.railway.app/oauth2callback")

# Role constants (your IDs)
from utils import (
    list_categories, list_items,  # optional if you use them elsewhere
    CLASSIFIED_ROLE_ID,
    LEVEL1_ROLE_ID, LEVEL2_ROLE_ID, LEVEL3_ROLE_ID, LEVEL4_ROLE_ID, LEVEL5_ROLE_ID,
)
ALLOWED_ASSIGN_ROLES = {LEVEL1_ROLE_ID, LEVEL2_ROLE_ID, LEVEL3_ROLE_ID, LEVEL4_ROLE_ID, LEVEL5_ROLE_ID, CLASSIFIED_ROLE_ID}

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

# ── OAuth client resolve ────────────────────────────────────────────────────
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
    return node.get("client_id"), node.get("client_secret"), node.get("redirect_uris", [])

def _resolve_google_client():
    cid = os.getenv("GDRIVE_CLIENT_ID")
    csec = os.getenv("GDRIVE_CLIENT_SECRET")
    if cid and csec:
        return cid, csec, []
    data = _maybe_b64_or_json(os.getenv("GDRIVE_CREDS_BASE64")) or _maybe_b64_or_json(os.getenv("GDRIVE_CREDS"))
    if data:
        cid2, csec2, redirects = _extract_client_from_json(data)
        if cid2 and csec2:
            return cid2, csec2, redirects
    return None, None, []

def _build_auth_url() -> str:
    cid, csec, _ = _resolve_google_client()
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

# ── Web server for OAuth callback ───────────────────────────────────────────
routes = web.RouteTableDef()

@routes.get("/oauth2callback")
async def oauth2callback(request):
    cid, csec, redirects = _resolve_google_client()
    if not cid or not csec:
        return web.Response(text="Missing CLIENT_ID/SECRET. Check Railway env.")
    if REDIRECT_URI not in redirects and os.getenv("GDRIVE_CREDS") or os.getenv("GDRIVE_CREDS_BASE64"):
        print(f"[WARN] Add {REDIRECT_URI} to OAuth client redirect URIs in Google Cloud.")
    code = request.rel_url.query.get("code")
    if not code: return web.Response(text="Geen code ontvangen.")
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code, "client_id": cid, "client_secret": csec,
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=data) as resp:
            token_data = await resp.json()

    scopes_from_google = token_data.get("scope")
    scopes_list = scopes_from_google.split() if isinstance(scopes_from_google, str) else SCOPES

    token_info = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_url,
        "client_id": cid,
        "client_secret": csec,
        "scopes": scopes_list,
    }
    with open("token.json", "w", encoding="utf-8") as f:
        json.dump(token_info, f, indent=2)
    return web.Response(text="✅ Autorisatie gelukt! Je kunt dit venster sluiten.")

async def _start_web():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080); await site.start()

# ── Helpers ─────────────────────────────────────────────────────────────────
def _humanize_key(k: str) -> str:
    return k.replace("_", " ").title()

def _fmt_value(v) -> str:
    if isinstance(v, list):  return "\n".join(f"• {x}" for x in v) if v else "_(empty list)_"
    if isinstance(v, dict):  return "\n".join(f"• {k}: {v}" for k, v in v.items()) if v else "_(empty object)_"
    return str(v)

def _build_dossier_embed(category: str, item: str, data: dict) -> nextcord.Embed:
    e = nextcord.Embed(title=f"{category} / {item}".replace("_"," ").title(), color=0x00FFCC)
    for k, v in data.items():
        val = _fmt_value(v)
        if len(val) > 1024: val = val[:1010] + "…"
        e.add_field(name=_humanize_key(k), value=val or "—", inline=False)
    return e

# ── UI Components ───────────────────────────────────────────────────────────
class ItemSelect(Select):
    def __init__(self, category: str):
        self.category = category
        fm = load_folder_map()
        items = fm.get(category, {}).get("items", {})
        options = [SelectOption(label=k.replace("_"," ").title(), value=k) for k in sorted(items.keys())] \
                  or [SelectOption(label="(no items)", value="__none__", default=True)]
        super().__init__(placeholder="Select an item…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: nextcord.Interaction):
        if self.values[0] == "__none__":
            return await interaction.response.send_message("No items in this category.", ephemeral=True)
        item = self.values[0]
        try:
            fm = load_folder_map()
            file_id = fm[self.category]["items"][item]["id"]
            data, _ = fetch_dossier_json(file_id)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Fout bij laden dossier: `{e}`", ephemeral=True)

        embed = _build_dossier_embed(self.category, item, data)
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except HTTPException as ex:
            if "50035" in str(ex) or "Invalid Form Body" in str(ex):
                lines = [f"{self.category} / {item}".replace("_"," ").title(), "="*60, ""]
                for k,v in data.items(): lines += [f"{_humanize_key(k)}:", _fmt_value(v), ""]
                fname = f"{self.category}_{item}.txt".replace(" ", "_")
                with open(fname, "w", encoding="utf-8") as f: f.write("\n".join(lines))
                await interaction.response.send_message(
                    content="📎 Dossier is te lang voor een embed — zie bijgevoegde .txt",
                    file=nextcord.File(fname), ephemeral=True
                )
                os.remove(fname)
            else:
                await interaction.response.send_message(f"❌ Fout bij weergeven: `{ex}`", ephemeral=True)

class CategorySelect(Select):
    def __init__(self):
        try:
            fm = load_folder_map()
            cats = sorted(fm.keys())
        except Exception as e:
            print(f"[ERROR] load_folder_map: {e}"); cats = []
        options = [SelectOption(label=c.replace("_"," ").title(), value=c) for c in cats] \
                  or [SelectOption(label="No categories available", value="none", default=True)]
        super().__init__(placeholder="Select a category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: nextcord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("No categories available.", ephemeral=True)
        category = self.values[0]
        v = View(timeout=None)
        v.add_item(ItemSelect(category))
        refresh_btn = Button(label="🔄 Refresh", style=ButtonStyle.primary)

        async def _do_refresh(i: nextcord.Interaction):
            await i.response.defer(ephemeral=True)
            try:
                data = refresh_folder_map()
                with open("folder_map.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                await i.followup.send("✅ Drive map en menu ververst.", ephemeral=True)
            except Exception as e:
                await i.followup.send(f"❌ Error tijdens Drive refresh: `{e}`", ephemeral=True)

        refresh_btn.callback = _do_refresh
        v.add_item(refresh_btn)
        await interaction.response.edit_message(
            embed=Embed(title="Project SPECTRE File Explorer",
                        description=f"Category: **{category}**\nSelect an item…", color=0x00FFCC),
            view=v
        )

class RootView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())
        refresh = Button(label="🔄 Refresh", style=ButtonStyle.primary)
        async def _refresh(inter: nextcord.Interaction):
            await inter.response.defer(ephemeral=True)
            try:
                data = refresh_folder_map()
                with open("folder_map.json","w",encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                await inter.followup.send("✅ Drive map en menu ververst.", ephemeral=True)
                await inter.message.edit(
                    embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
                    view=RootView()
                )
            except Exception as e:
                await inter.followup.send(f"❌ Error tijdens Drive refresh: `{e}`", ephemeral=True)
        refresh.callback = _refresh
        self.add_item(refresh)

# ── Bot / Commands ──────────────────────────────────────────────────────────
intents = nextcord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    try: await bot.sync_application_commands()
    except Exception: pass
    print(f"✅ Project SPECTRE online as {bot.user} (Drive)")
    ch = bot.get_channel(MENU_CHANNEL_ID)
    if ch:
        try:
            await ch.send(embed=Embed(title="Project SPECTRE File Explorer",
                                      description=DESCRIPTION, color=0x00FFCC), view=RootView())
        except Exception: pass

@bot.slash_command(name="ping", description="Health check", guild_ids=[GUILD_ID])
async def ping_cmd(inter: nextcord.Interaction):
    await inter.response.send_message("pong ✅", ephemeral=True)

@bot.slash_command(name="authlink", description="Genereer Google OAuth link", guild_ids=[GUILD_ID])
async def authlink_cmd(inter: nextcord.Interaction):
    await inter.response.send_message(_build_auth_url(), ephemeral=True)

@bot.slash_command(name="debugenv", description="Welke GDRIVE_* vars zijn zichtbaar?", guild_ids=[GUILD_ID])
async def debugenv_cmd(inter: nextcord.Interaction):
    keys = ["GDRIVE_CLIENT_ID","GDRIVE_CLIENT_SECRET","GDRIVE_CREDS_BASE64","GDRIVE_CREDS","GDRIVE_FOLDER_ID"]
    found = {k: bool(os.getenv(k)) for k in keys}
    sizes = {k: (len(os.getenv(k)) if os.getenv(k) else 0) for k in keys}
    await inter.response.send_message(f"found={found}\nsizes={sizes}\n(redeploy nodig na var-wijzigingen)", ephemeral=True)

@bot.slash_command(name="debugauth", description="Show resolved OAuth client", guild_ids=[GUILD_ID])
async def debugauth_cmd(inter: nextcord.Interaction):
    cid, csec, redirects = _resolve_google_client()
    masked = (cid[:8] + "…") if cid else None
    await inter.response.send_message(
        f"client_id=`{masked}` have_secret=`{bool(csec)}` redirect_ok=`{REDIRECT_URI in redirects}`",
        ephemeral=True
    )

@bot.slash_command(name="refresh", description="Refresh folder map", guild_ids=[GUILD_ID])
async def refresh_cmd(inter: nextcord.Interaction):
    await inter.response.defer(ephemeral=True)
    try:
        data = refresh_folder_map()
        with open("folder_map.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        await inter.followup.send("✅ Folder map updated", ephemeral=True)
    except Exception as e:
        await inter.followup.send(f"❌ Error tijdens Drive refresh: `{e}`", ephemeral=True)

@bot.slash_command(name="grantfileclearance", description="Grant a role access to a dossier", guild_ids=[GUILD_ID])
async def grantfileclearance_cmd(inter: nextcord.Interaction):
    user_roles = {r.id for r in inter.user.roles}
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await inter.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may grant clearance.", ephemeral=True)

    sel = Select(placeholder="Step 1: Select category…",
                 options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in sorted(load_folder_map().keys())],
                 min_values=1, max_values=1)
    v = View(timeout=None); v.add_item(sel)

    async def sel_cat(i: nextcord.Interaction):
        cat = i.data["values"][0]
        v.clear_items()
        items = sorted(load_folder_map().get(cat, {}).get("items", {}).keys())
        sel2 = Select(placeholder="Step 2: Select item…",
                      options=[SelectOption(label=x.replace("_"," ").title(), value=x) for x in items],
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
                fm = load_folder_map()
                fid = fm[cat]["items"][it]["id"]
                add_role_to_acl(fid, int(i3.data["values"][0]))
                await i3.response.send_message(f"✅ Granted <@&{i3.data['values'][0]}> access to `{cat}/{it}.json`.", ephemeral=True)

            sel3.callback = do_grant
            await i2.response.edit_message(embed=Embed(title="Grant File Clearance",
                description=f"Category: **{cat}**\nItem: **{it}**\nSelect a role…"), view=v)

        sel2.callback = sel_item
        await i.response.edit_message(embed=Embed(title="Grant File Clearance",
            description=f"Category: **{cat}**\nSelect an item…"), view=v)

    sel.callback = sel_cat
    await inter.response.send_message(embed=Embed(title="Grant File Clearance",
        description="Step 1: Select category…", color=0x00FFCC), view=v, ephemeral=True)

@bot.slash_command(name="revokefileclearance", description="Revoke a role from a dossier", guild_ids=[GUILD_ID])
async def revokefileclearance_cmd(inter: nextcord.Interaction):
    user_roles = {r.id for r in inter.user.roles}
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator or (user_roles & ALLOWED_ASSIGN_ROLES)):
        return await inter.response.send_message("⛔ Only Level 5+, Classified, Admin or Owner may revoke clearance.", ephemeral=True)

    sel = Select(placeholder="Step 1: Select category…",
                 options=[SelectOption(label=c.replace("_"," ").title(), value=c) for c in sorted(load_folder_map().keys())],
                 min_values=1, max_values=1)
    v = View(timeout=None); v.add_item(sel)

    async def sel_cat(i: nextcord.Interaction):
        cat = i.data["values"][0]
        v.clear_items()
        items = sorted(load_folder_map().get(cat, {}).get("items", {}).keys())
        sel2 = Select(placeholder="Step 2: Select item…",
                      options=[SelectOption(label=x.replace("_"," ").title(), value=x) for x in items],
                      min_values=1, max_values=1)
        v.add_item(sel2)

        async def sel_item(i2: nextcord.Interaction):
            it = i2.data["values"][0]
            v.clear_items()
            fm = load_folder_map(); fid = fm[cat]["items"][it]["id"]
            role_ids = get_file_acl(fid)
            roles = [rid for rid in role_ids if i2.guild.get_role(rid)]
            sel3 = Select(placeholder="Step 3: Select role to revoke…",
                          options=[SelectOption(label=i2.guild.get_role(rid).name, value=str(rid)) for rid in roles]
                                  or [SelectOption(label="(none)", value="__none__", default=True)],
                          min_values=1, max_values=1)
            v.add_item(sel3)

            async def do_revoke(i3: nextcord.Interaction):
                rid = int(i3.data["values"][0])
                remove_role_from_acl(fid, rid)
                await i3.response.send_message(f"✅ Revoked <@&{rid}> from `{cat}/{it}.json`.", ephemeral=True)

            sel3.callback = do_revoke
            await i2.response.edit_message(embed=Embed(title="Revoke File Clearance",
                description=f"Category: **{cat}**\nItem: **{it}**\nSelect a role…", color=0xFF5555), view=v)

        sel2.callback = sel_item
        await i.response.edit_message(embed=Embed(title="Revoke File Clearance",
            description=f"Category: **{cat}**\nSelect an item…"), view=v)

    sel.callback = sel_cat
    await inter.response.send_message(embed=Embed(title="Revoke File Clearance",
        description="Step 1: Select category…", color=0xFF5555), view=v, ephemeral=True)

@bot.slash_command(name="summonmenu", description="Resend the file explorer menu", guild_ids=[GUILD_ID])
async def summonmenu_cmd(inter: nextcord.Interaction):
    if not (inter.user.id == inter.guild.owner_id or inter.user.guild_permissions.administrator):
        return await inter.response.send_message("⛔ Only Admin or Owner may summon the menu.", ephemeral=True)
    await inter.response.send_message(
        embed=Embed(title="Project SPECTRE File Explorer", description=DESCRIPTION, color=0x00FFCC),
        view=RootView()
    )

# ── Start everything ────────────────────────────────────────────────────────
async def main():
    await _start_web()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
