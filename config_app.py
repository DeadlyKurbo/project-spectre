import os
import json
import logging
import secrets
from secrets import compare_digest
import asyncio
from urllib.parse import parse_qs, urlparse
import html

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware

from storage_spaces import read_json, write_json, backup_json

ACCENT = os.getenv("PANEL_ACCENT", "#7c3aed")  # default: imperial purple
BRAND = os.getenv("PANEL_BRAND", "SPECTRE")
BUILD = os.getenv("RAILWAY_GIT_COMMIT_SHA", "dev")[:7]
REGION = os.getenv("S3_REGION", "—")
SPACE = os.getenv("S3_BUCKET", "—")

DEFAULT_PAYLOAD = json.dumps(
    {
        "settings": {"menu_theme": "tcis-dark"},
        "ROOT_PREFIX": "records",
    },
    separators=(",", ":"),
)

logger = logging.getLogger(__name__)

app = FastAPI()
auth = HTTPBasic(auto_error=False)
try:
    templates = Jinja2Templates(directory="templates")
except AssertionError:
    templates = None

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_API = os.getenv("DISCORD_API", "https://discord.com/api/v10")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")

if not BOT_TOKEN:
    logger.error(
        "DISCORD_BOT_TOKEN (or DISCORD_TOKEN) not configured. "
        "Dashboard will run in limited mode without Discord guild data."
    )

BOT_TOKEN_AVAILABLE = bool(BOT_TOKEN)


class _OAuthClient:
    def __init__(self, client_id: str, redirect_uri: str):
        self.client_id = client_id
        self.redirect_uri = redirect_uri

    def fetch_token(
        self, token_url: str, *, client_secret: str, authorization_response: str
    ) -> dict:
        """Exchange authorization code for an access token."""
        code_list = parse_qs(urlparse(authorization_response).query).get("code")
        if not code_list:
            raise ValueError("authorization code not provided")
        resp = httpx.post(
            token_url,
            data={
                "client_id": self.client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code_list[0],
                "redirect_uri": self.redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


oauth = _OAuthClient(CLIENT_ID, REDIRECT_URI)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", secrets.token_urlsafe(32)))


def _env_or_default(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None:
        logger.warning("%s not set; defaulting to %r", key, default)
        return default
    return value


ADMIN_USER = _env_or_default("DASHBOARD_USERNAME", "admin")
ADMIN_PASS = _env_or_default("DASHBOARD_PASSWORD", "password")


def require_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(auth)):
    if request.session.get("user"):
        return True
    if creds and (
        compare_digest(creds.username, ADMIN_USER)
        and compare_digest(creds.password, ADMIN_PASS)
    ):
        return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Basic"},
    )


@app.get("/login", include_in_schema=False)
async def login(request: Request):
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    scopes = ["identify", "guilds"]
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "prompt": "consent",
    }
    qp = "&".join(
        f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items()
    )
    return RedirectResponse(f"{DISCORD_API}/oauth2/authorize?" + qp)


@app.get("/callback")
async def callback(request: Request):
    try:
        token = oauth.fetch_token(
            "https://discord.com/api/oauth2/token",
            client_secret=CLIENT_SECRET,
            authorization_response=str(request.url)
        )
        # Save the access token in session
        request.session["discord_token"] = token
        return RedirectResponse(url="/dashboard")

    except Exception as e:
        # Print to Railway logs
        import traceback
        print("⚠️ OAuth error in /callback:", e)
        traceback.print_exc()

        # Return an error message to the browser too
        return JSONResponse(
            status_code=500,
            content={"error": "OAuth callback failed", "detail": str(e)}
        )


MANAGE_GUILD = 0x20
ADMIN = 0x8


def _has_perm(p: int, b: int) -> bool:
    return (int(p) & b) == b


@app.get("/me")
async def me(request: Request):
    return request.session.get("user") or {}


@app.get("/dashboard")
async def dashboard(request: Request):
    token = request.session.get("discord_token")
    if not token:
        return RedirectResponse(url="/login")

    user, common = await _load_user_context(request)
    if user is None:
        return RedirectResponse(url="/login")

    if templates is None:
        return JSONResponse({"user": user, "guilds": common})

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "guilds": common,
        },
    )


