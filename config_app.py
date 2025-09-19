import os
import json
import logging
import secrets
from secrets import compare_digest
import asyncio
from urllib.parse import parse_qs, urlparse

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
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_API = "https://discord.com/api"


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

    user = request.session.get("user")
    if not user:
        async with httpx.AsyncClient() as c:
            headers = {"Authorization": f"Bearer {token['access_token']}"}
            user = (await c.get(f"{DISCORD_API}/users/@me", headers=headers)).json()
        request.session["user"] = user

    user_guilds = await get_user_guilds(token)
    bot_guilds = await get_bot_guilds()
    request.session["guilds"] = user_guilds
    common = _filter_common_guilds(user_guilds, bot_guilds)

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


async def _check_access(request: Request, guild_id: str):
    """Ensure the logged-in user can manage ``guild_id`` and the bot is present."""
    token = request.session.get("discord_token")
    if not token:
        raise HTTPException(401, "Unauthorized")

    user_guilds, bot_guilds = await asyncio.gather(
        get_user_guilds(token),
        get_bot_guilds(),
    )
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
    r.raise_for_status()
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
    r.raise_for_status()
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
async def root():
    html = """
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
    display:inline-flex; align-items:center; gap:8px; border-radius: 12px; padding: 10px 14px;
    background: color-mix(in oklab, var(--accent) 88%, black 8%);
    color:#0b0e14; font-weight:700; text-decoration:none; border:1px solid color-mix(in oklab, var(--accent) 50%, black 45%);
    box-shadow: 0 8px 24px color-mix(in oklab, var(--accent) 35%, transparent);
  }}
  .btn:hover {{ filter: brightness(1.05); transform: translateY(-1px); transition: .15s ease }}
  .muted {{ color: var(--muted) }}
  .field {{ display:flex; gap:10px; align-items:center; margin-top:10px }}
  input[type=text] {{
    flex:1; padding: 12px 14px; background:#0c111b; color:var(--text);
    border:1px solid rgba(255,255,255,.12); border-radius:12px; outline: none;
  }}
  .footer {{ margin-top: 34px; color: #8b95a7; font-size: 12px }}
  .accent {{ color: var(--accent) }}
  .chip {{ display:inline-block; padding:4px 8px; border:1px solid rgba(255,255,255,.1); border-radius:999px; background:#0c111b; }}
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
        <h3>Quick Launcher</h3>
        <div class="muted">Open a guild config (Basic Auth).</div>
        <div class="field">
          <input id="gid" type="text" placeholder="Enter Guild ID (e.g. 123456789012345678)" />
          <a class="btn" href="#" onclick="openGuild()">Open</a>
        </div>
        <div class="muted" style="margin-top:10px; font-size:12px;">Tip: your browser will prompt for credentials.</div>
      </div>

      <div class="card">
        <h3>cURL Helper</h3>
        <div class="muted">Copy a ready-to-edit PUT command.</div>
        <div class="field">
          <a class="btn" href="#" onclick="copyCurl()">Copy</a>
        </div>
        <div id="copyState" class="muted" style="margin-top:8px; font-size:12px;">Will copy with placeholders for <span class="accent">USER</span>/<span class="accent">PASS</span>.</div>
      </div>
    </div>

    <div class="footer">
      <span>© GU7 • {BRAND} Panel</span> ·
      <span>Theme <span class="accent">accent</span> {ACCENT}</span>
    </div>
  </div>

<script>
  function openGuild(){{
    const id = document.getElementById('gid').value.trim();
    if(!id) return alert('Enter a Guild ID first');
    window.location.href = '/panel/' + encodeURIComponent(id);
  }}
  function copyCurl(){{
    const id = document.getElementById('gid').value.trim() || '<GUILD_ID>';
    const cmd = [
      'curl -u USER:PASS -H "Content-Type: application/json" -X PUT',
      `-d '{DEFAULT_PAYLOAD}'`,
      window.location.origin + '/configs/' + id
    ].join(' ');
    navigator.clipboard.writeText(cmd).then(() => {{
      const el = document.getElementById('copyState');
      el.textContent = 'Copied! Paste in your terminal and replace USER/PASS.';
    }});
  }}
</script>
</body>
</html>
    """.format(
        ACCENT=ACCENT,
        BRAND=BRAND,
        BUILD=BUILD,
        REGION=REGION,
        SPACE=SPACE,
        DEFAULT_PAYLOAD=DEFAULT_PAYLOAD,
    )
    return HTMLResponse(html)
    # ...or just redirect to Swagger:
    # return RedirectResponse("/docs")


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
