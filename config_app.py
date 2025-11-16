import os
import json
import logging
import secrets
from secrets import compare_digest
import asyncio
from urllib.parse import parse_qs, urlparse, quote
import html
from datetime import datetime, timedelta, timezone
from collections.abc import Iterable, Mapping
from typing import Any, Callable

import httpx
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    Depends,
    status,
    UploadFile as FastAPIUploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from async_utils import run_blocking
from storage_spaces import read_json, write_json, backup_json, list_dir, delete_file, save_json
from constants import ROOT_PREFIX
from config import get_latest_changelog, get_system_health
from operator_login import list_operators
from server_config import (
    invalidate_config,
    default_root_prefix_for,
    normalise_root_prefix,
)
from owner_portal import (
    OWNER_USER_KEY,
    OWNER_SETTINGS_KEY,
    save_owner_settings,
    load_owner_settings,
    build_change_entry,
)
from owner_portal import OWNER_USER_KEY as _OWNER_USER_KEY  # keep compat
from owner_portal import (
    ModerationSettings,
    OwnerSettings,
    can_manage_fleet,
    can_manage_portal,
    is_owner,
    validate_discord_id,
)
from fleet_manager import (
    FleetVessel,
    load_fleet_manifest,
    save_fleet_manifest,
)
from dossier import ensure_guild_archive_structure
from link_registry import (
    get_instance_summary,
    register_archive,
    unregister_archive,
    resolve_code as resolve_link_code,
)
from integrations.hd2 import (
    HelldiversIntegrationError,
    get_hd2_summary,
)
from gu7_fleet_specs import (
    get_gu7_ships,
    get_ship_by_slug,
    normalize_ship_slug,
    save_gu7_ship_spec,
)
from tech_spec_images import (
    list_ship_images,
    save_ship_image,
    get_ship_image_bytes,
)

logger = logging.getLogger("config_app")
logger.setLevel(logging.INFO)

_OWNER_FLASH_KEY = "owner_flash"
_FLEET_FLASH_KEY = "fleet_flash"
_MAX_TECH_SPEC_IMAGE_BYTES = 5 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TECH_SPEC_FORM_FIELDS = (
    "slug",
    "name",
    "call_sign",
    "role",
    "class_name",
    "manufacturer",
    "crew",
    "summary",
    "tagline",
    "length_m",
    "beam_m",
    "height_m",
    "mass_tons",
    "cargo_tons",
    "max_speed_ms",
    "jump_range_ly",
    "weapons",
    "systems",
    "badge",
)

app = FastAPI()
auth = HTTPBasic(auto_error=False)
try:
    templates = Jinja2Templates(directory="templates")
except AssertionError:
    templates = None

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_API = os.getenv("DISCORD_API", "https://discord.com/api/v10")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")

if not BOT_TOKEN:
    logger.error(
        "DISCORD_BOT_TOKEN (or DISCORD_TOKEN) not configured. "
        "Roles/channels endpoints will fail."
    )

# ---- CORS & Session cookie config for cross-origin dashboards ----
# Set DASHBOARD_ORIGIN to your frontend origin, e.g. "https://panel.yoursite.com"
DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN")


def _origin_from_env(value: str | None, *, env_key: str) -> str | None:
    if not value:
        return None

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        logger.warning("%s must include scheme and host; ignoring %r", env_key, value)
        return None

    origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.path not in ("", "/"):
        logger.warning("Ignoring path component %r from %s; only origin is required.", parsed.path, env_key)
    return origin


DASHBOARD_ORIGIN = _origin_from_env(DASHBOARD_ORIGIN, env_key="DASHBOARD_ORIGIN")
if not DASHBOARD_ORIGIN:
    logger.warning("DASHBOARD_ORIGIN not set; CORS will be disabled.")

raw_redirect_uri = os.getenv("DISCORD_REDIRECT_URI")
redirect_path = "/callback"
redirect_query = ""
redirect_fragment = ""
redirect_origin = None
if raw_redirect_uri:
    parsed_redirect = urlparse(raw_redirect_uri)
    if parsed_redirect.scheme and parsed_redirect.netloc:
        redirect_origin = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"
    if parsed_redirect.path:
        redirect_path = parsed_redirect.path
    if parsed_redirect.query:
        redirect_query = parsed_redirect.query
    if parsed_redirect.fragment:
        redirect_fragment = parsed_redirect.fragment

if DASHBOARD_ORIGIN:
    if redirect_origin and redirect_origin != DASHBOARD_ORIGIN:
        logger.warning(
            "DISCORD_REDIRECT_URI origin %s did not match dashboard origin %s; using dashboard origin.",
            redirect_origin,
            DASHBOARD_ORIGIN,
        )
    redirect_origin = DASHBOARD_ORIGIN

if redirect_origin:
    path = redirect_path or "/callback"
    if not path.startswith("/"):
        path = "/" + path
    if redirect_query:
        path = f"{path}?{redirect_query}"
    if redirect_fragment:
        path = f"{path}#{redirect_fragment}"
    REDIRECT_URI = f"{redirect_origin}{path}"
else:
    REDIRECT_URI = raw_redirect_uri

# IMPORTANT:
# SameSite=None + Secure is required for cookies to be sent cross-site.
# Make sure you are on HTTPS in production.
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_urlsafe(32))
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "session")

# Add session middleware with cross-site friendly settings
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="none",
    https_only=True,
    session_cookie=SESSION_COOKIE_NAME,
)