async def get_user_guilds(token: dict) -> list[dict]:
    """Return guilds the user belongs to using their OAuth token."""
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
    r.raise_for_status()
    return r.json()


async def get_bot_guilds() -> list[dict]:
    """Return guilds the bot is a member of."""
    if not BOT_TOKEN_AVAILABLE:
        logger.warning(
            "Skipping bot guild lookup because the Discord bot token is not configured."
        )
        return []

    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
        )
    r.raise_for_status()
    return r.json()


def _filter_common_guilds(user_guilds: list[dict], bot_guilds: list[dict]) -> list[dict]:
    """Return guilds shared with the bot where the user has management rights."""
    bot_ids = {g["id"] for g in bot_guilds}
    common = []
    for g in user_guilds:
        if g["id"] not in bot_ids:
            continue
        perms = int(g.get("permissions", 0))
        if _has_perm(perms, MANAGE_GUILD) or _has_perm(perms, ADMIN):
            common.append(g)
    return common


def _format_username(user: dict) -> str:
    username = user.get("global_name") or user.get("username") or "Unknown user"
    discriminator = user.get("discriminator")
    if discriminator and discriminator not in ("0", "0000"):
        return f"{username}#{discriminator}"
    return username


def _avatar_url(user: dict) -> str | None:
    avatar = user.get("avatar")
    user_id = user.get("id")
    if not avatar or not user_id:
        return None
    ext = "gif" if str(avatar).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=96"


def _guild_icon(guild: dict) -> str | None:
    icon = guild.get("icon")
    guild_id = guild.get("id")
    if not icon or not guild_id:
        return None
    ext = "gif" if str(icon).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.{ext}?size=96"


def _guild_initials(name: str) -> str:
    if not name:
        return "?"
    parts = [segment for segment in name.strip().split() if segment]
    if not parts:
        return name[:2].upper()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


async def _load_user_context(request: Request) -> tuple[dict | None, list[dict]]:
    token = request.session.get("discord_token")
    if not token:
        return None, []

    user = request.session.get("user")
    if not user:
        try:
            async with httpx.AsyncClient() as c:
                headers = {"Authorization": f"Bearer {token['access_token']}"}
                resp = await c.get(f"{DISCORD_API}/users/@me", headers=headers)
                resp.raise_for_status()
                user = resp.json()
        except httpx.HTTPError:
            logger.exception("Failed to load Discord user profile during session load")
            return None, []
        request.session["user"] = user

    try:
        user_guilds, bot_guilds = await asyncio.gather(
            get_user_guilds(token),
            get_bot_guilds(),
        )
    except httpx.HTTPError:
        logger.exception(
            "Failed to load guild list for user %s", user.get("id", "<unknown>")
        )
        request.session["guilds"] = []
        return user, []

    common = _filter_common_guilds(user_guilds, bot_guilds)
    request.session["guilds"] = common
    return user, common


def _render_account_block(user: dict | None) -> str:
    if not user:
        return (
            "<div class=\"muted\">Sign in with Discord to manage your servers.</div>"
            "<div class=\"field\" style=\"margin-top:14px;\">"
            "  <a class=\"btn\" href=\"/login\">Connect with Discord</a>"
            "</div>"
        )

    display = html.escape(_format_username(user))
    user_id = html.escape(user.get("id", "—"))
    avatar = _avatar_url(user)
    avatar_html = (
        f'<img src="{avatar}" alt="" width="48" height="48" loading="lazy">'
        if avatar
        else '<div class="avatar-fallback">{}</div>'.format(
            html.escape(_guild_initials(user.get("username", "")))
        )
    )
    return (
        "<div class=\"account\">"
        f"  <div class=\"account-avatar\">{avatar_html}</div>"
        "  <div>"
        f"    <div class=\"account-name\">{display}</div>"
        f"    <div class=\"muted small\">ID: <span class=\"chip\">{user_id}</span></div>"
        "  </div>"
        "</div>"
        "<div class=\"field\" style=\"margin-top:16px;\">"
        "  <a class=\"btn\" href=\"/dashboard\">Open Dashboard</a>"
        "</div>"
    )


