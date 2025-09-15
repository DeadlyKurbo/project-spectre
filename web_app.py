# Web configuration service with Discord OAuth2 authentication.
#
# This FastAPI application implements a minimal configuration panel for
# Discord guilds.  Users authenticate via Discord OAuth2 (identify + guilds
# scopes) and may view or update per-guild settings stored in Postgres.
# The implementation follows the architecture outlined in the project
# documentation and is intentionally lightweight so the bot itself can
# remain focused on Discord interactions.

import json
import os
import secrets
from typing import Any, Dict, List, TYPE_CHECKING
from urllib.parse import urlencode

try:  # asyncpg is only required when database access is used
    import asyncpg  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled during runtime
    asyncpg = None

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg as _asyncpg

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
try:
    from starlette.middleware.sessions import SessionMiddleware
except ModuleNotFoundError:  # pragma: no cover - allows running without sessions
    SessionMiddleware = None

DISCORD_API = "https://discord.com/api"
# OAuth-related configuration is optional; missing values disable Discord login.
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_urlsafe(32))
DATABASE_URL = os.getenv("DATABASE_URL")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

OAUTH_CONFIGURED = all([CLIENT_ID, CLIENT_SECRET, REDIRECT_URI])

MANAGE_GUILD = 0x20
ADMIN = 0x8

app = FastAPI(title="Spectre Config Service")
if SessionMiddleware is not None:
    app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


async def get_db_pool() -> "_asyncpg.Pool":
    """Return an asyncpg connection pool, creating it on first use."""
    if asyncpg is None:
        raise RuntimeError("asyncpg not installed")
    if DATABASE_URL is None:
        raise RuntimeError("DATABASE_URL not configured")
    if not hasattr(app.state, "pool"):
        app.state.pool = await asyncpg.create_pool(DATABASE_URL)
    return app.state.pool


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """Landing page that offers login or greets the authenticated user."""
    try:
        user = request.session.get("user")
    except RuntimeError:
        user = None
    if not user:
        return HTMLResponse('<a href="/login">Login with Discord</a>')
    username = f"{user['username']}#{user['discriminator']}"
    return HTMLResponse(
        f"Hello, {username} — <a href='/guilds'>Configure guilds</a>"
    )


@app.get("/login")
async def login(request: Request) -> RedirectResponse:
    """Initiate the OAuth2 login flow."""
    if not OAUTH_CONFIGURED:
        raise HTTPException(status_code=501, detail="Discord OAuth2 not configured")
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    }
    return RedirectResponse(f"{DISCORD_API}/oauth2/authorize?{urlencode(params)}")


@app.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None) -> RedirectResponse:
    """Handle the OAuth2 callback and store session information."""
    if not OAUTH_CONFIGURED:
        raise HTTPException(status_code=501, detail="Discord OAuth2 not configured")
    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="Bad state")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me = (await client.get(f"{DISCORD_API}/users/@me", headers=headers)).json()
        guilds = (await client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)).json()

    request.session["user"] = me
    request.session["access_token"] = tokens["access_token"]
    request.session["guilds"] = guilds
    return RedirectResponse("/guilds")


def has_perm(perm_int: int, bit: int) -> bool:
    """Return True if ``perm_int`` contains ``bit``."""
    return (int(perm_int) & bit) == bit


@app.get("/guilds")
async def list_guilds(request: Request) -> JSONResponse:
    """Return guilds visible to the current user with manage permissions."""
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/")
    user_guilds: List[Dict[str, Any]] = request.session.get("guilds", [])
    pool = await get_db_pool()
    rows = await pool.fetch("SELECT guild_id FROM bot_guilds")
    bot_guild_ids = {r["guild_id"] for r in rows}

    visible = []
    for g in user_guilds:
        if g["id"] in bot_guild_ids:
            perms = int(g.get("permissions", 0))
            if has_perm(perms, MANAGE_GUILD) or has_perm(perms, ADMIN):
                visible.append({"id": g["id"], "name": g["name"], "icon": g.get("icon")})

    return JSONResponse({"guilds": visible})


@app.get("/guilds/{guild_id}/settings")
async def get_settings(guild_id: str, request: Request) -> JSONResponse:
    """Return settings for ``guild_id`` if user has access."""
    user_guilds = {g["id"]: g for g in request.session.get("guilds", [])}
    guild = user_guilds.get(guild_id)
    if not guild:
        raise HTTPException(status_code=403, detail="Not your guild / bot not present")
    perms = int(guild.get("permissions", 0))
    if not (has_perm(perms, MANAGE_GUILD) or has_perm(perms, ADMIN)):
        raise HTTPException(status_code=403, detail="No permission")

    pool = await get_db_pool()
    row = await pool.fetchrow("SELECT data FROM guild_settings WHERE guild_id=$1", guild_id)
    return JSONResponse(row["data"] if row else {})


@app.put("/guilds/{guild_id}/settings")
async def update_settings(guild_id: str, request: Request) -> JSONResponse:
    """Persist ``guild_id`` settings, ensuring the user has permission."""
    payload = await request.json()
    user_guilds = {g["id"]: g for g in request.session.get("guilds", [])}
    guild = user_guilds.get(guild_id)
    if not guild:
        raise HTTPException(status_code=403, detail="Not your guild / bot not present")
    perms = int(guild.get("permissions", 0))
    if not (has_perm(perms, MANAGE_GUILD) or has_perm(perms, ADMIN)):
        raise HTTPException(status_code=403, detail="No permission")

    pool = await get_db_pool()
    await pool.execute(
        """
        INSERT INTO guild_settings (guild_id, data, updated_at)
        VALUES ($1, $2::jsonb, NOW())
        ON CONFLICT (guild_id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
        """,
        guild_id,
        json.dumps(payload),
    )
    # Optional: publish a notification via Redis here for hot-reload
    return JSONResponse({"ok": True})


__all__ = ["app"]