# Add CORS for your dashboard origin and allow credentials
if DASHBOARD_ORIGIN:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[DASHBOARD_ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
# -----------------------------------------------------------------

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

# Maintain compatibility for legacy imports that referenced OWNER_USER_ID here.
OWNER_USER_ID = _OWNER_USER_KEY


def bot_token_available() -> bool:
    """Return ``True`` when a bot token is currently configured."""

    token = BOT_TOKEN
    if not token:
        token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if token is None:
        return False
    if isinstance(token, str):
        token = token.strip()
    return bool(token)


BOT_FACT_CACHE_TTL = timedelta(minutes=5)
BOT_FACT_FAILURE_TTL = timedelta(minutes=1)
_STORAGE_LIST_LIMIT = 10_000

_files_cache = {"value": None, "timestamp": None, "ttl": BOT_FACT_CACHE_TTL}
_configs_cache = {"value": None, "timestamp": None, "ttl": BOT_FACT_CACHE_TTL}


def _invalidate_config_count_cache() -> None:
    """Mark cached configuration document totals as stale."""

    _configs_cache["value"] = None
    _configs_cache["timestamp"] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


_LINK_CODE_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789-")


def _normalise_share_code(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper().replace(" ", "")
    if not cleaned:
        return None
    segments = [segment for segment in cleaned.split("-") if segment]
    candidate = "-".join(segments) if segments else cleaned
    if any(ch not in _LINK_CODE_ALPHABET for ch in candidate):
        return None
    return candidate


def _archive_display_name(settings: Mapping | None) -> str | None:
    if not isinstance(settings, Mapping):
        return None
    archive_cfg = settings.get("archive") if isinstance(settings, Mapping) else None
    candidates: list[str | None] = []
    if isinstance(archive_cfg, Mapping):
        candidates.append(str(archive_cfg.get("name")) if archive_cfg.get("name") is not None else None)
        candidates.append(str(archive_cfg.get("label")) if archive_cfg.get("label") is not None else None)
    candidates.append(str(settings.get("archive_name")) if settings.get("archive_name") is not None else None)
    candidates.append(str(settings.get("name")) if settings.get("name") is not None else None)
    for candidate in candidates:
        if not candidate:
            continue
        cleaned = candidate.strip()
        if cleaned:
            return cleaned
    return None


def _normalise_link_entries(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, str]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        code = _normalise_share_code(str(entry.get("code")) if entry.get("code") is not None else None)
        root = normalise_root_prefix(entry.get("root_prefix"))
        if not code or not root:
            continue
        guild_id_raw = entry.get("guild_id")
        guild_id = str(guild_id_raw).strip() if guild_id_raw is not None else ""
        name_raw = entry.get("name")
        key = (code, root, guild_id or None)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, str] = {"code": code, "root_prefix": root}
        if guild_id:
            payload["guild_id"] = guild_id
        if isinstance(name_raw, str):
            name_clean = name_raw.strip()
            if name_clean:
                payload["name"] = name_clean
        cleaned.append(payload)
    return cleaned


def _clean_text_value(value: object, *, limit: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip()
    return cleaned


def _normalise_menu_settings(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, str] = {}
    title = _clean_text_value(raw.get("title"), limit=256)
    desc = _clean_text_value(raw.get("description"), limit=4000)
    footer = _clean_text_value(raw.get("footer"), limit=512)
    thumb = _clean_text_value(raw.get("thumbnail"), limit=512)
    if title:
        cleaned["title"] = title
    if desc:
        cleaned["description"] = desc
    if footer:
        cleaned["footer"] = footer
    if thumb:
        cleaned["thumbnail"] = thumb
    return cleaned


def _normalise_console_entry(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, str] = {}
    title = _clean_text_value(raw.get("title"), limit=256)
    desc = _clean_text_value(raw.get("description"), limit=4000)
    if title:
        cleaned["title"] = title
    if desc:
        cleaned["description"] = desc
    return cleaned


def _normalise_console_entries(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for key in ("regular", "lead", "high_command", "trainee"):
        entry = _normalise_console_entry(raw.get(key))
        if entry:
            cleaned[key] = entry
    return cleaned


def _cache_is_valid(cache: dict) -> bool:
    ts = cache.get("timestamp")
    ttl = cache.get("ttl") or BOT_FACT_CACHE_TTL
    if ts is None:
        return False
    return _now() - ts < ttl


def _set_cache(cache: dict, value, ttl: timedelta) -> None:
    cache["value"] = value
    cache["timestamp"] = _now()
    cache["ttl"] = ttl


def _count_files_matching(prefix: str, predicate: Callable[[str], bool]) -> int:
    total = 0
    base_prefix = (prefix or "").strip("/")
    stack = [base_prefix] if base_prefix else [""]
    seen: set[str] = set()

    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            dirs, files = list_dir(current, limit=_STORAGE_LIST_LIMIT)
        except FileNotFoundError:
            continue
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to list storage prefix %s while gathering bot statistics",
                current,
            )
            continue

        for name, _size in files:
            if predicate(name):
                total += 1

        for directory in dirs:
            child = directory.strip("/")
            if not child:
                continue
            next_prefix = f"{current}/{child}" if current else child
            if next_prefix not in seen:
                stack.append(next_prefix)

    return total


def _count_archived_files_sync() -> int:
    prefix = ROOT_PREFIX or ""
    return _count_files_matching(prefix, lambda name: not name.endswith(".keep"))


def _count_config_documents_sync() -> int:
    return _count_files_matching("guild-configs", lambda name: name.endswith(".json"))


def _truncate(text: str, limit: int = 120) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_number(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


async def _get_archived_file_total() -> int | None:
    if _cache_is_valid(_files_cache):
        return _files_cache.get("value")

    try:
        total = await run_blocking(_count_archived_files_sync)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to count archived files for bot statistics")
        _set_cache(_files_cache, None, BOT_FACT_FAILURE_TTL)
        return None

    _set_cache(_files_cache, total, BOT_FACT_CACHE_TTL)
    return total


async def _get_config_document_total() -> int | None:
    if _cache_is_valid(_configs_cache):
        return _configs_cache.get("value")

    try:
        total = await run_blocking(_count_config_documents_sync)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to count configuration documents for bot statistics")
        _set_cache(_configs_cache, None, BOT_FACT_FAILURE_TTL)
        return None

    _set_cache(_configs_cache, total, BOT_FACT_CACHE_TTL)
    return total


def _count_registered_operators() -> int | None:
    try:
        return len(list_operators())
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to load operator roster for bot statistics")
        return None

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


def _env_or_default(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None:
        logger.warning("%s not set; defaulting to %r", key, default)
        return default
    return value


ADMIN_USER = _env_or_default("DASHBOARD_USERNAME", "admin")
ADMIN_PASS = _env_or_default("DASHBOARD_PASSWORD", "password")


_UPLOAD_FILE_CLASSES = (FastAPIUploadFile, StarletteUploadFile)


def _coerce_upload_file(value: Any):
    """Return a valid upload file object when ``value`` quacks like one."""

    if isinstance(value, _UPLOAD_FILE_CLASSES):
        return value
    return None


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

PERM_MODE = os.getenv('DASHBOARD_PERM_MODE', 'normal').strip().lower()



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

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user.get("id") else None
    can_manage_owner_portal = can_manage_portal(user_id, owner_settings.managers)
    latest_update = owner_settings.latest_update.strip()
    bot_version = owner_settings.bot_version.strip()

    if templates is None:
        return JSONResponse(
            {
                "user": user,
                "guilds": common,
                "bot_version": bot_version,
                "latest_update": latest_update,
                "can_manage_owner": can_manage_owner_portal,
            }
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "guilds": common,
            "accent": ACCENT,
            "brand": BRAND,
            "build": BUILD,
            "bot_version": bot_version,
            "latest_update": latest_update,
            "can_manage_owner": can_manage_owner_portal,
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
    if not bot_token_available():
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


def _filter_manageable_guilds(user_guilds: list[dict]) -> list[dict]:
    """Return guilds where the user has sufficient permissions."""

    manageable: list[dict] = []
    for guild in user_guilds:
        perms_raw = guild.get("permissions")
        if perms_raw is None:
            perms_raw = guild.get("permissions_new")
        try:
            perms = int(perms_raw)
        except (TypeError, ValueError):
            perms = 0
        if (
            _has_perm(perms, MANAGE_GUILD)
            or _has_perm(perms, ADMIN)
            or bool(guild.get("owner"))
        ):
            manageable.append(guild)
    return manageable


def _filter_common_guilds(user_guilds: list[dict], bot_guilds: list[dict]) -> list[dict]:
    """Return guilds the user can manage, intersecting with the bot when possible."""

    manageable = _filter_manageable_guilds(user_guilds)
    if not bot_token_available():
        # Without the bot token we cannot verify membership.  Fall back to the
        # manageable set so the dashboard can still operate in a limited mode.
        return manageable

    if not bot_guilds:
        # Discord occasionally returns an empty list for the bot even when it
        # remains in guilds the user can manage (for example when the token was
        # recently rotated or cache propagation lags).  In that situation,
        # falling back to the manageable list avoids locking the operator out
        # of their configuration.
        return manageable

    bot_ids = {str(g.get("id")) for g in bot_guilds}
    common = [g for g in manageable if str(g.get("id")) in bot_ids]
    if not common and manageable:
        logger.warning(
            "No overlap between manageable user guilds and bot guilds; falling back to manageable set. "
            "Verify DISCORD_CLIENT_ID/SECRET belong to same app as DISCORD_BOT_TOKEN."
        )
        return manageable
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
        request.session.pop("bot_guild_count", None)
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
        user_guilds = await get_user_guilds(token)
    except httpx.HTTPError:
        logger.exception(
            "Failed to load guild list for user %s", user.get("id", "<unknown>")
        )
        request.session["guilds"] = []
        request.session.pop("bot_guild_count", None)
        return user, []

    bot_available = bot_token_available()
    bot_guilds: list[dict] = []
    bot_data_valid = False
    if bot_available:
        try:
            bot_guilds = await get_bot_guilds()
        except httpx.HTTPError:
            logger.exception(
                "Failed to refresh bot guild list; falling back to manageable guilds"
            )
        else:
            bot_data_valid = True

    if bot_available and bot_data_valid:
        common = _filter_common_guilds(user_guilds, bot_guilds)
        request.session["bot_guild_count"] = len(bot_guilds)
    else:
        common = _filter_manageable_guilds(user_guilds)
        request.session.pop("bot_guild_count", None)

    request.session["guilds"] = common
    return user, common


def _render_account_block(
    user: dict | None, *, show_admin_link: bool = False
) -> str:
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
        "<div class=\"field\" style=\"margin-top:16px;flex-wrap:wrap;\">"
        "  <a class=\"btn\" href=\"/dashboard\">Open Dashboard</a>"
        + (
            "  <a class=\"btn btn--ghost admin-only\" href=\"/owner\">Admin controls</a>"
            if show_admin_link
            else ""
        )
        + "</div>"
    )


def _render_ui_diagnostics_card(request: Request, *, admin_only: bool = False) -> str:
    """Return a diagnostics card describing cross-origin session status."""

    cors_enabled = bool(DASHBOARD_ORIGIN)
    if cors_enabled:
        cors_state = "Enabled"
        cors_class = "diag-ok"
        cors_hint = f"Allowing origin {html.escape(DASHBOARD_ORIGIN)}."
    else:
        cors_state = "Disabled"
        cors_class = "diag-warn"
        cors_hint = (
            "Set the DASHBOARD_ORIGIN environment variable to allow cross-site "
            "requests from your control panel."
        )

    cookie_name = html.escape(SESSION_COOKIE_NAME)
    cookie_present = SESSION_COOKIE_NAME in request.cookies
    if cookie_present:
        cookie_state = "Present"
        cookie_class = "diag-ok"
        cookie_hint = (
            f"Cookie “{cookie_name}” detected on this request."
        )
    else:
        cookie_state = "Not detected"
        cookie_class = "diag-warn"
        if cors_enabled:
            cookie_hint = (
                "Log in through your dashboard to establish the session cookie."
            )
        else:
            cookie_hint = (
                "The cookie will appear after authentication once CORS is configured."
            )

    policy_hint = (
        f"Cookies use the “{cookie_name}” name with SameSite=None and Secure=on for cross-origin support."
    )
    storage_hint = html.escape(OWNER_SETTINGS_KEY)

    classes = "card card--diagnostics"
    if admin_only:
        classes += " admin-only"

    return (
        f"<div class=\"{classes}\">"
        "  <h3>Cross-Origin Diagnostics</h3>"
        "  <div class=\"muted small\">Use this to verify dashboard access.</div>"
        "  <ul class=\"diag-list\">"
        f"    <li><div class=\"diag-label\">CORS</div>"
        f"        <div class=\"diag-value {cors_class}\">{cors_state}</div>"
        f"        <div class=\"diag-hint\">{cors_hint}</div></li>"
        f"    <li><div class=\"diag-label\">Session cookie</div>"
        f"        <div class=\"diag-value {cookie_class}\">{cookie_state}</div>"
        f"        <div class=\"diag-hint\">{cookie_hint}</div></li>"
        f"    <li><div class=\"diag-label\">Policy</div>"
        f"        <div class=\"diag-value diag-info\">SameSite=None</div>"
        f"        <div class=\"diag-hint\">{policy_hint}</div></li>"
        f"    <li><div class=\"diag-label\">Owner settings</div>"
        f"        <div class=\"diag-value diag-info\">{storage_hint}</div>"
        "        <div class=\"diag-hint\">Storage key used for broadcast cache.</div></li>"
        "  </ul>"
        "</div>"
    )


def _render_owner_card(
    settings: OwnerSettings, can_manage_owner: bool, *, admin_only: bool = False
) -> str:
    version = settings.bot_version.strip()
    if version:
        version_html = f"<span class=\"chip\">{html.escape(version)}</span>"
    else:
        version_html = "<span class=\"muted\">Not set</span>"

    update = settings.latest_update.strip()
    if update:
        update_html = html.escape(update).replace("\n", "<br>")
        update_block = f"<div class=\"owner-update\">{update_html}</div>"
    else:
        update_block = "<div class=\"muted small\">No update broadcast yet.</div>"

    manage_button = (
        "<div class=\"field\" style=\"margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;\">"
        "  <a class=\"btn\" href=\"/owner\">Manage broadcast</a>"
        "  <a class=\"btn btn--ghost\" href=\"/fleet\">Fleet manager</a>"
        "</div>"
        if can_manage_owner
        else ""
    )

    classes = "card card--owner"
    if admin_only:
        classes += " admin-only"

    return (
        f"<div class=\"{classes}\">"
        "  <h3>Operations broadcast</h3>"
        "  <div class=\"muted\">Bot version</div>"
        f"  <div class=\"owner-version\">{version_html}</div>"
        "  <div class=\"muted\" style=\"margin-top:12px;\">Latest update</div>"
        f"  {update_block}"
        f"  {manage_button}"
        "</div>"
    )


def _pop_owner_flash(request: Request) -> dict | None:
    data = request.session.get(_OWNER_FLASH_KEY)
    if data is not None:
        request.session.pop(_OWNER_FLASH_KEY, None)
    return data


def _pop_fleet_flash(request: Request) -> dict | None:
    data = request.session.get(_FLEET_FLASH_KEY)
    if data is not None:
        request.session.pop(_FLEET_FLASH_KEY, None)
    return data


def _form_bool(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "on", "yes", "checked"}


def _format_actor(user: dict | None) -> str:
    if not user:
        return "Unknown operator"

    username = user.get("global_name") or user.get("username") or "Operator"
    discriminator = user.get("discriminator")
    if discriminator and discriminator != "0":
        display = f"{username}#{discriminator}"
    else:
        display = username

    user_id = user.get("id")
    if user_id:
        return f"{display} ({user_id})"
    return display


async def _render_bot_facts_block(_user: dict | None, request: Request) -> str:
    guild_count = request.session.get("bot_guild_count")
    guild_count_error = False

    if guild_count is None and bot_token_available():
        try:
            bot_guilds = await get_bot_guilds()
        except httpx.HTTPError:
            logger.exception("Failed to refresh bot guild list for statistics")
            guild_count_error = True
        else:
            guild_count = len(bot_guilds)
            request.session["bot_guild_count"] = guild_count
    elif guild_count is None and not bot_token_available():
        guild_count_error = True

    files_total = await _get_archived_file_total()
    configs_total = await _get_config_document_total()
    operator_total = _count_registered_operators()
    changelog = get_latest_changelog()
    system_health = get_system_health()

    facts: list[tuple[str, str, str]] = []

    if guild_count is not None:
        hint = (
            "Discord servers currently running the bot."
            if guild_count
            else "Invite the bot to a server to begin operations."
        )
        facts.append(("Active servers", _format_number(int(guild_count)), hint))
    else:
        if not bot_token_available():
            hint = "Configure the bot token to unlock deployment stats."
        elif guild_count_error:
            hint = "Temporarily unable to reach Discord for deployment stats."
        else:
            hint = "Deployment data is temporarily unavailable."
        facts.append(("Active servers", "—", hint))

    if files_total is not None:
        file_hint = (
            "Files indexed across every dossier category."
            if files_total
            else "No dossiers have been archived yet."
        )
        facts.append(("Archive dossiers", _format_number(files_total), file_hint))
    else:
        facts.append(
            (
                "Archive dossiers",
                "—",
                "Storage is unreachable right now; totals will update once connectivity returns.",
            )
        )

    if configs_total is not None:
        config_hint = (
            "Guild configuration profiles stored in the archive."
            if configs_total
            else "No configuration profiles saved yet."
        )
        facts.append(("Config profiles", _format_number(configs_total), config_hint))
    else:
        facts.append(
            (
                "Config profiles",
                "—",
                "Unable to read configuration storage right now.",
            )
        )

    if operator_total is not None:
        operator_hint = (
            "Operators with active ID codes in the roster."
            if operator_total
            else "No operator records have been registered yet."
        )
        facts.append(("Registered operators", _format_number(operator_total), operator_hint))
    else:
        facts.append(
            (
                "Registered operators",
                "—",
                "Operator registry is temporarily unavailable.",
            )
        )

    if changelog:
        update = str(changelog.get("update") or "Update logged")
        update_value = _truncate(update, 60)
        timestamp = changelog.get("timestamp")
        notes = changelog.get("notes")
        hint_parts = []
        if timestamp:
            hint_parts.append(str(timestamp))
        if notes:
            hint_parts.append(_truncate(str(notes), 120))
        hint = " • ".join(hint_parts) if hint_parts else "Latest changelog entry."
        facts.append(("Latest update", update_value, hint))
    else:
        facts.append(("Latest update", "—", "No changelog entries recorded yet."))

    health_value = _truncate(str(system_health or "—"), 80)
    facts.append(("System health", health_value, "Status broadcast from the last system check."))

    items = []
    for label, value, hint in facts:
        label_html = html.escape(label)
        value_html = html.escape(value).replace("\n", "<br>")
        hint_html = html.escape(hint).replace("\n", "<br>") if hint else ""
        hint_block = f"<div class=\"fact-hint\">{hint_html}</div>" if hint_html else ""
        items.append(
            "<div class=\"fact\">"
            f"  <div class=\"fact-label\">{label_html}</div>"
            f"  <div class=\"fact-value\">{value_html}</div>"
            f"  {hint_block}"
            "</div>"
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

    def _cached_guild_ids() -> set[str]:
        cached = request.session.get("guilds")
        if not isinstance(cached, list):
            return set()
        ids: set[str] = set()
        for entry in cached:
            if isinstance(entry, dict) and entry.get("id") is not None:
                ids.add(str(entry["id"]))
        return ids

    guild_id_str = str(guild_id)
    if guild_id_str in _cached_guild_ids():
        return True

    try:
        user_guilds = await get_user_guilds(token)
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

    bot_guilds: list[dict]
    bot_available = bot_token_available()
    if bot_available:
        try:
            bot_guilds = await get_bot_guilds()
        except httpx.HTTPError as exc:
            logger.exception("Discord API request failed while validating bot membership")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Failed to validate guild access via the Discord API.",
            ) from exc
    else:
        bot_guilds = []
        request.session.pop("bot_guild_count", None)

    common = _filter_common_guilds(user_guilds, bot_guilds)
    request.session["guilds"] = common
    if bot_token_available():
        request.session["bot_guild_count"] = len(bot_guilds)

    allowed = {str(g.get("id")) for g in common if g.get("id") is not None}
    if guild_id_str not in allowed:
        detail = "Not your guild" if not bot_available else "Not your guild or bot missing"
        raise HTTPException(403, detail)
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



    guild_record = None
    for candidate in request.session.get("guilds") or []:
        if str(candidate.get("id")) == guild_id:
            guild_record = candidate
            break

    guild_name = guild_record.get("name") if isinstance(guild_record, dict) else None
    guild_icon_url = _guild_icon(guild_record) if guild_record else None
    if guild_icon_url:
        guild_avatar_html = (
            f'<img src="{html.escape(guild_icon_url)}" alt="" width="56" height="56" loading="lazy">'
        )
    else:
        guild_avatar_html = '<div class="guild-fallback">{}</div>'.format(
            html.escape(_guild_initials(guild_name or guild_id))
        )

    guild_display_name = guild_name or f"Guild {guild_id}"

    if templates is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Template rendering is unavailable on this deployment.",
        )

    context = {
        "request": request,
        "accent": ACCENT,
        "brand": BRAND,
        "guild_name": guild_display_name,
        "guild_avatar": guild_avatar_html,
        "guild_id": str(guild_id),
        "guild_id_js": json.dumps(str(guild_id)),
    }
    return templates.TemplateResponse("panel.html", context)



def _render_config_panel_html(**context):
    html_doc = """
<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{BRAND} Config Panel</title>
<meta name=\"theme-color\" content=\"{ACCENT}\">
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
  .title-row {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
  .actions {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }}
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
  .btn--ghost {{
    background: transparent;
    color: var(--text);
    border:1px solid rgba(255,255,255,.16);
    box-shadow: none;
  }}
  .btn--ghost:hover {{
    filter: none;
    transform: none;
    background: rgba(255,255,255,.08);
  }}
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
  .card--diagnostics {{ min-width: 260px; }}
  .fact-grid {{ display:grid; gap:16px; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); margin-top:16px; }}
  .fact {{ border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:16px; background:rgba(12,18,30,.72); display:flex; flex-direction:column; gap:8px; min-height:120px; box-shadow: inset 0 1px 0 rgba(255,255,255,.03); }}
  .fact-label {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:600; }}
  .fact-value {{ font-size:20px; font-weight:700; color:var(--text); line-height:1.2; }}
  .fact-hint {{ font-size:12px; color:var(--muted); line-height:1.45; }}
  .diag-list {{ list-style:none; padding:0; margin:16px 0 0; display:flex; flex-direction:column; gap:12px; }}
  .diag-list li {{ border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:12px 14px; background:rgba(12,18,30,.65); }}
  .diag-label {{ font-size:12px; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); font-weight:600; }}
  .diag-value {{ font-size:16px; font-weight:700; margin-top:4px; }}
  .diag-hint {{ font-size:12px; color:var(--muted); margin-top:6px; line-height:1.45; }}
  .diag-ok {{ color:#34d399; }}
  .diag-warn {{ color:#fbbf24; }}
  .diag-info {{ color:#60a5fa; word-break:break-word; }}
  button.btn {{ border:none; }}
  .card--owner .chip {{ background: rgba(12,18,30,.75); }}
  .owner-version {{ margin-top:8px; font-size:16px; font-weight:600; }}
  .owner-update {{
    margin-top:8px;
    padding:12px 14px;
    border-radius:12px;
    border:1px solid rgba(255,255,255,.08);
    background: rgba(12,18,30,.72);
    font-size:13px;
    line-height:1.5;
    white-space:pre-line;
  }}
</style>
</head>
<body class=\"grid\">
  <div class=\"wrap\">
    <div class=\"title-row\">
      <div>
        <div class=\"title\">{BRAND}</div>
        <div class=\"subtitle\">Configuration Console</div>
      </div>
      {ACTION_BLOCK}
    </div>

    <div class=\"row\">
      {SYSTEM_CARD}

      {OWNER_CARD}

      {FLEET_CARD}

      <div class=\"card\">
        <h3>Account</h3>
        {ACCOUNT_BLOCK}
      </div>

      {CURL_CARD}

      {DIAGNOSTICS_CARD}
    </div>

    <div class=\"row\">
      <div class=\"card\">
        <h3>Ship tech specs</h3>
        <div class=\"muted\">Look inside the fleet manifest files and review each vessel's GU7 tech specs.</div>
        <div class=\"field\" style=\"margin-top:14px;\">
          <a class=\"btn\" href=\"/gu7/tech-specs\">View Tech Specs</a>
        </div>
      </div>
    </div>

    <div class=\"row\">
      <div class=\"card card--servers\">
        <h3>Bot Intel</h3>
        <p class=\"muted small\">Live signals from the archive core.</p>
        <div class=\"fact-grid\">
          {BOT_FACTS}
        </div>
      </div>
    </div>

    <div class=\"footer\">
      <span>© {BRAND} Panel</span> ·
      <span>Theme <span class=\"accent\">accent</span> {ACCENT}</span>
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

    return HTMLResponse(html_doc.format(**context))


@app.get("/", include_in_schema=False)
async def root(request: Request):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    user_id = str(user.get("id")) if user and user.get("id") else None
    can_manage_owner_portal = can_manage_portal(user_id, owner_settings.managers)
    show_owner_admin_features = bool(can_manage_owner_portal)
    account_block = _render_account_block(user)
    owner_card = _render_owner_card(owner_settings, can_manage_owner_portal)
    diagnostics_card = ""
    system_card = ""
    curl_card = ""
    fleet_card = ""
    bot_facts_block = await _render_bot_facts_block(user, request)

    if show_owner_admin_features:
        action_block = (
            "<div class=\"actions\"><a class=\"btn btn--ghost\" href=\"/admin\">Enter admin mode</a></div>"
        )
    else:
        action_block = ""

    return _render_config_panel_html(
        ACCENT=ACCENT,
        BRAND=BRAND,
        BUILD=BUILD,
        REGION=REGION,
        SPACE=SPACE,
        ACCOUNT_BLOCK=account_block,
        OWNER_CARD=owner_card,
        CURL_CARD=curl_card,
        SYSTEM_CARD=system_card,
        FLEET_CARD=fleet_card,
        ACTION_BLOCK=action_block,
        BOT_FACTS=bot_facts_block,
        DIAGNOSTICS_CARD=diagnostics_card,
        DEFAULT_PAYLOAD=DEFAULT_PAYLOAD,
    )


@app.get("/admin", include_in_schema=False)
async def admin_console(request: Request):
    user, guilds = await _load_user_context(request)
    if not user:
        return RedirectResponse(url="/login")

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user and user.get("id") else None
    if not can_manage_portal(user_id, owner_settings.managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the admin controls.",
        )

    account_block = _render_account_block(user, show_admin_link=True)
    owner_card = _render_owner_card(owner_settings, True)
    diagnostics_card = _render_ui_diagnostics_card(request)
    bot_facts_block = await _render_bot_facts_block(user, request)

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

    curl_card = f"""
      <div class=\"card\">
        <h3>cURL Helper</h3>
        <div class=\"muted\">Copy a ready-to-edit PUT command.</div>
        {curl_select_block}
        <div class=\"field\" style=\"margin-top:14px;\">
          <button class=\"btn\" type=\"button\" onclick=\"copyCurl()\">Copy</button>
        </div>
        <div id=\"copyState\" class=\"muted\" style=\"margin-top:8px; font-size:12px;\">{copy_state_text}</div>
      </div>
    """

    system_card = """
      <div class=\"card\">
        <h3>System</h3>
        <div class=\"muted\">Space: <span class=\"chip\">{SPACE}</span></div>
        <div class=\"muted\" style=\"margin-top:6px;\">Region: <span class=\"chip\">{REGION}</span></div>
        <div class=\"muted\" style=\"margin-top:6px;\">Build: <span class=\"chip\">{BUILD}</span></div>
        <div style=\"margin-top:14px;\"><a class=\"btn\" href=\"/health\">Check Health</a></div>
      </div>
    """

    fleet_card = """
      <div class=\"card\">
        <h3>Fleet manifest</h3>
        <div class=\"muted\">Fleet managers and admins can edit the live manifest from here.</div>
        <div class=\"field\" style=\"margin-top:14px;\">
          <a class=\"btn\" href=\"/fleet\">Open Fleet manager</a>
        </div>
      </div>
    """

    action_block = (
        "<div class=\"actions\">"
        "<a class=\"btn btn--ghost\" href=\"/\">← Back to panel</a>"
        "<a class=\"btn\" href=\"/docs\" aria-label=\"Open API docs\">Open API Docs →</a>"
        "</div>"
    )

    return _render_config_panel_html(
        ACCENT=ACCENT,
        BRAND=BRAND,
        BUILD=BUILD,
        REGION=REGION,
        SPACE=SPACE,
        ACCOUNT_BLOCK=account_block,
        OWNER_CARD=owner_card,
        CURL_CARD=curl_card,
        SYSTEM_CARD=system_card,
        FLEET_CARD=fleet_card,
        ACTION_BLOCK=action_block,
        BOT_FACTS=bot_facts_block,
        DIAGNOSTICS_CARD=diagnostics_card,
        DEFAULT_PAYLOAD=DEFAULT_PAYLOAD,
    )


@app.get("/owner", include_in_schema=False)
async def owner_portal(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")

    settings, etag = load_owner_settings(with_etag=True)
    user_id = str(user.get("id")) if user.get("id") else None
    if not can_manage_portal(user_id, settings.managers):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You do not have access to the owner portal.")

    flash = _pop_owner_flash(request)
    owner_mode = is_owner(user_id)

    if templates is None:
        return JSONResponse(
            {
                "bot_version": settings.bot_version,
                "latest_update": settings.latest_update,
                "managers": settings.managers,
                "fleet_managers": settings.fleet_managers,
                "bot_active": settings.bot_active,
                "moderation": settings.moderation.to_payload(),
                "change_log": [entry.to_payload() for entry in settings.change_log],
                "can_add_managers": owner_mode,
                "owner_user_id": OWNER_USER_KEY,
            }
        )

    return templates.TemplateResponse(
        "owner.html",
        {
            "request": request,
            "accent": ACCENT,
            "brand": BRAND,
            "user": user,
            "settings": settings,
            "etag": etag or "",
            "can_add_managers": owner_mode,
            "managers": settings.managers,
            "fleet_managers": settings.fleet_managers,
            "flash": flash,
            "owner_user_id": OWNER_USER_KEY,
            "is_owner": owner_mode,
            "change_log": settings.change_log,
        },
    )


@app.post("/owner", include_in_schema=False)
async def update_owner_portal(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")

    settings, etag = load_owner_settings(with_etag=True)
    user_id = str(user.get("id")) if user.get("id") else None
    if not can_manage_portal(user_id, settings.managers):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You do not have access to the owner portal.")

    owner_mode = is_owner(user_id)
    actor = _format_actor(user)
    form = await request.form()
    action = form.get("action") or ""
    form_etag = form.get("etag") or None
    status_label = "success"
    message = ""

    if action == "update_metadata":
        updated = settings.copy()
        new_version = (form.get("bot_version") or "").strip()
        new_update = (form.get("latest_update") or "").strip()
        updated.bot_version = new_version
        updated.latest_update = new_update

        if new_version == settings.bot_version and new_update == settings.latest_update:
            message = "No broadcast changes detected."
        else:
            change_parts = []
            if new_version != settings.bot_version:
                change_parts.append(
                    f"version {settings.bot_version or '—'} → {new_version or '—'}"
                )
            if new_update != settings.latest_update:
                change_parts.append("announcement updated")
            if change_parts:
                updated.append_log_entry(
                    build_change_entry(actor, "Broadcast updated", "; ".join(change_parts))
                )
            if save_owner_settings(updated, etag=form_etag or etag):
                message = "Broadcast updated."
            else:
                status_label = "error"
                message = "The broadcast changed on the server. Refresh and try again."
    elif action == "update_bot_state":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may change the bot state."
        else:
            desired = _form_bool(form.get("bot_active"))
            reason = (form.get("reason") or "").strip()
            if desired == settings.bot_active:
                message = "Bot state is already up to date."
            else:
                updated = settings.copy()
                updated.bot_active = desired
                state_label = "Bot resumed" if desired else "Bot paused"
                details = f"State set to {'active' if desired else 'paused'}"
                if reason:
                    details = f"{details} — {reason}"
                updated.append_log_entry(build_change_entry(actor, state_label, details))
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Bot state updated."
                else:
                    status_label = "error"
                    message = "The bot state changed on the server. Refresh and try again."
    elif action == "add_manager":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may add moderators."
        else:
            candidate = validate_discord_id(form.get("manager_id"))
            if not candidate:
                status_label = "error"
                message = "Enter a valid numeric Discord user ID."
            elif candidate == OWNER_USER_KEY:
                status_label = "error"
                message = "The owner already has full access."
            elif candidate in settings.managers:
                status_label = "error"
                message = "That user already has manager access."
            else:
                updated = settings.copy()
                updated.managers.append(candidate)
                updated.append_log_entry(
                    build_change_entry(actor, "Moderator added", f"Granted access to {candidate}")
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Manager added successfully."
                else:
                    status_label = "error"
                    message = "The manager list changed on the server. Refresh and try again."
    elif action == "remove_manager":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may remove moderators."
        else:
            target = validate_discord_id(form.get("manager_id"))
            if not target:
                status_label = "error"
                message = "Enter a valid numeric Discord user ID."
            elif target not in settings.managers:
                status_label = "error"
                message = "That user does not have manager access."
            else:
                updated = settings.copy()
                updated.managers = [mid for mid in updated.managers if mid != target]
                updated.append_log_entry(
                    build_change_entry(actor, "Moderator removed", f"Revoked access from {target}")
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Manager removed."
                else:
                    status_label = "error"
                    message = "The manager list changed on the server. Refresh and try again."
    elif action == "add_fleet_manager":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may add fleet managers."
        else:
            candidate = validate_discord_id(form.get("fleet_manager_id"))
            if not candidate:
                status_label = "error"
                message = "Enter a valid numeric Discord user ID."
            elif candidate == OWNER_USER_KEY:
                status_label = "error"
                message = "The owner already has full access."
            elif candidate in settings.fleet_managers:
                status_label = "error"
                message = "That user already has fleet manager access."
            else:
                updated = settings.copy()
                updated.fleet_managers.append(candidate)
                updated.append_log_entry(
                    build_change_entry(
                        actor, "Fleet manager added", f"Granted fleet access to {candidate}"
                    )
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Fleet manager added successfully."
                else:
                    status_label = "error"
                    message = "The fleet manager list changed on the server. Refresh and try again."
    elif action == "remove_fleet_manager":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may remove fleet managers."
        else:
            target = validate_discord_id(form.get("fleet_manager_id"))
            if not target:
                status_label = "error"
                message = "Enter a valid numeric Discord user ID."
            elif target not in settings.fleet_managers:
                status_label = "error"
                message = "That user does not have fleet manager access."
            else:
                updated = settings.copy()
                updated.fleet_managers = [fid for fid in updated.fleet_managers if fid != target]
                updated.append_log_entry(
                    build_change_entry(
                        actor, "Fleet manager removed", f"Revoked fleet access from {target}"
                    )
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Fleet manager removed."
                else:
                    status_label = "error"
                    message = "The fleet manager list changed on the server. Refresh and try again."
    elif action == "update_moderation":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may update moderation controls."
        else:
            updated = settings.copy()
            new_flags = ModerationSettings(
                auto_moderation=_form_bool(form.get("auto_moderation")),
                link_blocking=_form_bool(form.get("link_blocking")),
                new_member_lock=_form_bool(form.get("new_member_lock")),
                escalation_mode=_form_bool(form.get("escalation_mode")),
            )
            if new_flags.to_payload() == updated.moderation.to_payload():
                message = "No moderation changes detected."
            else:
                changes: list[str] = []
                if new_flags.auto_moderation != updated.moderation.auto_moderation:
                    changes.append(
                        "Auto moderation "
                        + ("enabled" if new_flags.auto_moderation else "disabled")
                    )
                if new_flags.link_blocking != updated.moderation.link_blocking:
                    changes.append(
                        "Link blocking " + ("enabled" if new_flags.link_blocking else "disabled")
                    )
                if new_flags.new_member_lock != updated.moderation.new_member_lock:
                    changes.append(
                        "New member lock "
                        + ("activated" if new_flags.new_member_lock else "released")
                    )
                if new_flags.escalation_mode != updated.moderation.escalation_mode:
                    changes.append(
                        "Incident escalation "
                        + ("armed" if new_flags.escalation_mode else "stood down")
                    )
                updated.moderation = new_flags
                updated.append_log_entry(
                    build_change_entry(actor, "Moderation updated", "; ".join(changes) or None)
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Moderation controls updated."
                else:
                    status_label = "error"
                    message = "Moderation settings changed on the server. Refresh and try again."
    elif action == "add_log_entry":
        note = (form.get("log_note") or "").strip()
        if not note:
            status_label = "error"
            message = "Enter details for the log entry."
        else:
            updated = settings.copy()
            updated.append_log_entry(build_change_entry(actor, "Manual update", note))
            if save_owner_settings(updated, etag=form_etag or etag):
                message = "Log entry recorded."
            else:
                status_label = "error"
                message = "The change log updated on the server. Refresh and try again."
    elif action == "clear_log":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may clear the change log."
        else:
            reason = (form.get("reason") or "").strip()
            if not settings.change_log:
                message = "The change log is already empty."
            else:
                updated = settings.copy()
                updated.change_log = []
                entry_details = "Log cleared"
                if reason:
                    entry_details = f"{entry_details} — {reason}"
                updated.append_log_entry(build_change_entry(actor, "Change log cleared", entry_details))
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Change log cleared."
                else:
                    status_label = "error"
                    message = "The change log updated on the server. Refresh and try again."
    else:
        status_label = "error"
        message = "Unsupported owner portal action."

    request.session[_OWNER_FLASH_KEY] = {"status": status_label, "message": message}
    return RedirectResponse(url="/owner", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/fleet", include_in_schema=False)
async def fleet_manager_page(request: Request):
    user = request.session.get("user")

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user and user.get("id") else None
    can_manage = can_manage_fleet(
        user_id, owner_settings.managers, owner_settings.fleet_managers
    )

    manifest, etag = load_fleet_manifest(with_etag=True)
    flash = _pop_fleet_flash(request) if can_manage else None
    ship_images = list_ship_images()
    gu7_ships = list(get_gu7_ships())
    gu7_ship_payloads = [ship.to_payload() for ship in gu7_ships]
    spec_slugs = {ship.slug for ship in gu7_ships}
    tech_spec_ships: list[dict[str, Any]] = []
    tech_spec_options: list[dict[str, str]] = []
    seen_slugs: set[str] = set()
    tech_spec_prefill_entries: list[dict[str, Any]] = []

    def _add_option(slug: str, name: str, call_sign: str | None) -> None:
        if not slug:
            return
        if any(option["slug"] == slug for option in tech_spec_options):
            return
        tech_spec_options.append(
            {
                "slug": slug,
                "name": name or slug,
                "call_sign": call_sign or "",
            }
        )

    for ship in gu7_ships:
        slug = ship.slug
        seen_slugs.add(slug)
        _add_option(slug, ship.name, ship.call_sign)
        tech_spec_ships.append(
            {
                "slug": slug,
                "name": ship.name,
                "call_sign": ship.call_sign,
                "has_image": slug in ship_images,
                "updated_at": ship_images.get(slug, {}).get("updated_at"),
            }
        )

    for idx, vessel in enumerate(manifest.vessels):
        slug = _viewer_slug_for_vessel(vessel, idx)
        if not slug:
            continue
        display_name = vessel.name or (vessel.vessel_id or f"Hull {idx + 1}")
        call_sign = vessel.registry_id or vessel.vessel_id
        _add_option(slug, display_name, call_sign)
        if slug not in spec_slugs:
            tech_spec_prefill_entries.append(
                _prefill_spec_entry_from_vessel(vessel, slug)
            )
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        tech_spec_ships.append(
            {
                "slug": slug,
                "name": display_name,
                "call_sign": call_sign,
                "has_image": slug in ship_images,
                "updated_at": ship_images.get(slug, {}).get("updated_at"),
            }
        )

    viewer_name = _format_actor(user) if user else "Guest observer"
    viewer_id = user_id or "—"
    is_authenticated = bool(user)

    if templates is None:
        return JSONResponse(
            {
                "last_updated": manifest.last_updated,
                "vessels": [v.to_payload() for v in manifest.vessels],
                "can_manage": can_manage,
                "viewer": {
                    "name": viewer_name,
                    "id": viewer_id,
                    "authenticated": is_authenticated,
                },
                "tech_spec_ships": tech_spec_ships,
                "tech_spec_options": tech_spec_options,
                "tech_spec_entries": gu7_ship_payloads,
                "tech_spec_prefill_entries": tech_spec_prefill_entries,
            }
        )

    return templates.TemplateResponse(
        "fleet.html",
        {
            "request": request,
            "accent": ACCENT,
            "brand": BRAND,
            "user": user,
            "operator_name": viewer_name,
            "vessels": [v.to_payload() for v in manifest.vessels],
            "last_updated": manifest.last_updated,
            "etag": etag or "",
            "flash": flash,
            "viewer_id": viewer_id,
            "can_manage": can_manage,
            "is_authenticated": is_authenticated,
            "tech_spec_ships": tech_spec_ships,
            "tech_spec_options": tech_spec_options,
            "tech_spec_entries": gu7_ship_payloads,
            "tech_spec_prefill_entries": tech_spec_prefill_entries,
        },
    )


@app.post("/fleet", include_in_schema=False)
async def update_fleet_manager(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user.get("id") else None
    if not can_manage_fleet(user_id, owner_settings.managers, owner_settings.fleet_managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You do not have access to the fleet manifest."
        )

    manifest, etag = load_fleet_manifest(with_etag=True)
    form = await request.form()
    action = (form.get("action") or "").strip()
    form_etag = (form.get("etag") or "").strip() or None
    status_label = "success"
    message = ""

    if action == "add_vessel":
        name = (form.get("name") or "").strip()
        vessel_type = (form.get("vessel_type") or "").strip()
        armaments = (form.get("armaments") or "").strip()
        speed = (form.get("speed") or "").strip()
        assignment = (form.get("assignment") or "").strip()
        registry_id = (form.get("registry_id") or "").strip()
        shipyard = (form.get("shipyard") or "").strip()
        commission_date = (form.get("commission_date") or "").strip()
        assigned_squadron = (form.get("assigned_squadron") or "").strip()
        clearance_level = (form.get("clearance_level") or "").strip()
        status_value = (form.get("status") or "").strip()
        status_value = status_value.title() if status_value else ""
        vessel_motto_raw = (form.get("vessel_motto") or "").strip()
        notes_raw = (form.get("notes") or "").strip()
        notes = notes_raw or None
        vessel_motto = vessel_motto_raw or None

        if not name:
            status_label = "error"
            message = "Enter a vessel name before saving."
        else:
            updated = manifest.copy()
            vessel = FleetVessel(
                vessel_id=secrets.token_hex(8),
                name=name,
                vessel_type=vessel_type,
                armaments=armaments,
                speed=speed,
                assignment=assignment,
                registry_id=registry_id,
                shipyard=shipyard,
                commission_date=commission_date,
                assigned_squadron=assigned_squadron,
                clearance_level=clearance_level,
                status=status_value,
                vessel_motto=vessel_motto,
                notes=notes,
            )
            updated.vessels.append(vessel)
            updated.touch()
            if save_fleet_manifest(updated, etag=form_etag or etag):
                message = f"{name} added to the manifest."
            else:
                status_label = "error"
                message = "The manifest changed on the server. Refresh and try again."
    elif action == "remove_vessel":
        vessel_id = (form.get("vessel_id") or "").strip()
        if not vessel_id:
            status_label = "error"
            message = "Missing vessel identifier."
        else:
            updated = manifest.copy()
            before = len(updated.vessels)
            updated.vessels = [v for v in updated.vessels if v.vessel_id != vessel_id]
            if len(updated.vessels) == before:
                status_label = "error"
                message = "Vessel not found or already removed."
            else:
                updated.touch()
                if save_fleet_manifest(updated, etag=form_etag or etag):
                    message = "Vessel removed from the manifest."
                else:
                    status_label = "error"
                    message = "The manifest changed on the server. Refresh and try again."
    elif action == "edit_vessel":
        vessel_id = (form.get("vessel_id") or "").strip()
        name = (form.get("name") or "").strip()
        vessel_type = (form.get("vessel_type") or "").strip()
        armaments = (form.get("armaments") or "").strip()
        speed = (form.get("speed") or "").strip()
        assignment = (form.get("assignment") or "").strip()
        registry_id = (form.get("registry_id") or "").strip()
        shipyard = (form.get("shipyard") or "").strip()
        commission_date = (form.get("commission_date") or "").strip()
        assigned_squadron = (form.get("assigned_squadron") or "").strip()
        clearance_level = (form.get("clearance_level") or "").strip()
        status_value = (form.get("status") or "").strip()
        status_value = status_value.title() if status_value else ""
        vessel_motto_raw = (form.get("vessel_motto") or "").strip()
        notes_raw = (form.get("notes") or "").strip()
        notes = notes_raw or None
        vessel_motto = vessel_motto_raw or None

        if not vessel_id:
            status_label = "error"
            message = "Missing vessel identifier."
        elif not name:
            status_label = "error"
            message = "Enter a vessel name before saving."
        else:
            updated = manifest.copy()
            target = next((v for v in updated.vessels if v.vessel_id == vessel_id), None)
            if target is None:
                status_label = "error"
                message = "Vessel not found or already removed."
            else:
                target.name = name
                target.vessel_type = vessel_type
                target.armaments = armaments
                target.speed = speed
                target.assignment = assignment
                target.registry_id = registry_id
                target.shipyard = shipyard
                target.commission_date = commission_date
                target.assigned_squadron = assigned_squadron
                target.clearance_level = clearance_level
                target.status = status_value
                target.vessel_motto = vessel_motto
                target.notes = notes
                updated.touch()
                if save_fleet_manifest(updated, etag=form_etag or etag):
                    message = f"{name} updated."
                else:
                    status_label = "error"
                    message = "The manifest changed on the server. Refresh and try again."
    else:
        status_label = "error"
        message = "Unsupported fleet action."

    request.session[_FLEET_FLASH_KEY] = {"status": status_label, "message": message}
    return RedirectResponse(url="/fleet", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/health")
async def health():
    return {"ok": True}


def _brand_initials(name: str | None) -> str:
    if not name:
        return "HD"
    parts = [segment for segment in name.strip().split() if segment]
    if not parts:
        return "HD"
    initials = "".join(part[0] for part in parts)[:2]
    return initials.upper() or "HD"


async def _collect_hd2_summary() -> tuple[dict[str, Any], str | None]:
    try:
        payload = await get_hd2_summary()
    except HelldiversIntegrationError as exc:
        logger.warning("Helldivers feed unavailable: %s", exc)
        message = str(exc) or "Helldivers feed unavailable."
        return {}, message
    except Exception:
        logger.exception("Unexpected error while fetching Helldivers II summary")
        return {}, "Failed to fetch Helldivers II Galactic War data."
    return (payload or {}), None


@app.get("/helldivers/summary")
async def helldivers_public_summary():
    payload, error = await _collect_hd2_summary()
    if error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=error)
    return JSONResponse(payload)


@app.get("/api/hd2/summary")
async def hd2_summary(_: bool = Depends(require_auth)):
    payload, error = await _collect_hd2_summary()
    if error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=error)
    return JSONResponse(payload)


@app.get("/helldivers", include_in_schema=False)
async def helldivers_page(request: Request):
    if templates is None:
        payload, error = await _collect_hd2_summary()
        if error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=error)
        return JSONResponse(payload)

    payload, error = await _collect_hd2_summary()
    context = {
        "request": request,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_initials": _brand_initials(BRAND),
        "build": BUILD,
        "summary": payload,
        "summary_error": error,
    }
    return templates.TemplateResponse("helldivers.html", context)


def _viewer_summary_from_vessel(vessel: FleetVessel) -> str:
    segments: list[str] = []
    if vessel.assignment:
        segments.append(f"Assignment: {vessel.assignment}")
    if vessel.assigned_squadron:
        segments.append(f"Squadron: {vessel.assigned_squadron}")
    if vessel.status:
        segments.append(f"Status: {vessel.status}")
    if vessel.clearance_level:
        segments.append(f"Clearance: {vessel.clearance_level}")
    if vessel.registry_id:
        segments.append(f"Registry: {vessel.registry_id}")
    if segments:
        return " • ".join(segments)
    if vessel.notes:
        return vessel.notes
    return "Awaiting GU7 tech specs."


def _viewer_systems_from_vessel(vessel: FleetVessel) -> list[str]:
    details: list[str] = []
    if vessel.shipyard:
        details.append(f"Shipyard: {vessel.shipyard}")
    if vessel.commission_date:
        details.append(f"Commissioned: {vessel.commission_date}")
    if vessel.speed:
        details.append(f"Cruising speed: {vessel.speed}")
    if vessel.clearance_level:
        details.append(f"Clearance: {vessel.clearance_level}")
    if vessel.notes:
        details.append(vessel.notes)
    return details


def _viewer_slug_for_vessel(vessel: FleetVessel, index: int) -> str:
    for candidate in (vessel.vessel_id, vessel.name):
        slug = normalize_ship_slug(candidate or "")
        if slug:
            return slug
    return f"fleet-vessel-{index}"


def _merge_vessel_with_specs(
    vessel: FleetVessel,
    slug: str,
    spec_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    spec = spec_payload or {}

    def spec_value(key: str) -> Any:
        return spec.get(key)

    weapons = list(spec_value("weapons") or [])
    if not weapons and vessel.armaments:
        weapons = [vessel.armaments]

    systems = list(spec_value("systems") or [])
    if not systems:
        systems = _viewer_systems_from_vessel(vessel)

    summary = spec_value("summary") or _viewer_summary_from_vessel(vessel)

    badge = spec_value("badge") or vessel.status or "Registered"
    badge_tone = _badge_tone(badge)

    return {
        "slug": slug,
        "name": vessel.name or spec_value("name") or "Unnamed vessel",
        "call_sign": spec_value("call_sign")
        or vessel.registry_id
        or vessel.vessel_id,
        "role": spec_value("role")
        or vessel.vessel_type
        or (vessel.status and f"{vessel.status} status"),
        "class_name": spec_value("class_name")
        or vessel.assigned_squadron
        or vessel.assignment
        or vessel.vessel_type,
        "manufacturer": spec_value("manufacturer") or vessel.shipyard,
        "length_m": spec_value("length_m"),
        "beam_m": spec_value("beam_m"),
        "height_m": spec_value("height_m"),
        "mass_tons": spec_value("mass_tons"),
        "crew": spec_value("crew"),
        "cargo_tons": spec_value("cargo_tons"),
        "max_speed_ms": spec_value("max_speed_ms"),
        "jump_range_ly": spec_value("jump_range_ly"),
        "weapons": weapons,
        "systems": systems,
        "summary": summary,
        "badge": badge,
        "badge_tone": badge_tone,
        "tagline": spec_value("tagline")
        or vessel.vessel_motto
        or vessel.assignment
        or vessel.status,
        "image_url": spec_value("image_url") or "",
        "angles": list(spec_value("angles") or []),
    }


def _prefill_spec_entry_from_vessel(vessel: FleetVessel, slug: str) -> dict[str, Any]:
    payload = _merge_vessel_with_specs(vessel, slug, None)
    return {field: payload.get(field) for field in _TECH_SPEC_FORM_FIELDS}


def _coerce_spec_number(value: str | None, label: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"n/a", "na", "none", "null"}:
        return None
    normalized = text.replace(",", "")
    try:
        return float(normalized)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{label} must be a number or left blank.") from exc


def _split_spec_lines(value: str | None) -> list[str]:
    if not value:
        return []
    entries: list[str] = []
    for raw in str(value).splitlines():
        text = raw.strip()
        if text:
            entries.append(text)
    return entries


_BADGE_TONE_ALIASES = {
    "active": "active",
    "operational": "active",
    "online": "active",
    "ready": "active",
    "retrofit": "retrofit",
    "refit": "retrofit",
    "lost": "lost",
    "destroyed": "lost",
    "m-i-a": "lost",
    "in-dock": "dock",
    "dock": "dock",
    "docked": "dock",
    "drydock": "dock",
    "in-drydock": "dock",
    "reserve": "reserve",
    "standby": "reserve",
    "prototype": "reserve",
}


def _normalize_badge_label(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    filtered = [ch if ch.isalnum() else "-" for ch in text]
    normalized = "".join(filtered)
    parts = [segment for segment in normalized.split("-") if segment]
    return "-".join(parts)


def _badge_tone(value: str | None) -> str:
    normalized = _normalize_badge_label(value)
    return _BADGE_TONE_ALIASES.get(normalized, "neutral")


@app.get("/gu7/tech-specs", include_in_schema=False)
async def gu7_tech_specs(request: Request):
    ships = list(get_gu7_ships())
    image_manifest = list_ship_images()
    ship_lookup: dict[str, dict[str, Any]] = {}
    for ship in ships:
        payload = ship.to_payload()
        slug = payload.get("slug")
        payload["badge_tone"] = _badge_tone(payload.get("badge"))
        entry = image_manifest.get(slug)
        if slug and entry:
            updated = entry.get("updated_at") or ""
            version = quote(updated) if updated else ""
            query = f"?v={version}" if version else ""
            payload["image_url"] = f"/gu7/tech-specs/images/{slug}{query}"
        else:
            payload["image_url"] = ""
        if slug:
            ship_lookup[slug] = payload
    manifest, _ = load_fleet_manifest()
    manifest_payload = {
        "last_updated": manifest.last_updated,
        "vessels": [v.to_payload() for v in manifest.vessels],
    }
    manifest_count = len(manifest.vessels)

    viewer_ships: list[dict[str, Any]] = []
    for idx, vessel in enumerate(manifest.vessels):
        slug = _viewer_slug_for_vessel(vessel, idx)
        viewer_ships.append(
            _merge_vessel_with_specs(vessel, slug, ship_lookup.get(slug))
        )
    if templates is None:
        return JSONResponse(
            {
                "accent": ACCENT,
                "brand": BRAND,
                "ships": viewer_ships,
                "manifest": manifest_payload,
                "registered_vessel_count": manifest_count,
            }
        )

    context = {
        "request": request,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_initials": _brand_initials(BRAND),
        "ships": viewer_ships,
        "initial_ship": viewer_ships[0] if viewer_ships else None,
        "manifest_last_updated": manifest_payload["last_updated"],
        "registered_vessel_count": manifest_count,
    }
    return templates.TemplateResponse("gu7_specs.html", context)


@app.get("/gu7/tech-specs/images/{slug}", include_in_schema=False)
async def gu7_tech_spec_image(slug: str):
    ship = get_ship_by_slug(slug)
    if ship is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ship not found")
    try:
        data, content_type = get_ship_image_bytes(slug)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    headers = {"Cache-Control": "public, max-age=3600"}
    return Response(content=data, media_type=content_type, headers=headers)


@app.post("/gu7/tech-specs/upload", include_in_schema=False)
async def upload_tech_spec_image(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user.get("id") else None
    if not can_manage_fleet(user_id, owner_settings.managers, owner_settings.fleet_managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You do not have access to the fleet manifest."
        )

    form = await request.form()
    slug = normalize_ship_slug(form.get("ship_slug") or "")
    upload = form.get("image")
    upload_file = _coerce_upload_file(upload)

    ships: dict[str, str] = {}
    for ship in get_gu7_ships():
        if ship.slug:
            ships[ship.slug] = ship.name

    manifest, _ = load_fleet_manifest()
    for idx, vessel in enumerate(manifest.vessels):
        vessel_slug = _viewer_slug_for_vessel(vessel, idx)
        if not vessel_slug or vessel_slug in ships:
            continue
        display_name = vessel.name or vessel.registry_id or vessel_slug
        ships[vessel_slug] = display_name
    status_label = "success"
    message = "Tech spec image updated."

    if not slug or slug not in ships:
        status_label = "error"
        message = "Select a valid vessel before uploading."
    elif upload_file is None or not getattr(upload_file, "filename", ""):
        status_label = "error"
        message = "Attach a PNG image to continue."
    else:
        file_bytes = await upload_file.read()

        if not file_bytes:
            status_label = "error"
            message = "The uploaded file was empty."
        elif len(file_bytes) > _MAX_TECH_SPEC_IMAGE_BYTES:
            status_label = "error"
            message = "PNG files must be 5 MB or smaller."
        elif not file_bytes.startswith(_PNG_SIGNATURE):
            status_label = "error"
            message = "Only PNG images are supported right now."
        else:
            save_ship_image(slug, file_bytes)
            vessel_name = ships.get(slug) or slug
            message = f"{vessel_name} tech spec updated."

    if upload_file is not None:
        await upload_file.close()

    request.session[_FLEET_FLASH_KEY] = {"status": status_label, "message": message}
    return RedirectResponse(url="/fleet", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/gu7/tech-specs/spec", include_in_schema=False)
async def save_tech_spec_entry(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user.get("id") else None
    if not can_manage_fleet(user_id, owner_settings.managers, owner_settings.fleet_managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You do not have access to the fleet manifest."
        )

    form = await request.form()
    slug = normalize_ship_slug(form.get("slug") or "")
    name = (form.get("name") or "").strip()
    status_label = "success"
    custom_badge_sentinel = "__custom__"

    def _resolve_badge() -> str:
        badge_choice = (form.get("badge_status") or "").strip()
        badge_custom = (form.get("badge_custom") or "").strip()
        legacy_badge = (form.get("badge") or "").strip()
        if badge_choice and badge_choice != custom_badge_sentinel:
            return badge_choice
        if badge_choice == custom_badge_sentinel:
            return badge_custom
        if badge_custom:
            return badge_custom
        return legacy_badge

    if not slug or not name:
        status_label = "error"
        message = "Provide both a ship slug and display name before saving."
    else:
        try:
            payload = {
                "slug": slug,
                "name": name,
                "call_sign": (form.get("call_sign") or "").strip(),
                "role": (form.get("role") or "").strip(),
                "class_name": (form.get("class_name") or "").strip(),
                "manufacturer": (form.get("manufacturer") or "").strip(),
                "length_m": _coerce_spec_number(form.get("length_m"), "Length (m)"),
                "beam_m": _coerce_spec_number(form.get("beam_m"), "Beam (m)"),
                "height_m": _coerce_spec_number(form.get("height_m"), "Height (m)"),
                "mass_tons": _coerce_spec_number(form.get("mass_tons"), "Mass (t)"),
                "crew": (form.get("crew") or "").strip(),
                "cargo_tons": _coerce_spec_number(form.get("cargo_tons"), "Cargo (tons)"),
                "max_speed_ms": _coerce_spec_number(form.get("max_speed_ms"), "Sublight speed (m/s)"),
                "jump_range_ly": _coerce_spec_number(form.get("jump_range_ly"), "Jump range (ly)"),
                "weapons": _split_spec_lines(form.get("weapons")),
                "systems": _split_spec_lines(form.get("systems")),
                "summary": (form.get("summary") or "").strip(),
                "badge": _resolve_badge(),
                "tagline": (form.get("tagline") or "").strip(),
            }
            save_gu7_ship_spec(payload)
            message = f"{name} tech specs saved."
        except ValueError as exc:
            status_label = "error"
            message = str(exc)

    request.session[_FLEET_FLASH_KEY] = {"status": status_label, "message": message}
    return RedirectResponse(url="/fleet", status_code=status.HTTP_303_SEE_OTHER)


def guild_key(guild_id: str) -> str:
    return f"guild-configs/{guild_id}.json"


def _coerce_channel_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        value = stripped
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_menu_channel(doc: Any) -> int | None:
    if not isinstance(doc, Mapping):
        return None
    settings_obj = doc.get("settings") if isinstance(doc.get("settings"), Mapping) else None
    if isinstance(settings_obj, Mapping):
        channels_obj = settings_obj.get("channels")
        if isinstance(channels_obj, Mapping):
            candidate = _coerce_channel_id(channels_obj.get("menu_home"))
            if candidate is not None:
                return candidate
        legacy_candidate = _coerce_channel_id(settings_obj.get("MENU_CHANNEL_ID"))
        if legacy_candidate is not None:
            return legacy_candidate
    direct_candidate = _coerce_channel_id(doc.get("MENU_CHANNEL_ID"))
    if direct_candidate is not None:
        return direct_candidate
    return None

@app.get("/configs/{guild_id}")
async def get_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    if request.session.get("user"):
        await _check_access(request, guild_id)
    doc, etag = read_json(guild_key(guild_id), with_etag=True)

    exists = doc is not None
    payload: dict = dict(doc or {})

    settings = payload.get("settings")
    if isinstance(settings, Mapping):
        copied_settings = dict(settings)
    else:
        copied_settings = {}

    archive_cfg = copied_settings.get("archive")
    archive_copy: dict[str, Any]
    if isinstance(archive_cfg, Mapping):
        archive_copy = dict(archive_cfg)
    else:
        archive_copy = {}
    links_clean = _normalise_link_entries(archive_copy.get("links"))
    if links_clean:
        archive_copy["links"] = links_clean
    else:
        archive_copy.pop("links", None)
    menu_clean = _normalise_menu_settings(archive_copy.get("menu"))
    if menu_clean:
        archive_copy["menu"] = menu_clean
    else:
        archive_copy.pop("menu", None)
    consoles_clean = _normalise_console_entries(archive_copy.get("consoles"))
    if consoles_clean:
        archive_copy["consoles"] = consoles_clean
    else:
        archive_copy.pop("consoles", None)
    if archive_copy:
        copied_settings["archive"] = archive_copy
    else:
        copied_settings.pop("archive", None)
    payload["settings"] = copied_settings

    payload["_meta"] = {"etag": etag, "exists": exists}
    return JSONResponse(payload)


@app.get("/links/code")
async def fetch_link_code(_: bool = Depends(require_auth)):
    summary = get_instance_summary()
    return JSONResponse(summary)


@app.post("/links/resolve")
async def resolve_link_payload(request: Request, _: bool = Depends(require_auth)):
    body = await request.json()
    raw_code = body.get("code") if isinstance(body, Mapping) else None
    code = _normalise_share_code(str(raw_code) if raw_code is not None else None)
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid archive code.")
    try:
        result = resolve_link_code(code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid archive code.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archive code not found.") from exc
    return JSONResponse(result)


@app.put("/configs/{guild_id}")
async def put_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    if request.session.get("user"):
        await _check_access(request, guild_id)
    payload = await request.json()

    try:
        gid_int = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid guild ID.") from exc

    settings = payload.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        payload["settings"] = settings

    archive_cfg_raw = settings.get("archive")
    archive_cfg = dict(archive_cfg_raw) if isinstance(archive_cfg_raw, dict) else {}

    links_clean = _normalise_link_entries(archive_cfg.get("links"))
    if links_clean:
        archive_cfg["links"] = links_clean
    else:
        archive_cfg.pop("links", None)
    menu_clean = _normalise_menu_settings(archive_cfg.get("menu"))
    if menu_clean:
        archive_cfg["menu"] = menu_clean
    else:
        archive_cfg.pop("menu", None)
    consoles_clean = _normalise_console_entries(archive_cfg.get("consoles"))
    if consoles_clean:
        archive_cfg["consoles"] = consoles_clean
    else:
        archive_cfg.pop("consoles", None)

    base_root = None
    for candidate in (
        archive_cfg.get("root_prefix"),
        settings.get("ROOT_PREFIX"),
        payload.get("ROOT_PREFIX"),
    ):
        base_root = normalise_root_prefix(candidate)
        if base_root:
            break

    root_prefix = default_root_prefix_for(gid_int, base=base_root)
    if links_clean or normalise_root_prefix(archive_cfg.get("root_prefix")):
        archive_cfg["root_prefix"] = root_prefix
    else:
        archive_cfg.pop("root_prefix", None)

    if archive_cfg:
        settings["archive"] = archive_cfg
        payload["archive"] = archive_cfg
    else:
        settings.pop("archive", None)
        payload.pop("archive", None)

    clearance_cfg_raw = settings.get("clearance")
    clearance_cfg = dict(clearance_cfg_raw) if isinstance(clearance_cfg_raw, dict) else {}
    levels_raw = clearance_cfg.get("levels")
    cleaned_levels: dict[str, dict[str, Any]] = {}
    if isinstance(levels_raw, Mapping):
        for level_key, entry in levels_raw.items():
            try:
                level_int = int(level_key)
            except (TypeError, ValueError):
                continue
            if level_int < 1 or level_int > 6:
                continue
            entry_map = entry if isinstance(entry, Mapping) else {}
            roles_raw = entry_map.get("roles")
            cleaned_roles: list[int] = []
            if isinstance(roles_raw, Iterable):
                for role in roles_raw:
                    try:
                        role_int = int(role)
                    except (TypeError, ValueError):
                        continue
                    if role_int not in cleaned_roles:
                        cleaned_roles.append(role_int)
            name_raw = entry_map.get("name") if isinstance(entry_map.get("name"), str) else None
            name_clean = name_raw.strip() if name_raw else ""
            cleaned_entry: dict[str, Any] = {}
            if name_clean:
                cleaned_entry["name"] = name_clean
            if cleaned_roles:
                cleaned_entry["roles"] = cleaned_roles
            if cleaned_entry:
                cleaned_levels[str(level_int)] = cleaned_entry
    if cleaned_levels:
        clearance_cfg["levels"] = cleaned_levels
    else:
        clearance_cfg.pop("levels", None)

    if clearance_cfg:
        settings["clearance"] = clearance_cfg
        payload["clearance"] = clearance_cfg
    else:
        settings.pop("clearance", None)
        payload.pop("clearance", None)

    if (
        links_clean
        or normalise_root_prefix(settings.get("ROOT_PREFIX"))
        or normalise_root_prefix(payload.get("ROOT_PREFIX"))
    ):
        settings["ROOT_PREFIX"] = root_prefix
        payload["ROOT_PREFIX"] = root_prefix
    else:
        settings.pop("ROOT_PREFIX", None)
        payload.pop("ROOT_PREFIX", None)

    try:
        await run_blocking(ensure_guild_archive_structure, gid_int, root_prefix)
    except Exception as exc:  # pragma: no cover - storage connectivity issues
        logger.exception(
            "Failed to prepare archive storage for guild %s", guild_id
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Unable to prepare archive storage for this server. Try again later.",
        ) from exc

    current, etag = read_json(guild_key(guild_id), with_etag=True)
    previous_menu_channel = _extract_menu_channel(current)
    if current:
        backup_json(guild_key(guild_id).split("/")[-1], current)

    client_etag = (payload.get("_meta") or {}).get("etag")
    to_store = {k: v for k, v in payload.items() if k != "_meta"}
    ok = write_json(guild_key(guild_id), to_store, etag=client_etag or etag)
    if not ok:
        raise HTTPException(status_code=409, detail="Config changed on server; refresh and retry.")
    invalidate_config(guild_id)
    try:
        register_archive(gid_int, root_prefix=root_prefix, name=_archive_display_name(settings))
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to update archive link registry for guild %s", guild_id)
    channels_cfg = settings.get("channels") if isinstance(settings.get("channels"), Mapping) else None
    new_menu_channel = _coerce_channel_id(channels_cfg.get("menu_home")) if isinstance(channels_cfg, Mapping) else None
    if new_menu_channel is None:
        new_menu_channel = _coerce_channel_id(settings.get("MENU_CHANNEL_ID"))
    if new_menu_channel is None:
        new_menu_channel = _coerce_channel_id(payload.get("MENU_CHANNEL_ID"))
    should_queue_menu = new_menu_channel is not None and new_menu_channel != previous_menu_channel
    if should_queue_menu:
        queue_payload = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "menu_channel_id": new_menu_channel,
            "trigger": "menu_home_updated",
        }
        try:
            save_json(f"deploy-queue/{gid_int}.json", queue_payload)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to enqueue immediate menu deployment for guild %s", guild_id)
    _invalidate_config_count_cache()
    return {"ok": True}


@app.post("/configs/{guild_id}/deploy")
async def request_guild_deploy(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    if request.session.get("user"):
        await _check_access(request, guild_id)

    try:
        gid_int = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid guild ID.") from exc

    doc, _etag = read_json(guild_key(guild_id), with_etag=True)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No configuration stored for this server yet.")

    menu_channel = _extract_menu_channel(doc)
    if menu_channel is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure a menu channel before deploying.")

    queue_payload = {
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "menu_channel_id": menu_channel,
        "trigger": "manual_dashboard_deploy",
    }
    try:
        save_json(f"deploy-queue/{gid_int}.json", queue_payload)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to enqueue manual menu deployment for guild %s", guild_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Unable to queue deployment. Try again later.",
        ) from exc

    return JSONResponse({
        "ok": True,
        "queued_at": queue_payload["queued_at"],
        "menu_channel_id": menu_channel,
    })


@app.delete("/configs/{guild_id}")
async def delete_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    if request.session.get("user"):
        await _check_access(request, guild_id)

    # Capture the existing document for optional backup before deletion.
    existing, _etag = read_json(guild_key(guild_id), with_etag=True)
    deleted = False
    if existing:
        deleted = True
        try:
            backup_json(guild_key(guild_id).split("/")[-1], existing)
        except Exception:  # pragma: no cover - defensive backup logging
            logger.exception("Failed to create backup before deleting guild %s configuration", guild_id)

    try:
        delete_file(guild_key(guild_id))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to delete guild %s configuration from storage", guild_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Failed to remove configuration from storage.",
        ) from exc

    invalidate_config(guild_id)
    try:
        unregister_archive(int(guild_id))
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to update link registry after deleting guild %s", guild_id)
    _invalidate_config_count_cache()

    return JSONResponse({"ok": True, "deleted": deleted})