def _render_guilds_block(user: dict | None, guilds: list[dict]) -> str:
    if not user:
        return (
            "<div class=\"muted\">Log in with Discord to load servers you can manage.</div>"
        )

    if not BOT_TOKEN_AVAILABLE:
        return (
            "<div class=\"muted\">The dashboard is running in limited mode because the"
            " Discord bot token is not configured. Guild data cannot be loaded.</div>"
        )

    if not guilds:
        return (
            "<div class=\"muted\">We couldn't find any servers you manage with the bot."
            " Ensure the bot is invited and you have Manage Server permissions.</div>"
        )

    items = []
    for guild in guilds:
        gid = html.escape(guild.get("id", ""))
        name = html.escape(guild.get("name", "Unknown Server"))
        icon = _guild_icon(guild)
        if icon:
            icon_html = (
                f'<img src="{icon}" alt="" width="40" height="40" loading="lazy">'
            )
        else:
            icon_html = (
                '<div class="guild-fallback">{}</div>'.format(
                    html.escape(_guild_initials(guild.get("name", "")))
                )
            )
        items.append(
            "<a class=\"guild\" href=\"/panel/{gid}\">"
            f"  <div class=\"guild-icon\">{icon_html}</div>"
            "  <div class=\"guild-meta\">"
            f"    <div class=\"guild-name\">{name}</div>"
            f"    <div class=\"guild-id\">{gid}</div>"
            "  </div>"
            "</a>"
        )
    return "".join(items)


def _render_curl_select(guilds: list[dict]) -> str:
    if not guilds:
        return ""

    options = ["<option value=\"\">Select a server…</option>"]
    for guild in guilds:
        gid = html.escape(guild.get("id", ""))
        name = html.escape(guild.get("name", "Unknown Server"))
        options.append(f"<option value=\"{gid}\">{name} ({gid})</option>")
    return "".join(options)


async def _check_access(request: Request, guild_id: str):
    """Ensure the logged-in user can manage ``guild_id`` and the bot is present."""
    token = request.session.get("discord_token")
    if not token:
        raise HTTPException(401, "Unauthorized")

    if not BOT_TOKEN_AVAILABLE:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Discord bot token not configured; unable to validate guild access.",
        )

    try:
        user_guilds, bot_guilds = await asyncio.gather(
            get_user_guilds(token),
            get_bot_guilds(),
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else None
        if status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            request.session.pop("discord_token", None)
            request.session.pop("user", None)
            request.session.pop("guilds", None)
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Discord session expired. Please reconnect from the dashboard.",
            ) from exc
        logger.exception("Discord API request failed while validating guild access")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Failed to validate guild access via the Discord API.",
        ) from exc
    except httpx.HTTPError as exc:
        logger.exception("Unexpected Discord API error while validating guild access")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Failed to validate guild access via the Discord API.",
        ) from exc
    allowed = {g["id"] for g in _filter_common_guilds(user_guilds, bot_guilds)}
    if guild_id not in allowed:
        raise HTTPException(403, "Not your guild or bot missing")
    return True


@app.get("/discord/{guild_id}/roles")
async def guild_roles(guild_id: str, request: Request):
    await _check_access(request, guild_id)
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{DISCORD_API}/guilds/{guild_id}/roles",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"/roles failed: {r.status_code} {r.text}",
        )
    return [
        {"id": x["id"], "name": x["name"], "position": x["position"]}
        for x in r.json()
    ]


@app.get("/discord/{guild_id}/channels")
async def guild_channels(guild_id: str, request: Request):
    await _check_access(request, guild_id)
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{DISCORD_API}/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"/channels failed: {r.status_code} {r.text}",
        )
    chans = [
        {
            "id": x["id"],
            "name": x["name"],
            "type": x["type"],
            "parent_id": x.get("parent_id"),
        }
        for x in r.json()
    ]
    return [c for c in chans if c["type"] in (0, 5, 15)]


@app.get("/panel/{guild_id}", include_in_schema=False)
async def panel(request: Request, guild_id: str):
    token = request.session.get("discord_token")
    if not token:
        return RedirectResponse(url="/login")

    await _check_access(request, guild_id)

    return HTMLResponse(f"""
<!doctype html><meta charset="utf-8">
<title>Panel • {guild_id}</title>
<style>
  body{{background:#0b0e14;color:#e5e7eb;font-family:system-ui;margin:0;padding:24px}}
  .row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
  .card{{background:#0f1420;border:1px solid #1f2636;border-radius:14px;padding:16px}}
  select,input,button,textarea{{background:#0c111b;border:1px solid #2a3446;color:#e5e7eb;border-radius:10px;padding:10px;width:100%}}
  label{{font-size:12px;color:#9aa4b2}}
  h2{{margin:.2rem 0 1rem}}
</style>
<h1>Guild {guild_id}</h1>
<div class="row">
  <div class="card">
    <h2>Channels</h2>
    <label>Status Log</label><select id="status_log"></select><br><br>
    <label>Moderation Log</label><select id="moderation_log"></select><br><br>
    <label>Admin Log</label><select id="admin_log"></select>
  </div>
  <div class="card">
    <h2>Clearance Mapping</h2>
    <label>Level 1 Roles</label><select id="lvl1" multiple size="6"></select><br><br>
    <label>Level 3 Roles</label><select id="lvl3" multiple size="6"></select><br><br>
    <label>Level 5 Roles</label><select id="lvl5" multiple size="6"></select>
  </div>
  <div class="card">
    <h2>Archive</h2>
    <label>Root Prefix</label><input id="root_prefix" placeholder="records"/>
    <label>Theme</label><input id="theme" placeholder="gu7-dark"/>
  </div>
</div>
<br>
<button onclick="save()">Save</button>
<pre id="state"></pre>
<script>
const gid = "{guild_id}";
const stateEl = document.getElementById('state');
const j = async (p) => {{
  const resp = await fetch(p, {{ credentials: 'include' }});
  if (!resp.ok) {{
    const body = await resp.text();
    throw new Error(`${{p}} → ${{resp.status}} ${{body || resp.statusText}}`);
  }}
  try {{
    return await resp.json();
  }} catch (err) {{
    throw new Error(`Failed to parse response from ${{p}}: ${{err}}`);
  }}
}};
let roles=[], chans=[], cfg={{}};

async function load(){{
  stateEl.textContent = 'Loading configuration…';
  [roles, chans, cfg] = await Promise.all([
    j(`/discord/${{gid}}/roles`),
    j(`/discord/${{gid}}/channels`),
    j(`/configs/${{gid}}`)
  ]);
  const rs=(id)=>document.getElementById(id);
  const fill = (sel, items, val)=>{{
    const options = Array.isArray(items) ? items : [];
    sel.innerHTML = options.map(x=>`<option value="${{x.id}}">${{x.name}}</option>`).join('');
    if(Array.isArray(val)) val.forEach(v=>[...sel.options].find(o=>o.value===v)?.setAttribute('selected','selected'));
    if(typeof val==='string') sel.value = val || '';
  }};
  fill(rs('status_log'), chans, cfg.channels?.status_log);
  fill(rs('moderation_log'), chans, cfg.channels?.moderation_log);
  fill(rs('admin_log'), chans, cfg.channels?.admin_log);
  fill(rs('lvl1'), roles, cfg.clearance?.levels?.["1"]?.roles||[]);
  fill(rs('lvl3'), roles, cfg.clearance?.levels?.["3"]?.roles||[]);
  fill(rs('lvl5'), roles, cfg.clearance?.levels?.["5"]?.roles||[]);
  rs('root_prefix').value = cfg.archive?.root_prefix || 'records';
  rs('theme').value = cfg.branding?.theme || 'gu7-dark';
  stateEl.textContent = 'Configuration loaded.';
}}
function vals(sel){{
  return [...sel.options].filter(o=>o.selected).map(o=>o.value);
}}
async function save(){{
  stateEl.textContent = 'Saving…';
  const body = {{
    ...cfg,
    branding: {{ ...(cfg.branding||{{}}), theme: document.getElementById('theme').value }},
    archive:  {{ ...(cfg.archive||{{}}), root_prefix: document.getElementById('root_prefix').value }},
    channels: {{
      status_log: document.getElementById('status_log').value,
      moderation_log: document.getElementById('moderation_log').value,
      admin_log: document.getElementById('admin_log').value
    }},
    clearance: {{
      ...(cfg.clearance||{{}}),
      levels: {{
        ...(cfg.clearance?.levels||{{}}),
        "1": {{ name: (cfg.clearance?.levels?.["1"]?.name||"Confidential"), roles: vals(document.getElementById('lvl1')) }},
        "3": {{ name: (cfg.clearance?.levels?.["3"]?.name||"Secret"), roles: vals(document.getElementById('lvl3')) }},
        "5": {{ name: (cfg.clearance?.levels?.["5"]?.name||"Omega"), roles: vals(document.getElementById('lvl5')) }}
      }}
    }}
  }};
  const resp = await fetch(`/configs/${{gid}}`, {{
    method:'PUT',
    headers:{{'Content-Type':'application/json'}},
    credentials: 'include',
    body: JSON.stringify(body)
  }});
  const payload = await resp.text();
  if (!resp.ok) {{
    stateEl.textContent = `Save failed: ${{resp.status}} ${{payload || resp.statusText}}`;
    return;
  }}
  stateEl.textContent = 'Saved: ' + payload;
}}
load().catch(err => {{
  console.error(err);
  stateEl.textContent = err.message;
}});
</script>
""")



@app.get("/", include_in_schema=False)
async def root(request: Request):
    user, guilds = await _load_user_context(request)
    account_block = _render_account_block(user)
    guilds_block = _render_guilds_block(user, guilds)
    curl_select = _render_curl_select(guilds)

    if curl_select:
        curl_select_block = (
            "<label class=\"muted small\" for=\"curlGuild\" "
            "style=\"display:block;margin-top:14px;margin-bottom:8px;\">Target server</label>"
            f"<select id=\"curlGuild\">{curl_select}</select>"
        )
        copy_state_text = "Select a server to include its ID in the command."
    else:
        curl_select_block = (
            "<div class=\"muted small\" style=\"margin-top:12px;\">"
            "Log in to populate this list automatically."
            "</div>"
        )
        copy_state_text = "Copies with a <GUILD_ID> placeholder. Update it after logging in."

    html_doc = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{BRAND} Config Panel</title>
<meta name="theme-color" content="{ACCENT}">
<style>
  :root {{
    --accent: {ACCENT};
    --bg: #0b0e14;
    --panel: #0f1420;
    --muted: #9aa4b2;
    --text: #e5e7eb;
  }}
  * {{ box-sizing: border-box }}
  html, body {{ height: 100%; margin: 0; }}
  body {{
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, 'Helvetica Neue', Arial, 'Apple Color Emoji','Segoe UI Emoji';
    color: var(--text); background: radial-gradient(1200px 600px at 10% -10%, #1d2233 10%, transparent 50%),
             radial-gradient(1000px 600px at 110% 10%, #141926 10%, transparent 50%), var(--bg);
    overflow-x: hidden;
  }}
  /* subtle animated grid */
  .grid:before {{
    content:""; position: fixed; inset: 0;
    background:
      linear-gradient(transparent 95%, rgba(255,255,255,.06) 95%) 0 0/ 20px 20px,
      linear-gradient(90deg, transparent 95%, rgba(255,255,255,.06) 95%) 0 0/ 20px 20px;
    mask-image: radial-gradient(ellipse at 50% -10%, rgba(0,0,0,.8), transparent 60%);
    animation: pan 18s linear infinite;
    pointer-events: none;
  }}
  @keyframes pan {{ from {{ transform: translateY(0) }} to {{ transform: translateY(20px) }} }}
  .wrap {{ max-width: 980px; margin: 0 auto; padding: 56px 22px 80px; position: relative; }}
  /* glitch title */
  .title {{
    font-size: clamp(28px, 4vw, 48px); font-weight: 800; letter-spacing:.5px; line-height: 1.05;
    text-shadow: 0 0 24px color-mix(in oklab, var(--accent) 30%, transparent);
    position: relative; display:inline-block;
  }}
  .title:before, .title:after {{
    content: "{BRAND}"; position:absolute; inset:0; mix-blend-mode:screen; opacity:.55;
  }}
  .title:before {{ transform: translate(-1px,-1px); color:#00e5ff; filter: drop-shadow(0 0 6px #00e5ff66); }}
  .title:after  {{ transform: translate(1px,1px);   color:#ff2a6d; filter: drop-shadow(0 0 6px #ff2a6d66); }}
  .subtitle {{ color: var(--muted); margin-top: 6px }}
  .row {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap:16px; margin-top:28px; }}
  .card {{
    background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 16px; padding: 18px 18px 16px;
    box-shadow: 0 8px 30px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.04);
    backdrop-filter: blur(4px);
  }}
  .card h3 {{ margin:0 0 10px; font-size: 16px; color:#cfd6e4; font-weight:700; letter-spacing:.3px }}
  .btn {{
    display:inline-flex; align-items:center; justify-content:center; gap:8px; border-radius: 12px; padding: 10px 14px;
    background: color-mix(in oklab, var(--accent) 88%, black 8%);
    color:#0b0e14; font-weight:700; text-decoration:none; border:1px solid color-mix(in oklab, var(--accent) 50%, black 45%);
    box-shadow: 0 8px 24px color-mix(in oklab, var(--accent) 35%, transparent);
    cursor: pointer;
  }}
  .btn:hover {{ filter: brightness(1.05); transform: translateY(-1px); transition: .15s ease }}
  .muted {{ color: var(--muted) }}
  .field {{ display:flex; gap:10px; align-items:center; margin-top:10px }}
  input[type=text] {{
    flex:1; padding: 12px 14px; background:#0c111b; color:var(--text);
    border:1px solid rgba(255,255,255,.12); border-radius:12px; outline: none;
  }}
  select {{
    width: 100%; padding: 12px 14px; background:#0c111b; color:var(--text);
    border:1px solid rgba(255,255,255,.12); border-radius:12px; outline: none;
    appearance: none;
  }}
  .footer {{ margin-top: 34px; color: #8b95a7; font-size: 12px }}
  .accent {{ color: var(--accent) }}
  .chip {{ display:inline-block; padding:4px 8px; border:1px solid rgba(255,255,255,.1); border-radius:999px; background:#0c111b; }}
  .small {{ font-size: 12px; }}
  .account {{ display:flex; align-items:center; gap:12px; margin-top:6px; }}
  .account-avatar img {{ border-radius: 999px; border:1px solid rgba(255,255,255,.12); object-fit: cover; }}
  .avatar-fallback {{ width:48px; height:48px; border-radius:999px; background:#1b2233; display:flex; align-items:center; justify-content:center; font-weight:700; color:var(--accent); border:1px solid rgba(255,255,255,.1); }}
  .card--servers {{ grid-column: 1 / -1; }}
  .guild {{ display:flex; align-items:center; gap:12px; padding:12px; border:1px solid rgba(255,255,255,.06); border-radius:12px; text-decoration:none; color:var(--text); background:rgba(15,20,32,0.75); transition:.15s ease; }}
  .guild:hover {{ transform: translateY(-1px); border-color: color-mix(in oklab, var(--accent) 60%, rgba(255,255,255,.08)); box-shadow: 0 4px 18px rgba(0,0,0,.35); }}
  .guild-icon img {{ border-radius: 999px; border:1px solid rgba(255,255,255,.12); object-fit: cover; }}
  .guild-fallback {{ width:40px; height:40px; border-radius:999px; background:#1b2233; display:flex; align-items:center; justify-content:center; font-weight:700; color:var(--accent); border:1px solid rgba(255,255,255,.08); }}
  .guild-meta {{ display:flex; flex-direction:column; gap:4px; }}
  .guild-name {{ font-weight:600; font-size:14px; }}
  .guild-id {{ color:var(--muted); font-size:12px; }}
  button.btn {{ border:none; }}
</style>
</head>
<body class="grid">
  <div class="wrap">
    <div style="display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;">
      <div>
        <div class="title">{BRAND}</div>
        <div class="subtitle">Configuration Console</div>
      </div>
      <a class="btn" href="/docs" aria-label="Open API docs">Open API Docs →</a>
    </div>

    <div class="row">
      <div class="card">
        <h3>System</h3>
        <div class="muted">Space: <span class="chip">{SPACE}</span></div>
        <div class="muted" style="margin-top:6px;">Region: <span class="chip">{REGION}</span></div>
        <div class="muted" style="margin-top:6px;">Build: <span class="chip">{BUILD}</span></div>
        <div style="margin-top:14px;"><a class="btn" href="/health">Check Health</a></div>
      </div>

      <div class="card">
        <h3>Account</h3>
        {ACCOUNT_BLOCK}
      </div>

      <div class="card">
        <h3>cURL Helper</h3>
        <div class="muted">Copy a ready-to-edit PUT command.</div>
        {CURL_SELECT_BLOCK}
        <div class="field" style="margin-top:14px;">
          <button class="btn" type="button" onclick="copyCurl()">Copy</button>
        </div>
        <div id="copyState" class="muted" style="margin-top:8px; font-size:12px;">{COPY_STATE_TEXT}</div>
      </div>
    </div>

    <div class="row">
      <div class="card card--servers">
        <h3>Your Servers</h3>
        <div class="guild-list" style="display:flex; flex-direction:column; gap:12px; margin-top:12px;">
          {GUILD_LIST}
        </div>
      </div>
    </div>

    <div class="footer">
      <span>© GU7 • {BRAND} Panel</span> ·
      <span>Theme <span class="accent">accent</span> {ACCENT}</span>
    </div>
  </div>

<script>
  function copyCurl(){{
    const select = document.getElementById('curlGuild');
    const id = select && select.value ? select.value.trim() : '';
    const guildId = id || '<GUILD_ID>';
    const cmd = [
      'curl -u USER:PASS -H "Content-Type: application/json" -X PUT',
      `-d '{DEFAULT_PAYLOAD}'`,
      window.location.origin + '/configs/' + guildId
    ].join(' ');
    navigator.clipboard.writeText(cmd).then(() => {{
      const el = document.getElementById('copyState');
      if (!el) return;
      el.textContent = id
        ? 'Copied! Paste in your terminal and replace USER/PASS.'
        : 'Copied with placeholder. Replace <GUILD_ID> with one of your servers and update USER/PASS.';
    }}).catch(() => {{
      alert('Copy failed. Try copying manually:\n' + cmd);
    }});
  }}
</script>
</body>
</html>
    """

    return HTMLResponse(
        html_doc.format(
            ACCENT=ACCENT,
            BRAND=BRAND,
            BUILD=BUILD,
            REGION=REGION,
            SPACE=SPACE,
            ACCOUNT_BLOCK=account_block,
            CURL_SELECT_BLOCK=curl_select_block,
            COPY_STATE_TEXT=copy_state_text,
            GUILD_LIST=guilds_block or "<div class=\"muted\">No servers available.</div>",
            DEFAULT_PAYLOAD=DEFAULT_PAYLOAD,
        )
    )
@app.get("/health")
async def health():
    return {"ok": True}

def guild_key(guild_id: str) -> str:
    return f"guild-configs/{guild_id}.json"

@app.get("/configs/{guild_id}")
async def get_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    if request.session.get("user"):
        await _check_access(request, guild_id)
    doc, etag = read_json(guild_key(guild_id), with_etag=True)
    if not doc:
        return JSONResponse({"_meta": {"etag": None}, "settings": {}}, status_code=200)
    doc["_meta"] = {"etag": etag}
    return JSONResponse(doc)

@app.put("/configs/{guild_id}")
async def put_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    if request.session.get("user"):
        await _check_access(request, guild_id)
    payload = await request.json()

    current, etag = read_json(guild_key(guild_id), with_etag=True)
    if current:
        backup_json(guild_key(guild_id).split("/")[-1], current)

    client_etag = (payload.get("_meta") or {}).get("etag")
    to_store = {k: v for k, v in payload.items() if k != "_meta"}
    ok = write_json(guild_key(guild_id), to_store, etag=client_etag or etag)
    if not ok:
        raise HTTPException(status_code=409, detail="Config changed on server; refresh and retry.")
    return {"ok": True}
