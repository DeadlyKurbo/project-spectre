import os
import json
import logging
import io
import gzip
import re
import unicodedata
import hashlib
import hmac
import secrets
import threading
from secrets import compare_digest
import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote
import html
import base64
import binascii
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any, Callable

import httpx
import jwt
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    Depends,
    status,
    Body,
    Header,
    WebSocket,
    WebSocketDisconnect,
    UploadFile as FastAPIUploadFile,
)
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import psutil

import llm_client
import support_chat
from async_utils import run_blocking
import importlib
import storage_spaces
import archive_access
import archive_index
import archive_lock
from storage_spaces import read_json, write_json, backup_json, list_dir, delete_file, save_json, save_text
from utils.guild_store import request_deploy
from constants import GUILD_ID, ROOT_PREFIX
from bot_control import (
    BOT_CONTROL_ACTIONS,
    BOT_CONTROL_REASON_MAX_LENGTH,
    describe_bot_state,
    get_bot_control,
    get_bot_status,
    set_bot_control,
)
from guild_blacklist import (
    GUILD_BLACKLIST_POLL_SECONDS,
    GUILD_BLACKLIST_REASON_MAX_LENGTH,
    list_blacklisted_guilds,
    normalise_guild_id,
)
from website_users import list_website_users, record_website_user
import zeta_dm
import vpn_blocklist
from config import (
    clean_site_lock_message,
    get_site_lock_state,
    get_system_health_state,
    set_site_lock_state,
    set_system_health_state,
    update_site_lock_message,
    SITE_LOCK_MESSAGE_DEFAULT,
    SITE_LOCK_MESSAGE_MAX_LENGTH,
    SYSTEM_HEALTH_STATUSES,
)
from operator_login import (
    account_name_in_use,
    get_operator_by_account_identifier,
    get_or_create_operator,
    list_operators,
    set_account_name,
    set_password,
    verify_password,
)
from server_config import (
    invalidate_config,
    default_root_prefix_for,
    normalise_root_prefix,
)
from director_portal import load_broadcast_history, record_broadcast
from director_portal import (
    load_file_assignments,
    synchronise_file_assignments,
    update_file_assignment,
)
from owner_portal import (
    OWNER_USER_KEY,
    OWNER_SETTINGS_KEY,
    BROADCAST_PRIORITIES,
    build_change_entry,
    load_owner_settings,
    normalise_broadcast_priority,
    save_owner_settings,
    set_operations_broadcast,
)
from owner_portal import OWNER_USER_KEY as _OWNER_USER_KEY  # keep compat
from owner_portal import (
    ModerationSettings,
    OwnerSettings,
    can_manage_fleet,
    can_manage_chat_access,
    can_manage_portal,
    can_access_chat,
    is_owner,
    validate_discord_id,
)
from admin_roster import (
    AdminBio,
    AdminTeamSettings,
    load_admin_bios,
    load_admin_team_settings,
    normalise_bio_text,
    normalise_clearance_text,
    normalise_rank_text,
    save_admin_bio,
    save_admin_team_settings,
)
from fleet_manager import (
    FleetVessel,
    load_fleet_manifest,
    save_fleet_manifest,
)
from dossier import (
    _archive_root_prefixes,
    _find_existing_item_key,
    _list_files_in,
    _strip_ext,
    ensure_guild_archive_structure,
    enumerate_dossier_files,
    list_items_recursive,
    move_dossier_file,
    read_json,
    read_text,
    read_dossier_body,
    remove_dossier_file,
    describe_dossier_key,
)
from acl import get_required_roles, check_temp_clearance
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
from fdd_fleet_specs import (
    get_fdd_ships,
    get_ship_by_slug,
    normalize_ship_slug,
    save_fdd_ship_spec,
)
from tech_spec_images import (
    list_ship_images,
    save_ship_image,
    get_ship_image_bytes,
    detect_image_format,
    image_format_labels,
    accepted_image_content_types,
)
from definition_images import (
    delete_definition_image,
    get_definition_image_bytes,
    list_definition_images,
    normalize_definition_slug,
    save_definition_image,
)
from server_config import get_server_config
from wallpapers import (
    accepted_image_content_types as accepted_wallpaper_types,
    delete_wallpaper,
    detect_image_format as detect_wallpaper_format,
    get_wallpaper_bytes,
    list_wallpapers,
    normalize_wallpaper_slug,
    save_wallpaper,
)
from war_map import (
    PYRO_SYSTEM_BODIES,
    PYRO_WAR_ORBITAL_LAYOUT,
    PYRO_WAR_SECTORS,
    PYRO_WAR_STATUS_CHOICES,
    PYRO_WAR_STATE_CHOICES,
    PYRO_WAR_STATE_LABELS,
    load_pyro_war_state,
    pyro_war_body_listing,
    save_pyro_war_state,
)
from wasp_map_state import (
    WaspMapConflictError,
    WaspMapOpError,
    load_wasp_map_state,
    update_wasp_map_state,
)
from spectre.restart_policy import (
    compute_next_restart,
    get_process_restart_schedule,
    get_restart_schedule,
    read_restart_state,
)
from app_spectre.routers.moderation_routes import router as moderation_router
from app_spectre.services.moderation_service import get_moderation_service
import url_scramble
import security_shield

logger = logging.getLogger("config_app")
logger.setLevel(logging.INFO)


@dataclass(frozen=True)
class _RuntimeSettings:
    """Runtime configuration loaded from environment variables."""

    client_id: str | None
    client_secret: str | None
    discord_api: str
    bot_token: str | None
    session_cookie_name: str
    session_cookie_same_site: str
    alice_private_message_recipient: str | None

    @classmethod
    def from_env(cls) -> "_RuntimeSettings":
        return cls(
            client_id=os.getenv("DISCORD_CLIENT_ID"),
            client_secret=os.getenv("DISCORD_CLIENT_SECRET"),
            discord_api=os.getenv("DISCORD_API", "https://discord.com/api/v10"),
            bot_token=os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN"),
            session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "session"),
            session_cookie_same_site=os.getenv("SESSION_COOKIE_SAMESITE", "lax"),
            alice_private_message_recipient=(
                os.getenv("ALICE_PRIVATE_MESSAGE_RECIPIENT_ID")
                or os.getenv("ALICE_DM_RECIPIENT_ID")
                or OWNER_USER_KEY
            ),
        )


_RUNTIME_SETTINGS = _RuntimeSettings.from_env()

_OWNER_FLASH_KEY = "owner_flash"
_FLEET_FLASH_KEY = "fleet_flash"
_PANEL_FLASH_KEY = "panel_flash"
_CHAT_ACCESS_FLASH_KEY = "chat_access_flash"
_WAR_STATUS_VALUES = {option["value"] for option in PYRO_WAR_STATUS_CHOICES}
_MAX_TECH_SPEC_IMAGE_BYTES = 5 * 1024 * 1024
_TECH_SPEC_IMAGE_LABELS = image_format_labels()
_TECH_SPEC_ACCEPT_HEADER = ",".join(accepted_image_content_types())
_MAX_DEFINITION_IMAGE_BYTES = 5 * 1024 * 1024
_DEFINITION_IMAGE_LABELS = image_format_labels()
_DEFINITION_ACCEPT_HEADER = ",".join(accepted_image_content_types())
_WALLPAPER_ACCEPT_HEADER = ",".join(accepted_wallpaper_types())
_ALICE_CHAT_LOG_KEY = "alice/chat-log.json"
_ALICE_CHAT_REQUESTS_KEY = "alice/chat-access-requests.json"
_ALICE_CHAT_MAX_MESSAGES = 200
_ALICE_CHAT_MAX_LENGTH = 600
_ALICE_PRIVATE_MESSAGE_KEY = "alice/private-messages.json"
_ALICE_PRIVATE_MESSAGE_MAX = 50
_ALICE_PRIVATE_MESSAGE_RECIPIENT = _RUNTIME_SETTINGS.alice_private_message_recipient
# Display names of ZETA members, so masked callsigns can be assigned even for
# members who are not in the operator registry.
_ZETA_MEMBERS_KEY = "zeta/members.json"
# Anyone can join ZETA by entering a name; the session then carries a guest
# identity, and this registry lists the guests seen in the last 30 days.
_ZETA_GUESTS_KEY = "zeta/guests.json"
_ZETA_GUEST_SESSION_KEY = "zeta_guest"
_ZETA_GUEST_ID_RE = re.compile(r"^zeta[0-9a-f]{32}$")
_ZETA_GUEST_NAME_MAX = 32
_ZETA_GUEST_TTL = timedelta(days=30)
_ZETA_GUEST_TOUCH_INTERVAL = timedelta(hours=1)
# Guests on a VPN, proxy or Tor are turned away (see _zeta_vpn_block); set to 0 to allow them.
_ZETA_VPN_BLOCK_ENABLED = os.getenv("ZETA_BLOCK_VPN_GUESTS", "1").strip() != "0"
# The channel purges messages older than 24 hours whenever it is read or
# written; this sweep also clears them when nobody is using the channel.
_ZETA_PURGE_INTERVAL_SECONDS = 600
# Admins are marked active by every request they make (see
# _touch_admin_presence) and by static/js/admin_presence.js, which pings every
# 45 seconds from any open page; background tabs may stretch that to a minute.
_ADMIN_HEARTBEAT_TIMEOUT = timedelta(seconds=90)
_ADMIN_PRESENCE_LOCK = threading.Lock()
_ADMIN_PRESENCE: dict[str, dict[str, Any]] = {}
_ADMIN_PRESENCE_STORAGE_KEY = "owner/admin-presence.json"
_ADMIN_PRESENCE_LOADED = False
_ADMIN_PRESENCE_PERSIST_INTERVAL = timedelta(seconds=60)
_ADMIN_PRESENCE_PERSISTED_AT: datetime | None = None
_ADMIN_PRESENCE_TOUCH_SECONDS = 20.0
_ADMIN_PRESENCE_LAST_TOUCH: dict[str, float] = {}
_ACTIVITY_LOG_LIMIT = 200
_ACTIVITY_LOG_LOCK = threading.Lock()
_ACTIVITY_LOGS: deque[dict[str, Any]] = deque(maxlen=_ACTIVITY_LOG_LIMIT)
_ACTIVITY_LOG_STORAGE_KEY = "owner/admin-activity-log.json"
_ACTIVITY_LOG_LOADED = False
_ACTIVITY_SUBSCRIBERS_LOCK = threading.Lock()
_ACTIVITY_SUBSCRIBERS: set[asyncio.Queue[list[dict[str, Any]]]] = set()
_ACTIVITY_SOCKET_SUBSCRIBERS_LOCK = threading.Lock()
_ACTIVITY_SOCKET_SUBSCRIBERS: set[WebSocket] = set()
_SITE_VISIT_LOG_LOCK = threading.Lock()
_SITE_VISIT_STORAGE_KEY = "owner/site-visit-tracker.json"
_SITE_VISIT_DAILY: dict[str, int] = {}
_SITE_VISIT_SEEN_KEYS: dict[str, set[str]] = {}
_SITE_VISIT_RECENT: dict[str, dict[str, Any]] = {}
_SITE_VISIT_LOADED = False
# Visitor keys come from client-controlled headers, so cap what we keep in
# memory and how often we write the tracker back to storage.
_SITE_VISIT_RECENT_MAX = 2_000
_SITE_VISIT_SEEN_MAX_PER_DAY = 50_000
_SITE_VISIT_MAINTENANCE_INTERVAL = timedelta(minutes=1)
_SITE_VISIT_LAST_MAINTENANCE: datetime | None = None
_MONITORED_OWNERS_LOCK = threading.Lock()
_MONITORED_OWNERS_STORAGE_KEY = "owner/monitored-guild-owners.json"
_MONITORED_OWNERS_CACHE_TTL = timedelta(minutes=5)
_MONITORED_OWNERS_CACHE: dict[str, Any] = {
    "fetched_at": None,
    "owners": [],
}
def _resolve_jwt_secret() -> str:
    configured = os.getenv("JWT_SECRET")
    if configured:
        if len(configured) < 32:
            logger.warning("JWT_SECRET is shorter than 32 characters; use a longer random value in production.")
        return configured

    logger.warning("JWT_SECRET not set; using an ephemeral per-process signing key.")
    return secrets.token_urlsafe(48)


_JWT_SECRET = _resolve_jwt_secret()
_JWT_ALGORITHM = "HS256"
_JWT_TTL = timedelta(hours=8)
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

_WALLPAPER_PAGES: dict[str, str] = {
    "dashboard": "Dashboard",
    "owner": "Owner portal",
    "director": "Director console",
    "panel": "Guild panel",
    "personnel-board": "Personnel dossiers",
    "admin-team": "Admin team",
    "fleet": "Fleet manager",
    "fdd-tech-specs": "Tech specs",
    "war-manager": "War manager",
    "pyro-war": "Pyro war (public)",
    "pyro-war-admin": "Pyro war admin",
    "helldivers": "Helldivers intel",
    "helldivers-placeholder": "Helldivers access gate",
}

# The API docs list every endpoint, so they are served to portal admins only
# (see api_docs) instead of FastAPI's public /docs, /redoc and /openapi.json.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(moderation_router)
auth = HTTPBasic(auto_error=False)
try:
    templates = Jinja2Templates(directory="templates")
except AssertionError:
    templates = None
if templates is not None:
    # templates/_admin_presence.html: the Online keep-alive is only sent to admins.
    templates.env.globals["admin_presence_enabled"] = lambda request: _session_portal_admin(request) is not None
    templates.env.globals["zeta_ping_enabled"] = lambda request: _zeta_ping_enabled(request)
    # templates/_wasp_player.html: the playlist for pages whose route does not pass one.
    templates.env.globals["wasp_player_tracks"] = lambda: _list_uploaded_wasp_tracks(newest_first=False)

if os.path.isdir("images"):
    app.mount("/images", StaticFiles(directory="images"), name="images")
else:
    logger.warning("images directory is missing; /images assets will not be served.")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logger.warning("static directory is missing; onboarding assets will not be served.")

CLIENT_ID = _RUNTIME_SETTINGS.client_id
CLIENT_SECRET = _RUNTIME_SETTINGS.client_secret
DISCORD_API = _RUNTIME_SETTINGS.discord_api
BOT_TOKEN = _RUNTIME_SETTINGS.bot_token
GUILD_CACHE_TTL_SECONDS = 60
GUILD_CACHE_MAX_ENTRIES = 256
_GUILD_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_GUILD_CACHE_LOCK = threading.Lock()
# Several pages need the bot's server list and Discord rate limits that
# endpoint hard, so share one copy for a short while.
BOT_GUILDS_CACHE_TTL_SECONDS = 60.0
_bot_guilds_cache: tuple[float, list[dict[str, Any]]] | None = None
# Longest Discord rate-limit window worth waiting out before giving up on a call.
DISCORD_RATE_LIMIT_MAX_WAIT_SECONDS = 10.0

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
redirect_path = "/auth/callback"
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
    path = redirect_path or "/auth/callback"
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
# Cloudflare terminates HTTPS, so keep secure cookies enabled.
# Use SESSION_COOKIE_SAMESITE to tune policy per deployment (defaults to lax).
SESSION_SECRET = os.getenv("SESSION_SECRET") or ""
if not SESSION_SECRET:
    logger.warning(
        "SESSION_SECRET not set; using a random per-process key, so everyone is signed out on each restart."
    )
    SESSION_SECRET = secrets.token_urlsafe(32)
elif len(SESSION_SECRET) < 32:
    # Anyone who guesses it can forge an admin session cookie.
    logger.warning("SESSION_SECRET is shorter than 32 characters; use a long random value in production.")
SESSION_COOKIE_NAME = _RUNTIME_SETTINGS.session_cookie_name


def _normalize_same_site(raw_value: str | None) -> str:
    value = (raw_value or "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        logger.warning(
            "SESSION_COOKIE_SAMESITE must be lax, strict, or none; received %r. Falling back to lax.",
            raw_value,
        )
        return "lax"
    return value


SESSION_COOKIE_SAMESITE = _normalize_same_site(_RUNTIME_SETTINGS.session_cookie_same_site)
TOS_CONSENT_COOKIE_NAME = "spectre_tos_accepted"
TOS_CONSENT_COOKIE_VALUE = "1"
TOS_CONSENT_MAX_AGE_SECONDS = 60 * 60 * 24 * 365

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

ACCENT = "#8ea784"  # SPECTRE green, shared by every page except A.L.I.C.E. and W.A.S.P.
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

_MAINTENANCE_BYPASS_PATHS = {"/login", "/auth/callback", "/callback"}
# The maintenance screen carries the W.A.S.P. player too, so its files and tracks
# stay reachable while the lock is active.
_MAINTENANCE_PLAYER_PATHS = {
    "/static/js/wasp_audio.js",
    "/static/js/wasp_global_player.js",
    "/static/wasp_global_player.css",
}
_MAINTENANCE_PLAYER_MEDIA_PREFIX = "/media/wasp/"


def _is_maintenance_player_path(path: str) -> bool:
    if path in _MAINTENANCE_PLAYER_PATHS:
        return True
    track = path[len(_MAINTENANCE_PLAYER_MEDIA_PREFIX):] if path.startswith(_MAINTENANCE_PLAYER_MEDIA_PREFIX) else ""
    return bool(track) and "/" not in track


class MaintenanceLockMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces the maintenance lock for non-admin visitors."""

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - exercised via tests
        try:
            _record_site_visit(request)
        except Exception:
            logger.exception("Failed to record site visit telemetry")
        try:
            # Any page or API call by an admin shows them as online on the Contact page.
            await _touch_admin_presence(request)
        except Exception:
            logger.exception("Failed to record admin presence")
        path = request.url.path
        if path in _MAINTENANCE_BYPASS_PATHS or _is_maintenance_player_path(path):
            return await call_next(request)

        state = get_site_lock_state()
        request.state.site_lock_state = state

        if not state.get("enabled"):
            return await call_next(request)

        if (
            _session_user_is_admin(request)
            or _basic_auth_allows_admin(request)
            or _session_user_matches_lock_actor(request, state)
        ):
            return await call_next(request)

        return _build_maintenance_response(state)


# Add the maintenance middleware before sessions so session data is available.
app.add_middleware(MaintenanceLockMiddleware)

_WEBSITE_BLOCK_REFRESH_SECONDS = 30
_website_blocks: dict[str, dict[str, Any]] = {}
_website_blocks_loaded_at: float | None = None
_website_blocks_lock = asyncio.Lock()


async def _active_website_blocks() -> dict[str, dict[str, Any]]:
    """Website bans/suspensions keyed by account ID, refreshed at most every 30s."""

    global _website_blocks, _website_blocks_loaded_at
    service = get_moderation_service()
    loaded_at = _website_blocks_loaded_at
    fresh = (
        loaded_at is not None
        and time.monotonic() - loaded_at < _WEBSITE_BLOCK_REFRESH_SECONDS
        and service.website_blocks_changed_at <= loaded_at
    )
    if fresh:
        return _website_blocks
    async with _website_blocks_lock:
        if _website_blocks_loaded_at == loaded_at:
            try:
                rows = await service.website_blocks()
                _website_blocks = {str(row["userId"]): row for row in rows}
            except Exception:
                logger.exception("Failed to refresh website sanctions; keeping the previous list")
            _website_blocks_loaded_at = time.monotonic()
    return _website_blocks


class WebsiteSanctionMiddleware(BaseHTTPMiddleware):
    """Sign out accounts with an active website ban or suspension."""

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - exercised via tests
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        try:
            user = request.session.get("user")
        except (AssertionError, RuntimeError):
            return await call_next(request)
        user_id = _clean_discord_id(user.get("id")) if isinstance(user, dict) else None
        if not user_id or is_owner(user_id):
            return await call_next(request)
        block = (await _active_website_blocks()).get(user_id)
        if not block:
            return await call_next(request)
        request.session.clear()
        return _build_website_block_response(block)


app.add_middleware(WebsiteSanctionMiddleware)


@lru_cache(maxsize=1)
def _wasp_map_client_asset_version() -> str:
    """Content hash of the map's JS/CSS so each deploy busts browser caches."""
    static_root = Path(__file__).resolve().parent / "static"
    digest = hashlib.sha256()
    for relative in ("js/wasp_map.js", "wasp_map.css"):
        try:
            digest.update((static_root / relative).read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:12]


class TosGateNoCacheMiddleware(BaseHTTPMiddleware):
    """Keep the ToS gate script out of long-lived browser or CDN caches."""

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - integration
        response = await call_next(request)
        path = request.url.path
        if path == "/static/js/tos_gate.js":
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(TosGateNoCacheMiddleware)


# Only the landing page may show up in search results; everything else is kept
# out of search indexes so it cannot be found by dorking.
_SEARCH_INDEXABLE_PATHS = frozenset({"/"})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline browser hardening headers to every response."""

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - integration
        response = await call_next(request)
        if request.url.path not in _SEARCH_INDEXABLE_PATHS:
            response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # The site is HTTPS-only (secure session cookie); browsers ignore this over plain HTTP.
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "media-src 'self' data: blob: https:; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://discord.com https://discordapp.com wss:; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ---- Security shield: per-IP rate limits, automatic blocks and attack alerts ----
# See security_shield.py and docs/security-shield.md. Alerts land in the
# director's activity feed and, when configured, a Discord channel.
_SECURITY_BLOCKS_STORAGE_KEY = "owner/security-blocks.json"
_SECURITY_ALERT_WEBHOOK_URL = (os.getenv("SECURITY_ALERT_WEBHOOK_URL") or "").strip()
_SECURITY_ALERT_CHANNEL_ID = (os.getenv("SECURITY_ALERT_CHANNEL_ID") or "").strip()
# Prepended to critical alerts, e.g. "<@&role id>" to ping the admin role.
_SECURITY_ALERT_MENTION = (os.getenv("SECURITY_ALERT_MENTION") or "").strip()
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_background(coro) -> None:
    """Run ``coro`` on the current event loop without waiting for it."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _send_security_alert(event: Mapping[str, Any]) -> None:
    # Summaries quote attacker-chosen paths: keep them in a code span so they
    # cannot add markdown links, and only ever ping the configured mention.
    summary = str(event.get("summary") or "Security incident").replace("`", "'")[:1700]
    text = f"\N{SHIELD} **Spectre security alert** \N{EM DASH} `{summary}`"
    allowed: dict[str, list[str]] = {"parse": []}
    if _SECURITY_ALERT_MENTION and event.get("severity") == "critical":
        text = f"{_SECURITY_ALERT_MENTION} {text}"
        allowed["roles"] = re.findall(r"<@&(\d+)>", _SECURITY_ALERT_MENTION)
        allowed["users"] = re.findall(r"<@!?(\d+)>", _SECURITY_ALERT_MENTION)
    payload = {"content": text[:1950], "allowed_mentions": allowed}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if _SECURITY_ALERT_WEBHOOK_URL:
                response = await client.post(_SECURITY_ALERT_WEBHOOK_URL, json=payload)
            else:
                response = await client.post(
                    f"{DISCORD_API}/channels/{_SECURITY_ALERT_CHANNEL_ID}/messages",
                    headers={"Authorization": f"Bot {BOT_TOKEN}"},
                    json=payload,
                )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Failed to deliver a security alert to Discord", exc_info=True)


def _handle_security_alert(event: dict[str, Any]) -> None:
    _log_activity(
        "security-alert",
        str(event.get("summary") or "Security incident"),
        str(event.get("ip") or "-"),
        background=True,
    )
    if _SECURITY_ALERT_WEBHOOK_URL or (_SECURITY_ALERT_CHANNEL_ID.isdigit() and BOT_TOKEN):
        _spawn_background(_send_security_alert(event))


SECURITY_SHIELD = security_shield.SecurityShield(
    store=security_shield.CallbackBlockStore(
        loader=lambda: read_json(_SECURITY_BLOCKS_STORAGE_KEY),
        saver=lambda payload: save_json(_SECURITY_BLOCKS_STORAGE_KEY, payload),
    ),
    on_alert=_handle_security_alert,
)


def _shield_trusts_session(scope: Mapping[str, Any]) -> bool:
    """Signed-in portal admins are never rate limited or blocked."""

    session = scope.get("session")
    user = session.get("user") if isinstance(session, dict) else None
    user_id = _clean_discord_id(user.get("id")) if isinstance(user, dict) else None
    return bool(user_id) and _user_is_portal_admin(user_id)


# Inside the session middleware so admins can be recognised, outside everything
# else so blocked clients cost as little as possible.
app.add_middleware(
    security_shield.ShieldMiddleware,
    shield=SECURITY_SHIELD,
    trusted_session=_shield_trusts_session,
    trusted_origins=[DASHBOARD_ORIGIN] if DASHBOARD_ORIGIN else [],
)

# Add session middleware with cross-site friendly settings
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site=SESSION_COOKIE_SAMESITE,
    https_only=True,
    session_cookie=SESSION_COOKIE_NAME,
)


def _url_hosts_from_env() -> set[str]:
    hosts: set[str] = set()
    for value in (DASHBOARD_ORIGIN, REDIRECT_URI, os.getenv("SPECTRE_DASHBOARD_URL")):
        netloc = urlparse(value or "").netloc
        if netloc:
            hosts.add(netloc.lower())
    return hosts


def _build_url_scrambler() -> url_scramble.PathScrambler | None:
    secret = url_scramble.configured_secret()
    if not secret:
        return None
    segments, top_level = url_scramble.collect_route_segments(app.routes)
    public_paths = set(url_scramble.DEFAULT_PUBLIC_PATHS)
    redirect_path = urlparse(REDIRECT_URI or "").path
    if redirect_path:
        public_paths.add(redirect_path)
    scrambler = url_scramble.PathScrambler(secret, segments, top_level, public_paths=public_paths)
    logger.info(
        "URL scrambling is on; readable paths now answer 404. Entry points: %s",
        ", ".join(f"{path} -> {scrambler.scramble_path(path)}" for path in ("/dashboard", "/admin", "/director", "/owner")),
    )
    return scrambler


# Added last so it is the outermost layer: every other middleware and route
# keeps working with the real paths. Guild configs are edited and saved back
# verbatim, so their JSON is never rewritten.
app.add_middleware(
    url_scramble.ScrambleMiddleware,
    scrambler_factory=_build_url_scrambler,
    own_hosts=_url_hosts_from_env(),
    json_passthrough_prefixes=("/configs/",),
)

_HEALTH_STATUS_OPTIONS = {
    "online": {
        "label": SYSTEM_HEALTH_STATUSES.get("online", "Online"),
        "chip": "status-chip--active",
        "description": "Systems are responding normally.",
        "default_note": "No anomalies detected.",
    },
    "maintenance": {
        "label": SYSTEM_HEALTH_STATUSES.get("maintenance", "Maintenance"),
        "chip": "status-chip--retrofit",
        "description": "Maintenance work or deployments in progress.",
        "default_note": "",
    },
    "degraded": {
        "label": SYSTEM_HEALTH_STATUSES.get("degraded", "Degraded"),
        "chip": "status-chip--in-dock",
        "description": "Limited capability or elevated latency detected.",
        "default_note": "",
    },
    "offline": {
        "label": SYSTEM_HEALTH_STATUSES.get("offline", "Offline"),
        "chip": "status-chip--lost",
        "description": "The bot is offline or unreachable.",
        "default_note": "",
    },
}

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
_PROCESS_START_TIME: datetime | None = None


def _invalidate_config_count_cache() -> None:
    """Mark cached configuration document totals as stale."""

    _configs_cache["value"] = None
    _configs_cache["timestamp"] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_process_start_time() -> datetime:
    global _PROCESS_START_TIME

    if _PROCESS_START_TIME is None:
        try:
            process = psutil.Process()
            _PROCESS_START_TIME = datetime.fromtimestamp(
                process.create_time(), tz=timezone.utc
            )
        except Exception:
            logger.exception("Failed to determine process start time for uptime stats")
            _PROCESS_START_TIME = _now()

    return _PROCESS_START_TIME


def _format_duration_compact(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")

    if not parts:
        parts.append(f"{seconds}s")
    elif len(parts) < 2 and seconds:
        parts.append(f"{seconds}s")

    return " ".join(parts)


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


def _normalise_role_id_list(raw: object) -> list[int]:
    if not isinstance(raw, Iterable):
        return []
    cleaned: list[int] = []
    for item in raw:
        try:
            role_int = int(item)
        except (TypeError, ValueError):
            continue
        if role_int > 0 and role_int not in cleaned:
            cleaned.append(role_int)
    return cleaned


def _normalise_mission_reports_settings(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}

    cleaned: dict[str, Any] = {}
    enabled_raw = raw.get("enabled")
    if isinstance(enabled_raw, bool):
        cleaned["enabled"] = enabled_raw

    submitter_roles = _normalise_role_id_list(raw.get("submitter_roles"))
    if submitter_roles:
        cleaned["submitter_roles"] = submitter_roles

    reviewer_roles = _normalise_role_id_list(raw.get("reviewer_roles"))
    if reviewer_roles:
        cleaned["reviewer_roles"] = reviewer_roles

    review_channel = _coerce_channel_id(raw.get("review_channel"))
    if review_channel is not None:
        cleaned["review_channel"] = review_channel

    menu_channel = _coerce_channel_id(raw.get("menu_channel"))
    if menu_channel is not None:
        cleaned["menu_channel"] = menu_channel

    menu_clean = _normalise_menu_settings(raw.get("menu"))
    if menu_clean:
        cleaned["menu"] = menu_clean

    archive_category = _clean_text_value(raw.get("archive_category"), limit=128)
    if archive_category:
        cleaned["archive_category"] = archive_category

    try:
        default_clearance = int(raw.get("default_clearance_role"))  # type: ignore[arg-type]
        if default_clearance > 0:
            cleaned["default_clearance_role"] = default_clearance
    except (TypeError, ValueError):
        pass

    return cleaned


def _normalise_access_sequence_settings(raw: object) -> dict[str, bool | float]:
    if not isinstance(raw, Mapping):
        return {}

    cleaned: dict[str, bool | float] = {}
    enabled_raw = raw.get("enabled")
    if isinstance(enabled_raw, bool):
        cleaned["enabled"] = enabled_raw

    chance_raw = raw.get("chance_percent")
    if isinstance(chance_raw, str):
        chance_raw = chance_raw.strip()
    try:
        chance = float(chance_raw)
    except (TypeError, ValueError):
        chance = None
    if chance is not None:
        cleaned["chance_percent"] = max(0.0, min(100.0, chance))

    return cleaned


def _normalise_protocol_settings(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, Mapping):
        return {}

    def _clean_code(value: object) -> str | None:
        text = _clean_text_value(value, limit=128)
        return text

    cleaned: dict[str, dict[str, str]] = {}

    epsilon_cfg = raw.get("epsilon")
    if isinstance(epsilon_cfg, Mapping):
        epsilon_clean: dict[str, str] = {}
        for key in ("launch_code", "owner_code", "xo_code", "fleet_code"):
            code_value = _clean_code(epsilon_cfg.get(key))
            if code_value:
                epsilon_clean[key] = code_value
        if epsilon_clean:
            cleaned["epsilon"] = epsilon_clean

    omega_cfg = raw.get("omega")
    if isinstance(omega_cfg, Mapping):
        omega_clean: dict[str, str] = {}
        for key in ("fragment_one", "fragment_two"):
            fragment_value = _clean_code(omega_cfg.get(key))
            if fragment_value:
                omega_clean[key] = fragment_value
        if omega_clean:
            cleaned["omega"] = omega_clean

    return cleaned


def _normalise_admin_settings(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}

    cleaned: dict[str, Any] = {}

    log_channel = _coerce_channel_id(raw.get("log_channel"))
    if log_channel is not None:
        cleaned["log_channel"] = log_channel

    raw_events = raw.get("audit_events")
    valid_events = {
        "file_access",
        "file_access_denied",
        "file_upload",
        "file_delete",
        "file_restore",
        "archivist_add",
        "archivist_delete",
        "category_delete",
        "clearance_change",
        "backup_restore",
        "archivist_edit",
        "trainee_submission",
        "archive_lockdown",
        "mission_report_submit",
        "mission_report_review",
        "mission_report_archive",
    }
    audit_events: dict[str, bool] = {}
    if isinstance(raw_events, Mapping):
        for key in valid_events:
            value = raw_events.get(key)
            if isinstance(value, bool):
                audit_events[key] = value
    if audit_events:
        cleaned["audit_events"] = audit_events

    raw_safeguards = raw.get("safeguards")
    safeguard_keys = {
        "mass_delete_protection",
        "suspicious_activity_alerts",
        "require_dual_approval_deletes",
        "block_offhours_access",
        "require_owner_approval_archivist",
        "lockout_after_failed_access",
        "alert_on_clearance_escalation",
        "require_justification_for_deletes",
        "cooldown_between_bulk_ops",
        "quarantine_new_uploads",
    }
    safeguards: dict[str, bool] = {}
    if isinstance(raw_safeguards, Mapping):
        for key in safeguard_keys:
            value = raw_safeguards.get(key)
            if isinstance(value, bool):
                safeguards[key] = value
    if safeguards:
        cleaned["safeguards"] = safeguards

    raw_safeguard_config = raw.get("safeguard_config")
    if isinstance(raw_safeguard_config, Mapping):
        safeguard_config: dict[str, Any] = {}
        alert_role = _coerce_channel_id(raw_safeguard_config.get("alert_role"))
        if alert_role is not None:
            safeguard_config["alert_role"] = str(alert_role)
        offhours_start = raw_safeguard_config.get("offhours_start")
        if isinstance(offhours_start, str) and offhours_start.strip():
            safeguard_config["offhours_start"] = offhours_start.strip()[:8]
        offhours_end = raw_safeguard_config.get("offhours_end")
        if isinstance(offhours_end, str) and offhours_end.strip():
            safeguard_config["offhours_end"] = offhours_end.strip()[:8]
        lockout_attempts = raw_safeguard_config.get("lockout_attempts")
        if isinstance(lockout_attempts, (int, float)) and 3 <= lockout_attempts <= 20:
            safeguard_config["lockout_attempts"] = int(lockout_attempts)
        lockout_minutes = raw_safeguard_config.get("lockout_minutes")
        if isinstance(lockout_minutes, (int, float)) and 5 <= lockout_minutes <= 120:
            safeguard_config["lockout_minutes"] = int(lockout_minutes)
        bulk_cooldown = raw_safeguard_config.get("bulk_cooldown_seconds")
        if isinstance(bulk_cooldown, (int, float)) and 10 <= bulk_cooldown <= 600:
            safeguard_config["bulk_cooldown_seconds"] = int(bulk_cooldown)
        quarantine_approver = _coerce_channel_id(raw_safeguard_config.get("quarantine_approver_role"))
        if quarantine_approver is not None:
            safeguard_config["quarantine_approver_role"] = str(quarantine_approver)
        dual_approval = _coerce_channel_id(raw_safeguard_config.get("dual_approval_role"))
        if dual_approval is not None:
            safeguard_config["dual_approval_role"] = str(dual_approval)
        if safeguard_config:
            cleaned["safeguard_config"] = safeguard_config

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


def _env_required_secret(key: str) -> str:
    value = os.getenv(key)
    if value is None or not value.strip():
        logger.warning("%s not set; HTTP Basic dashboard access is disabled.", key)
        return ""
    return value


ADMIN_USER = _env_required_secret("DASHBOARD_USERNAME")
ADMIN_PASS = _env_required_secret("DASHBOARD_PASSWORD")


_UPLOAD_FILE_CLASSES = (FastAPIUploadFile, StarletteUploadFile)


def _coerce_upload_file(value: Any):
    """Return a valid upload file object when ``value`` quacks like one."""

    if isinstance(value, _UPLOAD_FILE_CLASSES):
        return value
    return None


def _join_with_or(options: Iterable[str]) -> str:
    items = [str(opt).strip() for opt in options if str(opt).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def _definition_manifest() -> dict[str, dict[str, str]]:
    try:
        return list_definition_images()
    except Exception:
        logger.exception("Failed to load definition images manifest")
        return {}


def _wallpaper_manifest() -> dict[str, dict[str, str]]:
    try:
        return list_wallpapers()
    except Exception:
        logger.exception("Failed to load wallpaper manifest")
        return {}


def _definition_image_url(
    slug: str, manifest: dict[str, dict[str, str]] | None = None
) -> str | None:
    normalized = normalize_definition_slug(slug)
    if not normalized:
        return None

    manifest = manifest if isinstance(manifest, dict) else _definition_manifest()
    entry = manifest.get(normalized)
    if not entry:
        return None

    cache_buster = entry.get("updated_at")
    suffix = f"?v={quote(cache_buster)}" if cache_buster else ""
    return f"/branding/definitions/{quote(normalized)}{suffix}"


def _definition_image_entries(manifest: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for slug, meta in manifest.items():
        url = _definition_image_url(slug, manifest)
        entries.append(
            {
                "slug": slug,
                "url": url,
                "updated_at": meta.get("updated_at", ""),
                "content_type": meta.get("content_type", ""),
            }
        )
    entries.sort(key=lambda entry: entry.get("slug", ""))
    return entries


def _definition_label_suggestions(
    manifest: dict[str, dict[str, str]]
) -> list[str]:
    suggestions: set[str] = set()
    defaults = {"hq", "spectre", BRAND}
    for candidate in defaults:
        normalized = normalize_definition_slug(candidate)
        if normalized:
            suggestions.add(normalized)

    for slug in manifest.keys():
        normalized = normalize_definition_slug(slug)
        if normalized:
            suggestions.add(normalized)

    return sorted(suggestions)


def _brand_image_url(manifest: dict[str, dict[str, str]] | None = None) -> str | None:
    return _definition_image_url(BRAND, manifest)


def _wallpaper_url(
    slug: str, manifest: dict[str, dict[str, str]] | None = None
) -> str | None:
    normalized = normalize_wallpaper_slug(slug)
    if not normalized:
        return None

    manifest = manifest if isinstance(manifest, dict) else _wallpaper_manifest()
    entry = manifest.get(normalized)
    if not entry:
        return None

    cache_buster = entry.get("updated_at")
    suffix = f"?v={quote(cache_buster)}" if cache_buster else ""
    return f"/branding/wallpapers/{quote(normalized)}{suffix}"


def _wallpaper_entries(
    manifest: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    manifest = manifest if isinstance(manifest, dict) else _wallpaper_manifest()
    entries: list[dict[str, str]] = []
    for slug, label in _WALLPAPER_PAGES.items():
        url = _wallpaper_url(slug, manifest)
        meta = manifest.get(slug, {}) if isinstance(manifest, dict) else {}
        entries.append(
            {
                "slug": slug,
                "label": label,
                "url": url,
                "updated_at": meta.get("updated_at", ""),
                "content_type": meta.get("content_type", ""),
            }
        )
    return entries


def _chat_access_prompt_context(request: Request | None) -> dict[str, object]:
    if not isinstance(request, Request):
        return {}

    user = request.session.get("user") or {}
    user_id = _clean_discord_id(user.get("id"))
    settings, _etag = load_owner_settings()

    if not can_manage_chat_access(user_id, settings.managers):
        return {}

    requests, etag = _load_chat_access_requests(with_etag=True)
    if not requests:
        return {}

    pending: list[dict[str, str]] = []
    stale = False
    for entry in requests:
        if can_access_chat(entry.get("user_id"), settings.managers, settings.chat_access):
            stale = True
            continue
        pending.append(entry)

    if stale:
        _save_chat_access_requests(pending, etag=etag)

    if not pending:
        return {}

    return {"chat_access_requests": pending}


def _inject_wallpaper(
    context: dict[str, object], slug: str, manifest: dict[str, dict[str, str]] | None = None
) -> dict[str, object]:
    context = dict(context)
    context["wallpaper_url"] = _wallpaper_url(slug, manifest)
    if "request" in context:
        context.update(_chat_access_prompt_context(context.get("request")))
    return context


def _truncate_personnel_text(value: str, *, limit: int = 220) -> str:
    compact = " ".join(str(value).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _humanize_personnel_name(raw: str) -> str:
    cleaned = raw.replace("_", " ").replace("-", " ").strip().strip("/")
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    words = [segment for segment in cleaned.split(" ") if segment]
    return " ".join(word.capitalize() for word in words) or raw


def _extract_personnel_fields(payload: object) -> tuple[str | None, str | None, str | None, list[str]]:
    summary: str | None = None
    assignment: str | None = None
    clearance: str | None = None
    tags: list[str] = []

    def _maybe_take(data: dict, keys: tuple[str, ...]) -> str | None:
        for key in keys:
            raw_val = data.get(key)
            if isinstance(raw_val, str):
                cleaned = raw_val.strip()
                if cleaned:
                    return cleaned
        return None

    if isinstance(payload, dict):
        summary = _maybe_take(payload, ("summary", "bio", "profile", "notes", "description"))
        assignment = _maybe_take(payload, ("assignment", "role", "position", "unit"))
        clearance = _maybe_take(payload, ("clearance", "classification", "access_level", "level"))

        for label in ("unit", "location", "region", "station", "specialty"):
            raw = payload.get(label)
            if isinstance(raw, str) and raw.strip():
                tags.append(raw.strip())
    elif isinstance(payload, (list, tuple)):
        summary = _truncate_personnel_text("; ".join(str(item) for item in payload[:5]))
    elif payload is not None:
        summary = _truncate_personnel_text(str(payload))

    return summary, assignment, clearance, tags


def _default_personnel_records() -> list[dict[str, object]]:
    records = [
        {
            "name": "Cmdr. Nyla Reyes",
            "handle": "Ares-12",
            "assignment": "Field Intelligence Lead",
            "clearance": "Omega",
            "status": "Active dossier",
            "summary": "Coordinates deep field reconnaissance cells and validates inbound human intelligence before it reaches the Directorate.",
            "last_updated": "Today",
            "tags": ["Recon", "Signal triage"],
            "priority": True,
        },
        {
            "name": "Lt. Maro Venk",
            "handle": "Warden-3",
            "assignment": "Asset Protection",
            "clearance": "Gamma",
            "status": "On rotation",
            "summary": "Maintains custody protocols for high-value sources and escorts analysts during forward deployments.",
            "last_updated": "2d ago",
            "tags": ["Protective detail", "Field-ready"],
            "priority": False,
        },
        {
            "name": "Analyst Imani Cole",
            "handle": "Cipher-8",
            "assignment": "Signals Analysis",
            "clearance": "Beta",
            "status": "Review scheduled",
            "summary": "Owns the red-team review queue for intercepted traffic; specializes in adversary infrastructure mapping.",
            "last_updated": "4h ago",
            "tags": ["SIGINT", "Red-team"],
            "priority": True,
        },
        {
            "name": "Operative Hale Okada",
            "handle": "Specter-21",
            "assignment": "Special Projects",
            "clearance": "Alpha",
            "status": "Mission assigned",
            "summary": "Embedded with the expeditionary group handling emergent technologies; requests tracked by Directorate liaison.",
            "last_updated": "6h ago",
            "tags": ["Expeditionary", "R&D liaison"],
            "priority": True,
        },
        {
            "name": "Officer Nira Sato",
            "handle": "Harbor-19",
            "assignment": "Logistics",
            "clearance": "Unclassified",
            "status": "Active dossier",
            "summary": "Oversees secure material routing and maintains the rapid-deploy supply cache for coastal detachments.",
            "last_updated": "1d ago",
            "tags": ["Logistics", "Coastal"],
            "priority": False,
        },
        {
            "name": "Archivist Tomas Vale",
            "handle": "Ledger-5",
            "assignment": "Records Control",
            "clearance": "Beta",
            "status": "Flagged for audit",
            "summary": "Maintains the evidentiary trail for personnel updates and validates cross-guild access requests.",
            "last_updated": "8h ago",
            "tags": ["Audit", "Records"],
            "priority": False,
        },
    ]

    for record in records:
        status_value = str(record.get("status") or "").lower()
        record["review"] = status_value.startswith("review") or status_value.startswith("flagged")

    return records


def _load_personnel_records(guild_id: int | None = None) -> tuple[list[dict[str, object]], str | None]:
    records: list[dict[str, object]] = []
    notice: str | None = None

    try:
        dossier_items = list_items_recursive("personnel", max_items=200, guild_id=guild_id)
    except Exception:
        logger.exception("Failed to list personnel dossier items")
        return _default_personnel_records(), "Unable to reach dossier storage right now. Showing a curated layout preview."

    if not dossier_items:
        return _default_personnel_records(), "No personnel dossiers found yet. Displaying the layout with sample records."

    for slug in dossier_items:
        record: dict[str, object] = {
            "name": _humanize_personnel_name(slug),
            "handle": slug,
            "assignment": None,
            "clearance": "Unclassified",
            "status": "Active dossier",
            "summary": "Awaiting analyst summary.",
            "last_updated": None,
            "tags": [],
            "priority": False,
        }

        key = None
        ext = None
        try:
            found = _find_existing_item_key("personnel", slug, guild_id=guild_id)
            if found:
                key, ext = found
                record["key"] = key
        except Exception:
            logger.exception("Failed to resolve dossier key for personnel item %r", slug)

        payload: object | None = None
        if key and ext:
            try:
                payload = read_json(key) if ext == ".json" else read_text(key)
            except Exception:
                logger.exception("Failed to read dossier payload for %r", key)

        summary, assignment, clearance, tags = _extract_personnel_fields(payload)
        if summary:
            record["summary"] = _truncate_personnel_text(summary)
        if assignment:
            record["assignment"] = assignment
        if clearance:
            record["clearance"] = clearance.title()
        if tags:
            record["tags"] = tags

        status_hint = None
        if isinstance(payload, dict):
            status_hint = payload.get("status") or payload.get("state")
            last_updated = payload.get("updated_at") or payload.get("reviewed_at")
            if isinstance(last_updated, str) and last_updated.strip():
                record["last_updated"] = last_updated.strip()
        if isinstance(status_hint, str) and status_hint.strip():
            record["status"] = status_hint.strip().capitalize()

        status_value = str(record.get("status") or "").strip()
        if status_value:
            record["status"] = status_value
        normalized_status = status_value.lower()
        record["review"] = normalized_status.startswith("review") or normalized_status.startswith(
            "flagged"
        )

        high_clearance = str(record.get("clearance") or "").lower()
        if any(level in high_clearance for level in ("omega", "alpha", "gamma", "beta")):
            record["priority"] = True

        records.append(record)

    return records, notice


def _summarise_personnel_records(records: list[dict[str, object]]) -> dict[str, int]:
    total = len(records)
    priority = sum(1 for rec in records if rec.get("priority"))
    review_queue = sum(
        1
        for rec in records
        if rec.get("review")
        or str(rec.get("status", "")).lower().startswith(("review", "flagged"))
    )
    assignments = sum(1 for rec in records if rec.get("assignment"))
    return {
        "total": total,
        "priority": priority,
        "review": review_queue,
        "assigned": assignments,
    }


def require_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(auth)):
    if request.session.get("user"):
        return True
    if ADMIN_USER and ADMIN_PASS and creds and (
        compare_digest(creds.username, ADMIN_USER)
        and compare_digest(creds.password, ADMIN_PASS)
    ):
        return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Basic"},
    )


async def _require_guild_session_access(request: Request, guild_id: str) -> None:
    """Require a Discord OAuth session that is authorized for ``guild_id``."""

    if not request.session.get("user"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Discord sign-in required for guild configuration access.",
        )
    await _check_access(request, guild_id)


def require_chat_access(request: Request):
    viewer_id = _session_chat_viewer_id(request)
    if viewer_id:
        ban = _zeta_ban_for(request, viewer_id)
        if ban:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_zeta_ban_notice(ban))
        vpn_block = _zeta_vpn_block(request)
        if vpn_block:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=vpn_block)
        _zeta_note_traces(request, viewer_id)
        return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Enter a name on the Project ZETA page to join.",
    )


def _is_safe_redirect(target: str | None) -> bool:
    if not target:
        return False

    # Browsers treat "\\" like "/", so "/\\evil.com" and "//evil.com" are both
    # protocol-relative URLs that leave the site.
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    if any(ord(ch) < 0x20 for ch in target):
        return False
    parsed = urlparse(target)
    return parsed.scheme == "" and parsed.netloc == ""


def _clean_redirect_target(candidate: str | None, default: str = "/dashboard") -> str:
    if candidate and _is_safe_redirect(candidate):
        return candidate
    return default


def require_portal_admin(
    request: Request, creds: HTTPBasicCredentials | None = Depends(auth)
):
    """Enforce access for portal admins or basic-authenticated operators."""

    if _session_user_is_admin(request):
        return True
    if ADMIN_USER and ADMIN_PASS and creds and (
        compare_digest(creds.username, ADMIN_USER)
        and compare_digest(creds.password, ADMIN_PASS)
    ):
        return True
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to the admin controls.",
    )


def _discord_display_name(user: Mapping[str, Any] | None) -> str:
    if not user:
        return "Operator"

    for key in ("global_name", "display_name", "username"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "Operator"


def _operator_initial(user: Mapping[str, Any] | None) -> str:
    name = _discord_display_name(user)
    for char in name:
        if char.isalpha():
            return char.upper()
    return "O"


def _operator_initial_from_label(label: str | None) -> str:
    if not label:
        return "O"
    for char in label:
        if char.isalpha():
            return char.upper()
    return "O"


def _operator_from_id_code(id_code: str | None):
    if not id_code:
        return None
    cleaned = str(id_code).strip().upper()
    if not cleaned:
        return None
    for operator in list_operators():
        if str(operator.id_code).strip().upper() == cleaned:
            return operator
    return None


def _operator_alias_initial(
    initial: str | None, operator: str | None = None
) -> str:
    candidates = (initial, operator)
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        for char in candidate:
            if char.isalpha():
                return char.upper()
    return "O"


def _allocate_alias_initial(label: str, used: set[str]) -> str:
    """Return the first available alphabetic character in ``label``.

    The function walks the characters of ``label`` in order, returning the
    first unused alphabetic character (case-insensitive). If every alphabetic
    character in ``label`` is exhausted or none are present, the first unused
    letter from the English alphabet is returned instead. This guarantees a
    stable, unique initial for each caller.
    """

    if isinstance(label, str):
        for char in label:
            if not char.isalpha():
                continue
            candidate = char.upper()
            if candidate not in used:
                return candidate

    for fallback in (chr(code) for code in range(ord("A"), ord("Z") + 1)):
        if fallback not in used:
            return fallback

    # Should never be reached, but guard against an unexpectedly full set.
    return "O"


def _masked_operator_label(initial: str | None, operator: str | None = None) -> str:
    alias_initial = _operator_alias_initial(initial, operator)
    return f"Operator {alias_initial}" if alias_initial else "Operator"


def _chat_operator_name(
    user: Mapping[str, Any] | None, *, is_moderator: bool
) -> str:
    if is_moderator:
        return _discord_display_name(user)
    return _masked_operator_label(_operator_initial(user))


def _render_chat_entry(
    entry: Mapping[str, str],
    *,
    is_moderator: bool,
    viewer_id: str | None = None,
    directory: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, str]:
    cleaned_entry = dict(entry) if isinstance(entry, Mapping) else {}
    # The author's Discord ID stays server-side; viewers only learn whether a
    # message is their own and an opaque handle for opening a direct message.
    author_id = cleaned_entry.pop("user_id", None) or None
    cleaned_entry["mine"] = bool(viewer_id and author_id == viewer_id)
    member = (directory or {}).get(author_id) if author_id else None
    cleaned_entry["handle"] = _zeta_handle(author_id) if member else ""
    if is_moderator:
        return cleaned_entry

    if member:
        alias_initial = member["initial"]
        alias = member["label"]
    else:
        alias_initial = _operator_alias_initial(
            cleaned_entry.get("initial"), cleaned_entry.get("operator")
        )
        alias = _masked_operator_label(alias_initial)
    cleaned_entry.update(
        {
            "operator": alias,
            "operator_handle": alias,
            "initial": alias_initial,
        }
    )
    return cleaned_entry


def _session_chat_viewer_id(request: Request) -> str | None:
    """The caller's ZETA identity: an approved Discord account, else the guest name they joined with."""

    user = request.session.get("user") if isinstance(request.session, dict) else None
    user_id = _clean_discord_id((user or {}).get("id"))
    if user_id:
        settings, _etag = load_owner_settings()
        if can_access_chat(user_id, settings.managers, settings.chat_access):
            return user_id
    guest = _zeta_session_guest(request)
    return guest["id"] if guest else None


def _render_chat_entries(
    entries: Iterable[Mapping[str, str]] | None,
    *,
    is_moderator: bool,
    viewer_id: str | None = None,
    directory: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    if not entries:
        return rendered

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        rendered.append(
            _render_chat_entry(
                entry, is_moderator=is_moderator, viewer_id=viewer_id, directory=directory
            )
        )

    return rendered


def _refresh_local_storage_root() -> None:
    """Ensure storage operations honor the current local root."""

    override = os.getenv("SPECTRE_LOCAL_ROOT") or os.getenv("SPACES_ROOT")
    setter = getattr(storage_spaces, "set_local_root", None)
    if callable(setter):
        setter(override)


def _storage_backend():
    backend = importlib.reload(storage_spaces)
    _refresh_local_storage_root()
    return backend


def _clean_chat_log(
    data: Mapping[str, Any] | None, *, now: datetime | None = None
) -> dict[str, list[dict[str, str]]]:
    messages: list[dict[str, str]] = []
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    def _parse_timestamp(value: str | None) -> datetime:
        if not value:
            return now
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return now
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    if isinstance(data, Mapping):
        raw_messages = data.get("messages")
        if isinstance(raw_messages, list):
            for entry in raw_messages:
                if not isinstance(entry, Mapping):
                    continue
                message = str(entry.get("message", "")).strip()
                operator = str(entry.get("operator", "")).strip()
                operator_handle = str(entry.get("operator_handle", "")).strip()
                operator_role = str(entry.get("role", "operator")).strip().lower()
                operator_initial = str(entry.get("initial", "")).strip()
                created_at = str(entry.get("created_at", "")).strip()
                uid = str(entry.get("id", "")).strip()
                if not message or not operator:
                    continue
                timestamp = _parse_timestamp(created_at)
                if timestamp < cutoff:
                    continue

                if operator_role not in {"moderator", "operator"}:
                    operator_role = "operator"

                if not operator_handle:
                    operator_handle = operator

                if not operator_initial:
                    for char in operator:
                        if char.isalpha():
                            operator_initial = char.upper()
                            break
                    else:
                        operator_initial = "O"
                messages.append(
                    {
                        "id": uid or secrets.token_hex(8),
                        "message": message[:_ALICE_CHAT_MAX_LENGTH],
                        "operator": operator,
                        "operator_handle": operator_handle,
                        "role": operator_role,
                        "initial": operator_initial,
                        "created_at": created_at,
                        "user_id": _zeta_clean_member_id(entry.get("user_id")) or "",
                    }
                )

    messages = messages[-_ALICE_CHAT_MAX_MESSAGES :]
    return {"messages": messages}


def _clean_chat_access_requests(
    data: Mapping[str, Any] | None
) -> list[dict[str, str]]:
    """Return a de-duplicated list of pending chat access requests."""

    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    entries = []
    if isinstance(data, Mapping):
        raw = data.get("requests") or data.get("pending") or data.get("entries")
        if isinstance(raw, list):
            entries = [entry for entry in raw if isinstance(entry, Mapping)]

    for entry in entries:
        user_id = _clean_discord_id(entry.get("user_id") or entry.get("id"))
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        display_name = str(entry.get("display_name") or "").strip() or f"Operator {user_id}"
        requested_at = str(entry.get("requested_at") or "").strip() or now
        cleaned.append(
            {
                "user_id": user_id,
                "display_name": display_name,
                "requested_at": requested_at,
            }
        )

    return cleaned


def _load_chat_access_requests(
    with_etag: bool = False,
) -> tuple[list[dict[str, str]], str | None]:
    if with_etag:
        payload, etag = read_json(_ALICE_CHAT_REQUESTS_KEY, with_etag=True)
    else:
        try:
            payload = read_json(_ALICE_CHAT_REQUESTS_KEY)
            etag = None
        except FileNotFoundError:
            payload, etag = None, None
    return _clean_chat_access_requests(payload), etag


def _save_chat_access_requests(
    requests: list[dict[str, str]], *, etag: str | None = None
) -> bool:
    payload = {"requests": _clean_chat_access_requests({"requests": requests})}
    return write_json(_ALICE_CHAT_REQUESTS_KEY, payload, etag=etag)


def _clear_chat_access_request(user_id: str) -> bool:
    target = _clean_discord_id(user_id)
    if not target:
        return False

    requests, etag = _load_chat_access_requests(with_etag=True)
    updated = [entry for entry in requests if entry.get("user_id") != target]
    return _save_chat_access_requests(updated, etag=etag)


def _load_alice_chat(
    with_etag: bool = False, *, now: datetime | None = None
) -> tuple[dict[str, list[dict[str, str]]], str | None]:
    backend = _storage_backend()
    try:
        if with_etag:
            payload, etag = backend.read_json(_ALICE_CHAT_LOG_KEY, with_etag=True)
            return _clean_chat_log(payload, now=now), etag
        payload = backend.read_json(_ALICE_CHAT_LOG_KEY)
        return _clean_chat_log(payload, now=now), None
    except FileNotFoundError:
        return {"messages": []}, None


def _enforce_chat_retention(*, now: datetime | None = None) -> tuple[dict, str | None]:
    backend = _storage_backend()
    attempts = 0
    while attempts < 3:
        attempts += 1
        chat_log, etag = _load_alice_chat(with_etag=True, now=now)
        cleaned_log = _clean_chat_log(chat_log, now=now)
        if cleaned_log == chat_log:
            return cleaned_log, etag

        if backend.write_json(_ALICE_CHAT_LOG_KEY, cleaned_log, etag=etag):
            refreshed, refreshed_etag = _load_alice_chat(with_etag=True, now=now)
            return refreshed, refreshed_etag

    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail="Chat log was updated, please retry your message",
    )


def _clean_private_message_log(payload: dict | None) -> dict[str, list[dict[str, str]]]:
    if not isinstance(payload, dict):
        return {"messages": []}

    cleaned: list[dict[str, str]] = []
    for entry in payload.get("messages") or []:
        if not isinstance(entry, dict):
            continue

        recipient_id = _clean_discord_id(entry.get("recipient_id"))
        sender_id = _clean_discord_id(entry.get("sender_id"))
        message = str(entry.get("message") or "").strip()
        if not recipient_id or not message:
            continue

        cleaned.append(
            {
                "id": str(entry.get("id") or secrets.token_hex(8)),
                "recipient_id": recipient_id,
                "sender_id": sender_id or "",
                "sender": str(entry.get("sender") or "Operator").strip() or "Operator",
                "message": message[:_ALICE_CHAT_MAX_LENGTH],
                "created_at": str(entry.get("created_at") or "").strip()
                or datetime.now(timezone.utc).isoformat(),
            }
        )

    cleaned = cleaned[-_ALICE_PRIVATE_MESSAGE_MAX :]
    return {"messages": cleaned}


def _load_private_messages(with_etag: bool = False) -> tuple[dict, str | None]:
    backend = _storage_backend()
    try:
        if with_etag:
            payload, etag = backend.read_json(_ALICE_PRIVATE_MESSAGE_KEY, with_etag=True)
            return _clean_private_message_log(payload), etag
        payload = backend.read_json(_ALICE_PRIVATE_MESSAGE_KEY)
        return _clean_private_message_log(payload), None
    except FileNotFoundError:
        return {"messages": []}, None


def _save_private_messages(messages: list[dict], *, etag: str | None = None) -> bool:
    backend = _storage_backend()
    payload = _clean_private_message_log({"messages": messages})
    return backend.write_json(_ALICE_PRIVATE_MESSAGE_KEY, payload, etag=etag)


def _zeta_member_names() -> dict[str, str]:
    backend = _storage_backend()
    try:
        payload = backend.read_json(_ZETA_MEMBERS_KEY)
    except FileNotFoundError:
        return {}
    names = payload.get("names") if isinstance(payload, dict) else None
    return {
        str(user_id): name.strip()
        for user_id, name in (names or {}).items()
        if isinstance(name, str) and name.strip()
    }


def _zeta_remember_member(user: Mapping[str, Any] | None) -> None:
    """Record a member's display name so their callsign can be assigned."""

    user_id = _clean_discord_id((user or {}).get("id"))
    name = _discord_display_name(user)
    if not user_id or not name or name == "Operator":
        return
    backend = _storage_backend()
    for _attempt in range(3):
        try:
            payload, etag = backend.read_json(_ZETA_MEMBERS_KEY, with_etag=True)
        except FileNotFoundError:
            payload, etag = None, None
        names = dict((payload or {}).get("names") or {})
        if names.get(user_id) == name:
            return
        names[user_id] = name
        if backend.write_json(_ZETA_MEMBERS_KEY, {"names": names}, etag=etag):
            return


def _zeta_clean_member_id(value: Any) -> str | None:
    """A Discord ID or a ZETA guest ID, else ``None``."""

    candidate = str(value or "").strip()
    if _ZETA_GUEST_ID_RE.fullmatch(candidate):
        return candidate
    return _clean_discord_id(candidate)


def _zeta_clean_guest_name(value: Any) -> str:
    # NFKC folds full-width and styled letters; dropping control and format
    # characters removes invisible ones such as zero-width spaces.
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) not in {"Cc", "Cf"})
    return " ".join(text.split())[:_ZETA_GUEST_NAME_MAX].strip()


def _zeta_name_key(name: str) -> str:
    """What two names must differ in: "Night Owl", "night-owl" and "NIGHTOWL" collide."""

    return "".join(char for char in _zeta_clean_guest_name(name).casefold() if char.isalnum())


def _zeta_session_guest(request: Request) -> dict[str, str] | None:
    guest = request.session.get(_ZETA_GUEST_SESSION_KEY) if isinstance(request.session, dict) else None
    if not isinstance(guest, dict):
        return None
    guest_id = str(guest.get("id") or "")
    name = _zeta_clean_guest_name(guest.get("name"))
    if not _ZETA_GUEST_ID_RE.fullmatch(guest_id) or not name:
        return None
    return {"id": guest_id, "name": name}


def _zeta_guests(now: datetime | None = None) -> dict[str, dict[str, str]]:
    """Guests seen within ``_ZETA_GUEST_TTL``, keyed by guest ID."""

    try:
        payload = _storage_backend().read_json(_ZETA_GUESTS_KEY)
    except FileNotFoundError:
        return {}
    return _zeta_parse_guests(payload, now)


def _zeta_parse_guests(payload: Any, now: datetime | None = None) -> dict[str, dict[str, str]]:
    cutoff = (now or datetime.now(timezone.utc)) - _ZETA_GUEST_TTL
    guests: dict[str, dict[str, str]] = {}
    raw = payload.get("guests") if isinstance(payload, dict) else None
    for guest_id, entry in (raw or {}).items():
        if not _ZETA_GUEST_ID_RE.fullmatch(str(guest_id)) or not isinstance(entry, dict):
            continue
        name = _zeta_clean_guest_name(entry.get("name"))
        try:
            last_seen = datetime.fromisoformat(str(entry.get("last_seen") or ""))
        except ValueError:
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if name and last_seen >= cutoff:
            guests[str(guest_id)] = {"name": name, "last_seen": last_seen.isoformat()}
    return guests


def _zeta_guest_name_problem(name: str) -> str | None:
    """Why ``name`` cannot be used, or ``None`` when it is fine.

    Clashes with other guests are checked when the name is claimed, see
    ``_zeta_claim_guest``.
    """

    key = _zeta_name_key(name)
    if not key:
        return "Enter a name with at least one letter or number."
    # Members of the Discord roster appear as "Operator X"; keep guests from posing as one.
    if key.startswith(("operator", "formeroperator", "moderator")):
        return "That name is reserved. Pick another."
    # Moderators see members' real names, so those are taken too.
    if any(
        _zeta_name_key(member["name"]) == key
        for member in _zeta_members()
        if member["group"] != "guest"
    ):
        return "Someone in Project ZETA already uses that name."
    return None


_ZETA_GUESTS_LOCK = threading.Lock()


def _zeta_claim_guest(guest: Mapping[str, str], *, force: bool = False) -> str | None:
    """Record ``guest`` as seen under their name; return why not, or ``None``.

    The name is checked against every other active guest inside the same
    ETag-guarded write, so two people can never end up with the same name,
    not even by joining at the same moment or by returning after their name
    expired and someone else took it. Unless ``force``, a guest seen within
    ``_ZETA_GUEST_TOUCH_INTERVAL`` under the same name is not rewritten.
    """

    now = datetime.now(timezone.utc)
    key = _zeta_name_key(guest["name"])
    backend = _storage_backend()
    with _ZETA_GUESTS_LOCK:
        for _attempt in range(3):
            try:
                payload, etag = backend.read_json(_ZETA_GUESTS_KEY, with_etag=True)
            except FileNotFoundError:
                payload, etag = None, None
            current = _zeta_parse_guests(payload, now)
            if any(
                other_id != guest["id"] and _zeta_name_key(entry["name"]) == key
                for other_id, entry in current.items()
            ):
                return "Someone in Project ZETA already uses that name."
            entry = current.get(guest["id"])
            if (
                not force
                and entry
                and entry["name"] == guest["name"]
                and now - datetime.fromisoformat(entry["last_seen"]) < _ZETA_GUEST_TOUCH_INTERVAL
            ):
                return None
            current[guest["id"]] = {"name": guest["name"], "last_seen": now.isoformat()}
            if backend.write_json(_ZETA_GUESTS_KEY, {"guests": current}, etag=etag):
                return None
    return "Project ZETA is busy. Try again."


def _zeta_release_guest_name(request: Request) -> None:
    """Keep the session's guest ID (and its DMs) but make them pick a new name."""

    guest = request.session.get(_ZETA_GUEST_SESSION_KEY)
    if isinstance(guest, dict):
        request.session[_ZETA_GUEST_SESSION_KEY] = {"id": guest.get("id")}


def _website_user_names() -> dict[str, str]:
    try:
        users = list_website_users()
    except Exception:  # pragma: no cover - the registry is only a fallback
        return {}
    return {
        entry["id"]: entry.get("global_name") or entry.get("username") or ""
        for entry in users
        if entry.get("id")
    }


def _zeta_members(settings: OwnerSettings | None = None) -> list[dict[str, str]]:
    """Every ZETA member with a unique masked callsign.

    Each entry has ``id``, ``label`` (the masked ``Operator X`` callsign),
    ``initial``, ``name`` (the real display name, for moderators) and
    ``group`` (``command`` for the owner and managers, ``guest`` for people
    who joined with a name, else ``operator``).
    """

    if settings is None:
        settings, _ = load_owner_settings()

    command: set[str] = set()
    candidates: list[str | None] = []
    if _ALICE_PRIVATE_MESSAGE_RECIPIENT:
        candidates.append(_ALICE_PRIVATE_MESSAGE_RECIPIENT)
        command.add(_clean_discord_id(_ALICE_PRIVATE_MESSAGE_RECIPIENT) or "")
    candidates.extend(settings.managers)
    command.update(_clean_discord_id(mid) or "" for mid in settings.managers)
    candidates.extend(settings.chat_access)

    seen: set[str] = set()
    ids: list[str] = []
    for candidate in candidates:
        cleaned = _clean_discord_id(candidate)
        if cleaned and cleaned not in seen:
            ids.append(cleaned)
            seen.add(cleaned)

    operators = {str(op.user_id): op for op in list_operators()}
    zeta_names = _zeta_member_names()
    site_names: dict[str, str] | None = None

    members: list[dict[str, str]] = []
    used_initials: set[str] = set()

    for user_id in ids:
        record = operators.get(user_id)
        name = str(getattr(record, "name", "") or "").strip() if record else ""
        name = name or zeta_names.get(user_id, "")
        if not name:
            if site_names is None:
                site_names = _website_user_names()
            name = site_names.get(user_id, "")

        label = name or getattr(record, "id_code", None) or f"Operator {user_id}"
        initial = _allocate_alias_initial(label, used_initials)
        used_initials.add(initial)
        alias = _masked_operator_label(initial)

        members.append(
            {
                "id": user_id,
                "label": alias,
                "initial": initial,
                "name": name or alias,
                "group": "command" if user_id in command or is_owner(user_id) else "operator",
            }
        )

    # Guests chose their own name, so everyone sees it instead of a masked callsign.
    for guest_id, guest in _zeta_guests().items():
        members.append(
            {
                "id": guest_id,
                "label": guest["name"],
                "initial": _operator_initial_from_label(guest["name"]),
                "name": guest["name"],
                "group": "guest",
            }
        )

    return members


def _zeta_directory(settings: OwnerSettings | None = None) -> dict[str, dict[str, str]]:
    """Members who can use ZETA right now: banned members drop out, so their DMs turn read-only."""

    banned = _zeta_banned_ids()
    return {member["id"]: member for member in _zeta_members(settings) if member["id"] not in banned}


def _zeta_handle(user_id: str) -> str:
    """Opaque, stable reference to a member, so pages never carry Discord IDs."""

    key = f"zeta-handle:{SESSION_SECRET}".encode("utf-8")
    return hmac.new(key, user_id.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def _zeta_public_member(
    member: Mapping[str, str], *, is_moderator: bool, viewer_id: str | None
) -> dict[str, Any]:
    return {
        "handle": _zeta_handle(member["id"]),
        "label": member["name"] if is_moderator else member["label"],
        "initial": member["initial"],
        "group": member["group"],
        "self": member["id"] == viewer_id,
    }


def _zeta_former_member(user_id: str, *, is_moderator: bool, names: Mapping[str, str]) -> dict[str, str]:
    """Directory-shaped entry for someone who has a thread but no longer has access."""

    label = (names.get(user_id) if is_moderator else None) or "Former operator"
    return {"id": user_id, "label": label, "initial": "×", "name": label, "group": "former"}


def _zeta_import_legacy_dispatches(user_id: str) -> None:
    """Move undelivered dispatches from the old pop-up queue into DM threads."""

    payload, etag = _load_private_messages(with_etag=True)
    messages = payload.get("messages", [])
    mine = [entry for entry in messages if entry.get("recipient_id") == user_id]
    if not mine:
        return
    backend = _storage_backend()
    for entry in mine:
        zeta_dm.import_message(
            backend,
            sender_id=entry.get("sender_id") or "",
            recipient_id=user_id,
            message=entry.get("message") or "",
            created_at=entry.get("created_at") or datetime.now(timezone.utc).isoformat(),
        )
    remaining = [entry for entry in messages if entry.get("recipient_id") != user_id]
    _save_private_messages(remaining, etag=etag)


def _prune_guild_cache(now: float | None = None) -> None:
    """Remove stale/old guild cache entries to avoid unbounded token growth."""

    if not _GUILD_CACHE:
        return

    current = now if now is not None else time.time()
    stale_keys = [
        token
        for token, (cached_at, _guilds) in _GUILD_CACHE.items()
        if current - cached_at >= GUILD_CACHE_TTL_SECONDS
    ]
    for token in stale_keys:
        _GUILD_CACHE.pop(token, None)

    overflow = len(_GUILD_CACHE) - GUILD_CACHE_MAX_ENTRIES
    if overflow <= 0:
        return

    ordered = sorted(_GUILD_CACHE.items(), key=lambda item: item[1][0])
    for token, _value in ordered[:overflow]:
        _GUILD_CACHE.pop(token, None)


def _prune_admin_profile_cache(*, now: datetime | None = None) -> None:
    """Evict stale and oldest Discord profile cache entries."""

    if not _ADMIN_PROFILE_CACHE:
        return

    current = now or datetime.now(timezone.utc)
    stale_keys = [
        user_id
        for user_id, (cached_at, _profile) in _ADMIN_PROFILE_CACHE.items()
        if current - cached_at >= _ADMIN_PROFILE_CACHE_TTL
    ]
    for user_id in stale_keys:
        _ADMIN_PROFILE_CACHE.pop(user_id, None)

    overflow = len(_ADMIN_PROFILE_CACHE) - _ADMIN_PROFILE_CACHE_MAX_ENTRIES
    if overflow <= 0:
        return

    ordered = sorted(_ADMIN_PROFILE_CACHE.items(), key=lambda item: item[1][0])
    for user_id, _value in ordered[:overflow]:
        _ADMIN_PROFILE_CACHE.pop(user_id, None)


def _append_chat_message(
    *, request: Request, message: str
) -> dict[str, str]:
    attempts = 0
    cleaned_message = message.strip()
    if not cleaned_message:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty"
        )
    if len(cleaned_message) > _ALICE_CHAT_MAX_LENGTH:
        cleaned_message = cleaned_message[:_ALICE_CHAT_MAX_LENGTH]

    while attempts < 3:
        attempts += 1
        backend = _storage_backend()
        chat_log, etag = _load_alice_chat(with_etag=True)
        messages = chat_log.get("messages", [])

        viewer_id = _session_chat_viewer_id(request)
        guest = _zeta_session_guest(request)
        if guest and guest["id"] == viewer_id:
            actor_label = operator_name = guest["name"]
            operator_initial = _operator_initial_from_label(guest["name"])
        else:
            user = request.session.get("user") if isinstance(request.session, dict) else None
            actor_label = _format_actor(user)
            operator_name = _discord_display_name(user)
            operator_initial = _operator_initial(user)
        is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)

        entry = {
            "id": secrets.token_hex(8),
            "message": cleaned_message,
            "user_id": viewer_id,
            "operator": operator_name,
            "operator_handle": actor_label,
            "role": "moderator" if is_moderator else "operator",
            "initial": operator_initial,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        messages.append(entry)
        chat_log["messages"] = _clean_chat_log(
            {"messages": messages}, now=datetime.now(timezone.utc)
        )["messages"][-_ALICE_CHAT_MAX_MESSAGES :]

        if backend.write_json(_ALICE_CHAT_LOG_KEY, chat_log, etag=etag):
            return entry

    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail="Chat log was updated, please retry your message",
    )


def _delete_chat_message(*, message_id: str, now: datetime | None = None) -> dict:
    if not message_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="A valid message id is required",
        )

    attempts = 0
    while attempts < 3:
        attempts += 1
        backend = _storage_backend()
        chat_log, etag = _load_alice_chat(with_etag=True, now=now)
        messages = chat_log.get("messages", [])
        filtered = [entry for entry in messages if entry.get("id") != message_id]
        if len(filtered) == len(messages):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            )
        cleaned_log = _clean_chat_log({"messages": filtered}, now=now)
        if backend.write_json(_ALICE_CHAT_LOG_KEY, cleaned_log, etag=etag):
            refreshed, _ = _load_alice_chat(with_etag=True, now=now)
            return refreshed

    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail="Chat log was updated, please retry your request",
    )


@app.get("/login", include_in_schema=False)
async def login(request: Request, next: str | None = None):
    redirect_target = _clean_redirect_target(
        next or request.session.get("post_auth_redirect")
    )
    request.session["post_auth_redirect"] = redirect_target

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


async def _oauth_callback(request: Request):
    try:
        expected_state = str(request.session.pop("oauth_state", "") or "")
        received_state = str(request.query_params.get("state") or "")
        if not expected_state or not received_state or not compare_digest(expected_state, received_state):
            request.session.pop("post_auth_redirect", None)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state. Please start the login flow again.",
            )

        token = oauth.fetch_token(
            "https://discord.com/api/oauth2/token",
            client_secret=CLIENT_SECRET,
            authorization_response=str(request.url)
        )
        # Save the access token in session
        request.session["discord_token"] = token

        access_token = token.get("access_token")
        if access_token:
            try:
                async with httpx.AsyncClient() as c:
                    resp = await c.get(
                        f"{DISCORD_API}/users/@me",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                resp.raise_for_status()
            except httpx.HTTPError:
                logger.exception("Failed to load Discord user profile during OAuth callback")
            else:
                profile = resp.json()
                request.session["user"] = profile
                await _remember_website_user(profile, refresh=True)
                if isinstance(profile, dict) and _user_is_portal_admin(_clean_discord_id(profile.get("id"))):
                    _log_activity(
                        "login",
                        _user_display_name(profile) or "Admin",
                        _client_ip_from_request(request),
                        background=True,
                    )
        else:  # pragma: no cover - defensive guard
            logger.warning("OAuth token missing access_token; skipping profile load")

        redirect_target = _clean_redirect_target(
            request.session.pop("post_auth_redirect", None)
        )

        return RedirectResponse(url=redirect_target)

    except HTTPException:
        raise
    except Exception:
        logger.exception("OAuth error in callback endpoint")

        # Return an error message to the browser too
        return JSONResponse(
            status_code=500,
            content={"error": "OAuth callback failed"}
        )


@app.get("/auth/callback")
async def callback(request: Request):
    return await _oauth_callback(request)


@app.get("/callback", include_in_schema=False)
async def callback_legacy(request: Request):
    return await _oauth_callback(request)


MANAGE_GUILD = 0x20
ADMIN = 0x8

PERM_MODE = os.getenv('DASHBOARD_PERM_MODE', 'normal').strip().lower()


def _tos_consent_granted(request: Request) -> bool:
    cookie_value = str(request.cookies.get(TOS_CONSENT_COOKIE_NAME) or "").strip()
    return cookie_value == TOS_CONSENT_COOKIE_VALUE


def _tos_required_redirect(request: Request) -> RedirectResponse:
    destination = str(request.url.path or "/").strip() or "/"
    query = str(request.url.query or "").strip()
    if query:
        destination = f"{destination}?{query}"
    encoded_destination = quote(destination, safe="")
    return RedirectResponse(url=f"/?tos=required&next={encoded_destination}")


def _require_tos_consent(request: Request) -> RedirectResponse | None:
    if _tos_consent_granted(request):
        return None
    return _tos_required_redirect(request)



def _has_perm(p: int, b: int) -> bool:
    return (int(p) & b) == b


@app.get("/me")
async def me(request: Request):
    return request.session.get("user") or {}


@app.post("/tos/accept", include_in_schema=False)
async def accept_terms_of_service(request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    is_https = str(request.url.scheme).lower() == "https"
    response.set_cookie(
        key=TOS_CONSENT_COOKIE_NAME,
        value=TOS_CONSENT_COOKIE_VALUE,
        max_age=TOS_CONSENT_MAX_AGE_SECONDS,
        secure=is_https,
        httponly=False,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/",
    )
    return response


@app.get("/dashboard")
async def dashboard(request: Request):
    tos_redirect = _require_tos_consent(request)
    if tos_redirect:
        return tos_redirect

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

    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    if templates is None:
        return JSONResponse(
            {
                "user": user,
                "guilds": common,
                "bot_version": bot_version,
                "latest_update": latest_update,
                "can_manage_owner": can_manage_owner_portal,
                "brand_image_url": brand_image_url,
            }
        )

    context = {
        "request": request,
        "user": user,
        "guilds": common,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_image_url": brand_image_url,
        "build": BUILD,
        "bot_version": bot_version,
        "latest_update": latest_update,
        "can_manage_owner": can_manage_owner_portal,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(
        request,
        "dashboard_selector.html",
        _inject_wallpaper(context, "dashboard"),
    )


@app.get("/server/{guild_id}", include_in_schema=False)
async def server_control(request: Request, guild_id: str):
    token = request.session.get("discord_token")
    if not token:
        return RedirectResponse(url="/login")

    await _check_access(request, guild_id)

    user, common = await _load_user_context(request)
    if user is None:
        return RedirectResponse(url="/login")

    guild_record = next((g for g in common if str(g.get("id")) == guild_id), None)
    guild_name = guild_record.get("name", "Server") if guild_record else "Server"

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user.get("id") else None
    can_manage_owner_portal = can_manage_portal(user_id, owner_settings.managers)
    latest_update = owner_settings.latest_update.strip()
    bot_version = owner_settings.bot_version.strip()

    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    context = {
        "request": request,
        "user": user,
        "guilds": common,
        "guild_id": guild_id,
        "guild_name": guild_name,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_image_url": brand_image_url,
        "build": BUILD,
        "bot_version": bot_version,
        "latest_update": latest_update,
        "can_manage_owner": can_manage_owner_portal,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    context["standalone"] = True
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _inject_wallpaper(context, "dashboard"),
    )


async def get_user_guilds(token: dict) -> list[dict]:
    """Return guilds the user belongs to using their OAuth token."""
    access_token = str(token.get("access_token") or "").strip()
    if not access_token:
        raise httpx.HTTPError("Missing Discord OAuth access token for guild lookup.")

    now = time.time()
    with _GUILD_CACHE_LOCK:
        _prune_guild_cache(now=now)
        cached_entry = _GUILD_CACHE.get(access_token)
        if cached_entry is not None:
            cached_at, cached_guilds = cached_entry
            if now - cached_at < GUILD_CACHE_TTL_SECONDS:
                return cached_guilds

    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    r.raise_for_status()
    guilds = r.json()
    with _GUILD_CACHE_LOCK:
        _prune_guild_cache()
        _GUILD_CACHE[access_token] = (time.time(), guilds)
        _prune_guild_cache()
    return guilds


def _discord_retry_after(response: httpx.Response) -> float | None:
    """Return how many seconds Discord asked us to wait after a 429."""

    try:
        return float(response.json()["retry_after"])
    except Exception:  # noqa: BLE001 - body may be missing or not JSON
        pass
    try:
        return float(response.headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        return None


async def _call_discord(
    send: Callable[[], Any],
    *,
    max_wait: float = DISCORD_RATE_LIMIT_MAX_WAIT_SECONDS,
) -> httpx.Response:
    """Run a Discord REST call, waiting out one short rate limit before giving up."""

    response = await send()
    if response.status_code == 429:
        retry_after = _discord_retry_after(response)
        if retry_after is not None and retry_after <= max_wait:
            await asyncio.sleep(retry_after)
            response = await send()
    response.raise_for_status()
    return response


def _describe_discord_error(exc: Exception) -> str:
    """Summarise a Discord REST failure in one line for logs and the UI."""

    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            retry_after = _discord_retry_after(exc.response)
            if retry_after is not None:
                return f"Discord rate limit hit (retry in {retry_after:.0f}s)"
            return "Discord rate limit hit"
        if code == 403:
            return "Discord refused access (403)"
        if code == 404:
            return "not found on Discord (404)"
        return f"Discord returned HTTP {code}"
    return str(exc) or type(exc).__name__


async def get_bot_guilds() -> list[dict]:
    """Return guilds the bot is a member of.

    The result is cached for ``BOT_GUILDS_CACHE_TTL_SECONDS``. If Discord
    refuses a refresh, the last known list is served instead of failing.
    """
    global _bot_guilds_cache

    if not bot_token_available():
        logger.warning(
            "Skipping bot guild lookup because the Discord bot token is not configured."
        )
        return []

    cached = _bot_guilds_cache
    if cached and time.monotonic() - cached[0] < BOT_GUILDS_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await _call_discord(
                lambda: c.get(
                    f"{DISCORD_API}/users/@me/guilds",
                    headers={"Authorization": f"Bot {BOT_TOKEN}"},
                ),
                max_wait=2.0,
            )
    except httpx.HTTPError as exc:
        if cached is None:
            raise
        logger.warning(
            "Could not refresh the bot's server list (%s); using the copy from %.0fs ago",
            _describe_discord_error(exc),
            time.monotonic() - cached[0],
        )
        return cached[1]

    guilds = r.json()
    _bot_guilds_cache = (time.monotonic(), guilds)
    return guilds


def _director_alert_content(*, priority: str, actor: str, message: str) -> str:
    """Build a polished direct-message payload for server-owner alerts."""

    priority_label = normalise_broadcast_priority(priority).replace("-", " ").upper()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cleaned_actor = actor.strip() or "Director"
    cleaned_message = message.strip()

    content = (
        "🚨 **SPECTRE DIRECTOR ALERT**\n"
        f"Priority: **{priority_label}**\n"
        f"Issued by: **{cleaned_actor}**\n"
        f"Timestamp: **{timestamp}**\n\n"
        f"{cleaned_message}\n\n"
        "You are receiving this because you are registered as a server owner "
        "for a Discord server where SPECTRE is active."
    )
    if len(content) <= 2000:
        return content

    overflow = len(content) - 2000
    clipped_body = cleaned_message[: max(0, len(cleaned_message) - overflow - 24)].rstrip()
    clipped_suffix = "\n\n_[Message clipped to fit Discord DM limits.]_"
    clipped = (
        "🚨 **SPECTRE DIRECTOR ALERT**\n"
        f"Priority: **{priority_label}**\n"
        f"Issued by: **{cleaned_actor}**\n"
        f"Timestamp: **{timestamp}**\n\n"
        f"{clipped_body}{clipped_suffix}"
    )
    return clipped[:2000]


async def _dispatch_director_alert_to_server_owners(
    *, message: str, priority: str, actor: str
) -> dict[str, object]:
    """Send the director alert to unique owners for guilds where the bot is present."""

    if not bot_token_available():
        return {
            "attempted": 0,
            "delivered": 0,
            "failed": [],
            "skipped": "Discord bot token not configured",
        }

    try:
        guilds = await get_bot_guilds()
    except httpx.HTTPError as exc:
        reason = f"Could not list the bot's servers: {_describe_discord_error(exc)}"
        logger.warning("Director alert not sent. %s", reason)
        return {"attempted": 0, "delivered": 0, "failed": [], "skipped": reason}

    guild_ids: list[str] = []
    for entry in guilds:
        guild_id = _clean_discord_id(entry.get("id"))
        if guild_id:
            guild_ids.append(guild_id)

    if not guild_ids:
        return {"attempted": 0, "delivered": 0, "failed": []}

    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    owner_ids: set[str] = set()
    failures: list[dict[str, str]] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        for guild_id in guild_ids:
            try:
                response = await _call_discord(
                    lambda: client.get(f"{DISCORD_API}/guilds/{guild_id}", headers=headers)
                )
                payload = response.json()
            except Exception as exc:  # noqa: BLE001 - network and API errors
                failures.append(
                    {"owner_id": "", "reason": f"server {guild_id}: {_describe_discord_error(exc)}"}
                )
                continue

            owner_id = _clean_discord_id(payload.get("owner_id"))
            if owner_id:
                owner_ids.add(owner_id)

        if not owner_ids:
            return {"attempted": 0, "delivered": 0, "failed": failures}

        content = _director_alert_content(priority=priority, actor=actor, message=message)
        delivered = 0

        for owner_id in sorted(owner_ids):
            try:
                dm_response = await _call_discord(
                    lambda: client.post(
                        f"{DISCORD_API}/users/@me/channels",
                        headers=headers,
                        json={"recipient_id": owner_id},
                    )
                )
                dm_channel = dm_response.json()
                channel_id = _clean_discord_id(dm_channel.get("id"))
                if not channel_id:
                    raise ValueError("Missing DM channel id")

                await _call_discord(
                    lambda: client.post(
                        f"{DISCORD_API}/channels/{channel_id}/messages",
                        headers=headers,
                        json={"content": content},
                    )
                )
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - network and API errors
                reason = _describe_discord_error(exc)
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403:
                    reason = "owner does not accept DMs from the bot (403)"
                failures.append({"owner_id": owner_id, "reason": reason})

    return {
        "attempted": len(owner_ids),
        "delivered": delivered,
        "failed": failures,
    }


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


def _user_display_name(user: dict[str, Any] | None) -> str:
    if not isinstance(user, dict):
        return ""
    return (
        str(user.get("global_name") or "").strip()
        or str(user.get("username") or "").strip()
    )


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


_ADMIN_PROFILE_CACHE: dict[str, tuple[datetime, dict]] = {}
_ADMIN_PROFILE_CACHE_TTL = timedelta(minutes=30)
_ADMIN_PROFILE_CACHE_MAX_ENTRIES = 1000


def _record_admin_heartbeat(
    admin_id: str,
    *,
    name: str | None = None,
    role: str | None = None,
    clearance: str | None = None,
    ip: str | None = None,
) -> bool:
    """Mark ``admin_id`` as active now; return ``True`` if they were offline."""

    global _ADMIN_PRESENCE_PERSISTED_AT
    now = datetime.now(timezone.utc)
    snapshot: dict[str, dict[str, Any]] | None = None
    with _ADMIN_PRESENCE_LOCK:
        _ensure_admin_presence_loaded()
        existing = _ADMIN_PRESENCE.get(admin_id, {})
        previous = existing.get("last_active")
        came_online = not isinstance(previous, datetime) or now - previous > _ADMIN_HEARTBEAT_TIMEOUT
        _ADMIN_PRESENCE[admin_id] = {
            "id": admin_id,
            "name": (name or existing.get("name") or "Unknown").strip()[:80] or "Unknown",
            "role": (role or existing.get("role") or "Unknown").strip()[:80] or "Unknown",
            "clearance": (clearance or existing.get("clearance") or "None").strip()[:40] or "None",
            "last_active": now,
            "ip": (ip or existing.get("ip") or "Unknown").strip()[:64] or "Unknown",
        }
        # Every page an admin opens lands here; storage only needs the state
        # when someone comes online and roughly once a minute after that.
        persisted_at = _ADMIN_PRESENCE_PERSISTED_AT
        if came_online or persisted_at is None or now - persisted_at >= _ADMIN_PRESENCE_PERSIST_INTERVAL:
            _ADMIN_PRESENCE_PERSISTED_AT = now
            snapshot = {key: dict(value) for key, value in _ADMIN_PRESENCE.items()}
    if snapshot is not None:
        _persist_admin_presence(snapshot)
    return came_online


def _parse_presence_timestamp(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    candidate = raw_value.strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_admin_presence_loaded() -> None:
    global _ADMIN_PRESENCE_LOADED
    if _ADMIN_PRESENCE_LOADED:
        return
    try:
        payload = read_json(_ADMIN_PRESENCE_STORAGE_KEY)
    except FileNotFoundError:
        _ADMIN_PRESENCE_LOADED = True
        return
    except Exception:
        logger.exception("Failed to load admin presence from persistent storage")
        _ADMIN_PRESENCE_LOADED = True
        return

    entries = payload.get("entries") if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        _ADMIN_PRESENCE_LOADED = True
        return

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        admin_id = _clean_discord_id(raw_entry.get("id"))
        if not admin_id:
            continue
        parsed_time = _parse_presence_timestamp(raw_entry.get("last_active"))
        if not isinstance(parsed_time, datetime):
            continue
        _ADMIN_PRESENCE[admin_id] = {
            "id": admin_id,
            "name": str(raw_entry.get("name") or "Unknown").strip() or "Unknown",
            "role": str(raw_entry.get("role") or "Unknown").strip() or "Unknown",
            "clearance": str(raw_entry.get("clearance") or "None").strip() or "None",
            "ip": str(raw_entry.get("ip") or "Unknown").strip() or "Unknown",
            "last_active": parsed_time,
        }
    _ADMIN_PRESENCE_LOADED = True


def _persist_admin_presence(entries: dict[str, dict[str, Any]]) -> None:
    serialised: list[dict[str, str]] = []
    for admin_id, entry in entries.items():
        last_active = entry.get("last_active")
        if not isinstance(last_active, datetime):
            continue
        serialised.append(
            {
                "id": str(admin_id),
                "name": str(entry.get("name") or "Unknown").strip() or "Unknown",
                "role": str(entry.get("role") or "Unknown").strip() or "Unknown",
                "clearance": str(entry.get("clearance") or "None").strip() or "None",
                "ip": str(entry.get("ip") or "Unknown").strip() or "Unknown",
                "last_active": last_active.astimezone(timezone.utc).isoformat(),
            }
        )

    serialised.sort(key=lambda item: item.get("id", ""))
    payload = {
        "entries": serialised,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        save_json(_ADMIN_PRESENCE_STORAGE_KEY, payload)
    except Exception:
        logger.exception("Failed to persist admin presence to storage")


def _client_ip_from_request(request: Request) -> str:
    # The first X-Forwarded-For entry is whatever the client sent; the shield's
    # resolver reads the chain from our own proxies' end instead.
    headers = request.headers
    getlist = getattr(headers, "getlist", None)
    forwarded_values = getlist("x-forwarded-for") if getlist else [headers.get("x-forwarded-for") or ""]
    resolver = SECURITY_SHIELD.resolver
    client = request.client
    ip = resolver.resolve(
        [part for value in forwarded_values for part in str(value).split(",")],
        peer=client.host if client else None,
        cloudflare=headers.get("cf-connecting-ip"),
        custom=headers.get(resolver.header) if resolver.header else None,
    )
    return "Unknown" if ip == "unknown" else ip


class _SlidingWindowRateLimiter:
    """In-memory per-key request budget over a sliding time window."""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Record a hit for ``key``; return ``True`` when it is over budget."""

        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            for stale in [k for k, hits in self._hits.items() if not hits or hits[-1] < cutoff]:
                self._hits.pop(stale, None)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return True
            hits.append(now)
            return False

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _activity_entry(*, entry_type: str, user: str, ip: str, event_time: datetime | None = None) -> dict[str, Any]:
    occurred_at = event_time or datetime.now(timezone.utc)
    return {
        "type": entry_type,
        "user": (user or "Unknown").strip() or "Unknown",
        "ip": (ip or "Unknown").strip() or "Unknown",
        "time": occurred_at,
    }


def _should_track_site_visit(request: Request) -> bool:
    if request.method.upper() != "GET":
        return False

    path = request.url.path.strip() or "/"
    if path.startswith("/static") or path.startswith("/api") or path.startswith("/ws"):
        return False
    if path.startswith("/.well-known"):
        return False

    accept_header = str(request.headers.get("accept") or "")
    return "text/html" in accept_header.lower()


def _ensure_site_visit_log_loaded() -> None:
    global _SITE_VISIT_LOADED
    if _SITE_VISIT_LOADED:
        return

    try:
        payload = read_json(_SITE_VISIT_STORAGE_KEY)
    except FileNotFoundError:
        _SITE_VISIT_LOADED = True
        return
    except Exception:
        logger.exception("Failed to load site visit tracker data")
        _SITE_VISIT_LOADED = True
        return

    daily = payload.get("daily") if isinstance(payload, dict) else None
    if isinstance(daily, dict):
        for raw_day, raw_count in daily.items():
            day_key = str(raw_day or "").strip()
            if not day_key:
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            _SITE_VISIT_DAILY[day_key] = max(count, 0)

    _SITE_VISIT_LOADED = True


def _persist_site_visit_log() -> None:
    payload = {
        "daily": dict(sorted(_SITE_VISIT_DAILY.items())),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        save_json(_SITE_VISIT_STORAGE_KEY, payload)
    except Exception:
        logger.exception("Failed to persist site visit tracker data")


def _record_site_visit(request: Request) -> None:
    global _SITE_VISIT_LAST_MAINTENANCE

    if not _should_track_site_visit(request):
        return

    now = datetime.now(timezone.utc)
    day_key = now.date().isoformat()
    ip = _client_ip_from_request(request)
    user_agent = str(request.headers.get("user-agent") or "Unknown")
    path = str(request.url.path or "/").strip() or "/"
    dedupe_key = f"{ip}|{user_agent}".strip()
    visitor_hash = hashlib.sha1(dedupe_key.encode("utf-8")).hexdigest()[:12]
    visitor_id = f"visitor-{visitor_hash}"
    user: dict[str, Any] | None = None
    try:
        session = request.session
    except (RuntimeError, AssertionError):
        session = {}
    if isinstance(session, dict):
        raw_user = session.get("user")
        if isinstance(raw_user, dict):
            user = raw_user
    website_user_id = _clean_discord_id(user.get("id")) if isinstance(user, dict) else None
    website_display_name = _user_display_name(user) if isinstance(user, dict) else ""

    with _SITE_VISIT_LOG_LOCK:
        _ensure_site_visit_log_loaded()
        _SITE_VISIT_RECENT.pop(visitor_id, None)
        _SITE_VISIT_RECENT[visitor_id] = {
            "visitorId": visitor_id,
            "websiteUserId": website_user_id or "",
            "displayName": website_display_name or "Guest",
            "ip": ip,
            "path": path,
            "userAgent": user_agent,
            "lastSeen": now,
        }
        while len(_SITE_VISIT_RECENT) > _SITE_VISIT_RECENT_MAX:
            # dicts keep insertion order and we re-insert on every hit, so the
            # first key is the least recently seen visitor.
            _SITE_VISIT_RECENT.pop(next(iter(_SITE_VISIT_RECENT)), None)

        seen_for_day = _SITE_VISIT_SEEN_KEYS.setdefault(day_key, set())
        if visitor_hash not in seen_for_day and len(seen_for_day) < _SITE_VISIT_SEEN_MAX_PER_DAY:
            seen_for_day.add(visitor_hash)
            _SITE_VISIT_DAILY[day_key] = int(_SITE_VISIT_DAILY.get(day_key, 0) or 0) + 1

        if (
            _SITE_VISIT_LAST_MAINTENANCE is not None
            and now - _SITE_VISIT_LAST_MAINTENANCE < _SITE_VISIT_MAINTENANCE_INTERVAL
        ):
            return
        _SITE_VISIT_LAST_MAINTENANCE = now

        for existing_day in list(_SITE_VISIT_SEEN_KEYS.keys()):
            if existing_day != day_key:
                _SITE_VISIT_SEEN_KEYS.pop(existing_day, None)

        cutoff_date = (now - timedelta(days=45)).date()
        for existing_day in list(_SITE_VISIT_DAILY.keys()):
            try:
                parsed_day = datetime.strptime(existing_day, "%Y-%m-%d").date()
            except ValueError:
                _SITE_VISIT_DAILY.pop(existing_day, None)
                continue
            if parsed_day < cutoff_date:
                _SITE_VISIT_DAILY.pop(existing_day, None)

        stale_threshold = now - timedelta(hours=24)
        for visitor_key, visitor_entry in list(_SITE_VISIT_RECENT.items()):
            last_seen = visitor_entry.get("lastSeen")
            if isinstance(last_seen, datetime) and last_seen < stale_threshold:
                _SITE_VISIT_RECENT.pop(visitor_key, None)

        _persist_site_visit_log()


def _recent_site_visitors_snapshot(limit: int = 100) -> list[dict[str, str]]:
    bounded_limit = max(1, min(int(limit), 500))
    now = datetime.now(timezone.utc)
    with _SITE_VISIT_LOG_LOCK:
        rows = list(_SITE_VISIT_RECENT.values())
    rows.sort(key=lambda row: row.get("lastSeen", datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    payload: list[dict[str, str]] = []
    for row in rows[:bounded_limit]:
        last_seen = row.get("lastSeen")
        if not isinstance(last_seen, datetime):
            last_seen = now
        payload.append(
            {
                "visitorId": str(row.get("visitorId") or ""),
                "websiteUserId": str(row.get("websiteUserId") or ""),
                "displayName": str(row.get("displayName") or "Guest"),
                "ip": str(row.get("ip") or "Unknown"),
                "path": str(row.get("path") or "/"),
                "userAgent": str(row.get("userAgent") or "Unknown"),
                "lastSeen": last_seen.isoformat(),
                "lastSeenLabel": last_seen.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        )
    return payload


# Accounts this process has written to the website user registry already.
_REMEMBERED_WEBSITE_USERS: set[str] = set()


async def _remember_website_user(user: Any, *, refresh: bool = False) -> None:
    """Add a signed-in Discord account to the registry the admin console opens cases from.

    Each sign-in refreshes the entry. Otherwise an account is written once per
    process, which also picks up sessions from before the registry existed.
    """

    user_id = _clean_discord_id(user.get("id")) if isinstance(user, dict) else None
    if not user_id or (user_id in _REMEMBERED_WEBSITE_USERS and not refresh):
        return
    try:
        await run_blocking(record_website_user, user)
    except Exception:
        logger.exception("Could not record website user %s", user_id)
        return
    _REMEMBERED_WEBSITE_USERS.add(user_id)


def _registered_users_snapshot() -> list[dict[str, Any]]:
    """Everyone who has signed in to the website, most recently seen first. Storage errors propagate."""

    return [
        {
            "discordUserId": entry["id"],
            "displayName": entry["global_name"] or entry["username"] or entry["id"],
            "username": entry["username"] or "",
            "avatarUrl": _avatar_url(entry) or "",
            "firstSeenAt": entry["first_seen_at"] or "",
            "lastSeenAt": entry["last_seen_at"] or "",
        }
        for entry in list_website_users()
    ]


def _monthly_site_visits(days: int = 30) -> int:
    today = datetime.now(timezone.utc).date()
    earliest = today - timedelta(days=max(days - 1, 0))
    with _SITE_VISIT_LOG_LOCK:
        _ensure_site_visit_log_loaded()
        total = 0
        for day_key, count in _SITE_VISIT_DAILY.items():
            try:
                parsed_day = datetime.strptime(day_key, "%Y-%m-%d").date()
            except ValueError:
                continue
            if parsed_day >= earliest:
                total += max(int(count), 0)
        return total


def _serialize_activity_log(log: dict[str, Any]) -> dict[str, str]:
    stamp = log.get("time")
    if not isinstance(stamp, datetime):
        stamp = datetime.now(timezone.utc)
    return {
        "type": str(log.get("type") or "activity"),
        "user": str(log.get("user") or "Unknown"),
        "ip": str(log.get("ip") or "Unknown"),
        "time": stamp.isoformat(),
        "timeLabel": stamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def _ensure_activity_log_loaded() -> None:
    """Restore the feed saved before the last restart. Call with the lock held."""

    global _ACTIVITY_LOG_LOADED
    if _ACTIVITY_LOG_LOADED:
        return
    _ACTIVITY_LOG_LOADED = True
    try:
        payload = read_json(_ACTIVITY_LOG_STORAGE_KEY)
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("Failed to load the admin activity log from persistent storage")
        return

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return
    restored: list[dict[str, Any]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        occurred_at = _parse_presence_timestamp(raw_entry.get("time"))
        if occurred_at is None:
            continue
        restored.append(
            _activity_entry(
                entry_type=str(raw_entry.get("type") or "activity"),
                user=str(raw_entry.get("user") or ""),
                ip=str(raw_entry.get("ip") or ""),
                event_time=occurred_at,
            )
        )
    # Anything logged since start-up is newer, so saved entries go after it.
    free_slots = max(_ACTIVITY_LOG_LIMIT - len(_ACTIVITY_LOGS), 0)
    _ACTIVITY_LOGS.extend(restored[:free_slots])


def _persist_activity_log(entries: list[dict[str, Any]]) -> None:
    serialised = []
    for entry in entries:
        item = _serialize_activity_log(entry)
        item.pop("timeLabel", None)
        serialised.append(item)
    payload = {
        "entries": serialised,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        save_json(_ACTIVITY_LOG_STORAGE_KEY, payload)
    except Exception:
        logger.exception("Failed to persist the admin activity log to storage")


def _activity_snapshot() -> list[dict[str, str]]:
    with _ACTIVITY_LOG_LOCK:
        _ensure_activity_log_loaded()
        return [_serialize_activity_log(item) for item in _ACTIVITY_LOGS]


_JWT_STAFF_ROLES = frozenset({"Admin", "Director"})


def _user_role_from_claims(claims: dict[str, Any]) -> str:
    role = str(claims.get("role") or "").strip()
    return role or "Member"


def _decode_jwt_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token")
    return payload


def _extract_bearer_token(request: Request) -> str:
    auth_header = str(request.headers.get("authorization") or "").strip()
    if not auth_header:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No token")
    prefix, _, token = auth_header.partition(" ")
    if prefix.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No token")
    return token.strip()


async def _authenticate_request(request: Request) -> dict[str, Any]:
    token = _extract_bearer_token(request)
    payload = _decode_jwt_token(token)
    request.state.jwt_user = payload
    return payload


_PORTAL_MANAGERS_CACHE_TTL_SECONDS = 30.0
_portal_managers_cache: tuple[float, frozenset[str]] | None = None


def _user_is_portal_admin(user_id: str | int | None) -> bool:
    """``can_manage_portal`` against a manager list re-read at most every 30s.

    For checks on every request (shield, presence, API tokens), where reading
    the owner settings from storage each time would be too slow.
    """

    global _portal_managers_cache
    now = time.monotonic()
    cached = _portal_managers_cache
    if cached is None or now - cached[0] >= _PORTAL_MANAGERS_CACHE_TTL_SECONDS:
        owner_settings, _etag = load_owner_settings()
        cached = (now, frozenset(str(member) for member in owner_settings.managers))
        _portal_managers_cache = cached
    return can_manage_portal(user_id, cached[1])


def _claims_role_is_current(payload: Mapping[str, Any]) -> bool:
    """Tokens live for hours; check the holder still has the role they claim."""

    user_id = _clean_discord_id(payload.get("sub"))
    role = _user_role_from_claims(dict(payload))
    if role == "Director":
        return is_owner(user_id)
    if role == "Admin":
        return _user_is_portal_admin(user_id)
    return True


def _require_staff_claims(payload: dict[str, Any]) -> dict[str, Any]:
    if _user_role_from_claims(payload) not in _JWT_STAFF_ROLES or not _claims_role_is_current(payload):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Restricted access")
    return payload


def _require_director_claims(payload: dict[str, Any]) -> dict[str, Any]:
    if _user_role_from_claims(payload) != "Director" or not _claims_role_is_current(payload):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Restricted access")
    return payload


def _mint_session_jwt(user: dict[str, Any], *, request: Request) -> str:
    user_id = str(user.get("id") or "").strip()
    display_name = _user_display_name(user) or str(user.get("username") or "Admin").strip() or "Admin"
    if _session_user_is_owner(request) or is_owner(user_id):
        role = "Director"
    elif _session_user_is_admin(request):
        role = "Admin"
    else:
        role = "Member"
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "name": display_name,
        "role": role,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + _JWT_TTL).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _publish_activity_snapshot() -> None:
    snapshot = _activity_snapshot()
    with _ACTIVITY_SUBSCRIBERS_LOCK:
        subscribers = list(_ACTIVITY_SUBSCRIBERS)
    for queue in subscribers:
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            continue

    with _ACTIVITY_SOCKET_SUBSCRIBERS_LOCK:
        sockets = list(_ACTIVITY_SOCKET_SUBSCRIBERS)
    if not sockets:
        return

    async def _broadcast() -> None:
        dead: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json({"event": "activity_update", "payload": snapshot})
            except Exception:
                dead.append(socket)
        if dead:
            with _ACTIVITY_SOCKET_SUBSCRIBERS_LOCK:
                for stale in dead:
                    _ACTIVITY_SOCKET_SUBSCRIBERS.discard(stale)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_broadcast())


def _log_activity(
    entry_type: str,
    user: str,
    ip: str,
    *,
    event_time: datetime | None = None,
    background: bool = False,
) -> None:
    """Add to the director's activity feed.

    ``background`` saves the feed off the event loop, for callers on the
    request path (middleware) that must not wait on storage.
    """

    with _ACTIVITY_LOG_LOCK:
        _ensure_activity_log_loaded()
        _ACTIVITY_LOGS.appendleft(_activity_entry(entry_type=entry_type, user=user, ip=ip, event_time=event_time))
        snapshot = list(_ACTIVITY_LOGS)
    loop = None
    if background:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    if loop is not None:
        loop.run_in_executor(None, _persist_activity_log, snapshot)
    else:
        _persist_activity_log(snapshot)
    _publish_activity_snapshot()


def _format_time_ago(delta: timedelta) -> str:
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 90:
        return "Recently"
    units = (
        (60, "minute"),
        (3600, "hour"),
        (86400, "day"),
        (604800, "week"),
        (2629800, "month"),
    )
    for index, (unit_seconds, unit_label) in enumerate(units):
        next_threshold = units[index + 1][0] if index + 1 < len(units) else None
        if next_threshold is None or seconds < next_threshold:
            amount = max(seconds // unit_seconds, 1)
            suffix = "" if amount == 1 else "s"
            return f"{amount} {unit_label}{suffix} ago"
    return "Recently"


def _list_admin_presence(*, include_ip: bool) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    with _ADMIN_PRESENCE_LOCK:
        _ensure_admin_presence_loaded()
        snapshots = [dict(value) for value in _ADMIN_PRESENCE.values()]

    snapshots.sort(
        key=lambda entry: (
            now - entry.get("last_active", now) > _ADMIN_HEARTBEAT_TIMEOUT,
            str(entry.get("name") or entry.get("id") or "").lower(),
        )
    )

    formatted: list[dict[str, Any]] = []
    for entry in snapshots:
        last_active = entry.get("last_active")
        if not isinstance(last_active, datetime):
            continue
        delta = now - last_active
        item = {
            "id": entry.get("id"),
            "name": entry.get("name") or "Unknown",
            "role": entry.get("role") or "Unknown",
            "clearance": entry.get("clearance") or "None",
            "status": "Online" if delta <= _ADMIN_HEARTBEAT_TIMEOUT else "Offline",
            "lastActive": _format_time_ago(delta),
        }
        if include_ip:
            item["ip"] = entry.get("ip") or "Unknown"
        formatted.append(item)
    return formatted


def _clean_discord_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate.isdigit():
        return None
    return candidate


def _session_user_for_api_token(request: Request) -> dict[str, Any] | None:
    try:
        session = request.session
    except (RuntimeError, AssertionError):
        return None
    if not isinstance(session, dict):
        return None
    user = session.get("user")
    if not isinstance(user, dict):
        return None
    user_id = _clean_discord_id(user.get("id"))
    if not user_id:
        return None
    normalized = dict(user)
    normalized["id"] = user_id
    return normalized


def _persist_monitored_owner_snapshot(owners: list[dict[str, Any]], fetched_at: datetime) -> None:
    payload = {
        "fetched_at": fetched_at.isoformat(),
        "owners": owners,
    }
    try:
        save_json(_MONITORED_OWNERS_STORAGE_KEY, payload)
    except Exception:
        logger.exception("Failed to persist monitored guild owner snapshot")


def _load_monitored_owner_snapshot() -> tuple[list[dict[str, Any]], datetime | None]:
    try:
        payload = read_json(_MONITORED_OWNERS_STORAGE_KEY)
    except FileNotFoundError:
        return [], None
    except Exception:
        logger.exception("Failed to load monitored guild owner snapshot")
        return [], None
    if not isinstance(payload, dict):
        return [], None
    owners = payload.get("owners")
    fetched_raw = payload.get("fetched_at")
    fetched_at: datetime | None = None
    if isinstance(fetched_raw, str):
        try:
            fetched_at = datetime.fromisoformat(fetched_raw)
        except ValueError:
            fetched_at = None
    if not isinstance(owners, list):
        return [], fetched_at
    normalized = [entry for entry in owners if isinstance(entry, dict)]
    return normalized, fetched_at


async def _refresh_monitored_guild_owner_snapshot() -> list[dict[str, Any]]:
    if not bot_token_available():
        owners, _fetched = _load_monitored_owner_snapshot()
        return owners

    guilds = await get_bot_guilds()
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    owner_guild_pairs: list[tuple[str, dict[str, Any]]] = []
    owner_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=20.0) as client:
        for guild in guilds:
            guild_id = _clean_discord_id(guild.get("id"))
            if not guild_id:
                continue
            guild_name = str(guild.get("name") or f"Guild {guild_id}")
            guild_icon = _guild_icon(guild)
            owner_id = _clean_discord_id(guild.get("owner_id"))
            if not owner_id:
                try:
                    response = await client.get(
                        f"{DISCORD_API}/guilds/{guild_id}",
                        headers=headers,
                    )
                    response.raise_for_status()
                    owner_payload = response.json()
                    owner_id = _clean_discord_id(owner_payload.get("owner_id"))
                except Exception:
                    logger.warning("Failed to resolve owner for guild %s", guild_id, exc_info=True)
                    owner_id = None
            if not owner_id:
                continue
            owner_ids.add(owner_id)
            owner_guild_pairs.append(
                (
                    owner_id,
                    {
                        "guildId": guild_id,
                        "guildName": guild_name,
                        "guildIcon": guild_icon or "",
                    },
                )
            )

    profiles = await _load_discord_profiles(owner_ids)
    presence_by_id: dict[str, dict[str, Any]] = {}
    with _ADMIN_PRESENCE_LOCK:
        _ensure_admin_presence_loaded()
        for owner_id, entry in _ADMIN_PRESENCE.items():
            if isinstance(entry, dict):
                presence_by_id[str(owner_id)] = dict(entry)

    now = datetime.now(timezone.utc)
    snapshot: list[dict[str, Any]] = []
    for owner_id, guild_info in owner_guild_pairs:
        profile = profiles.get(owner_id) or {}
        display_name = _format_username(profile) if profile else f"Owner {owner_id}"
        username = str(profile.get("username") or "").strip()
        avatar = _avatar_url(profile) if profile else None
        presence = presence_by_id.get(owner_id, {})
        last_active = presence.get("last_active")
        if isinstance(last_active, datetime):
            delta = now - last_active
            monitoring_state = "Online" if delta <= _ADMIN_HEARTBEAT_TIMEOUT else "Offline"
            last_seen = last_active.isoformat()
            last_seen_label = _format_time_ago(delta)
        else:
            monitoring_state = "Unknown"
            last_seen = ""
            last_seen_label = "No heartbeat"

        snapshot.append(
            {
                "ownerId": owner_id,
                "ownerName": display_name,
                "ownerUsername": username,
                "ownerAvatar": avatar or "",
                "guildId": guild_info["guildId"],
                "guildName": guild_info["guildName"],
                "guildIcon": guild_info["guildIcon"],
                "monitoringState": monitoring_state,
                "lastSeen": last_seen,
                "lastSeenLabel": last_seen_label,
            }
        )

    fetched_at = datetime.now(timezone.utc)
    with _MONITORED_OWNERS_LOCK:
        _MONITORED_OWNERS_CACHE["fetched_at"] = fetched_at
        _MONITORED_OWNERS_CACHE["owners"] = snapshot
    _persist_monitored_owner_snapshot(snapshot, fetched_at)
    return snapshot


async def _monitored_guild_owners_snapshot(limit: int = 100) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit), 500))
    now = datetime.now(timezone.utc)
    with _MONITORED_OWNERS_LOCK:
        fetched_at = _MONITORED_OWNERS_CACHE.get("fetched_at")
        owners = _MONITORED_OWNERS_CACHE.get("owners") or []
        if isinstance(fetched_at, datetime) and now - fetched_at < _MONITORED_OWNERS_CACHE_TTL:
            return list(owners)[:bounded]

    try:
        refreshed = await _refresh_monitored_guild_owner_snapshot()
        return refreshed[:bounded]
    except Exception:
        logger.exception("Failed to refresh monitored guild owner snapshot")

    with _MONITORED_OWNERS_LOCK:
        owners = _MONITORED_OWNERS_CACHE.get("owners") or []
    if owners:
        return list(owners)[:bounded]

    loaded, fetched_at = _load_monitored_owner_snapshot()
    if loaded:
        with _MONITORED_OWNERS_LOCK:
            _MONITORED_OWNERS_CACHE["owners"] = loaded
            _MONITORED_OWNERS_CACHE["fetched_at"] = fetched_at
        return loaded[:bounded]
    return []


async def _registered_servers_snapshot() -> dict[str, Any]:
    """Servers the bot is in, plus blacklisted ones it may have left, sorted by name."""

    servers: dict[str, dict[str, Any]] = {}
    bot_servers_available = True
    try:
        bot_guilds = await get_bot_guilds()
    except httpx.HTTPError as exc:
        logger.warning("Could not load the bot's Discord servers (%s)", _describe_discord_error(exc))
        bot_guilds = []
        bot_servers_available = False
    if not bot_token_available():
        bot_servers_available = False
    for guild in bot_guilds:
        if not isinstance(guild, dict) or not guild.get("id"):
            continue
        guild_id = str(guild["id"])
        servers[guild_id] = {
            "serverId": guild_id,
            "name": str(guild.get("name") or guild_id),
            "iconUrl": _guild_icon(guild) or "",
            "botPresent": True,
            "blacklisted": False,
        }

    blacklist_available = True
    try:
        blacklist = await run_blocking(list_blacklisted_guilds)
    except Exception:
        logger.exception("Could not read the server blacklist")
        blacklist = []
        blacklist_available = False
    for entry in blacklist:
        server = servers.setdefault(
            entry["guild_id"],
            {
                "serverId": entry["guild_id"],
                "name": entry["name"] or entry["guild_id"],
                "iconUrl": "",
                "botPresent": False,
            },
        )
        server["blacklisted"] = True

    return {
        "servers": sorted(servers.values(), key=lambda server: server["name"].lower()),
        "botServersAvailable": bot_servers_available,
        "blacklistAvailable": blacklist_available,
    }


async def _fetch_discord_profile(
    user_id: str, *, client: httpx.AsyncClient, headers: dict[str, str]
) -> dict | None:
    try:
        resp = await client.get(f"{DISCORD_API}/users/{user_id}", headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:  # pragma: no cover - defensive log
        if exc.response.status_code != status.HTTP_404_NOT_FOUND:
            logger.warning("Failed to fetch Discord profile for %s: %s", user_id, exc)
        return None
    except httpx.HTTPError:
        logger.exception("Discord profile lookup failed for %s", user_id)
        return None
    return resp.json()


async def _load_discord_profiles(user_ids: Iterable[str]) -> dict[str, dict]:
    """Load Discord user objects for ``user_ids`` using the bot token."""

    now = datetime.now(timezone.utc)
    _prune_admin_profile_cache(now=now)
    if not bot_token_available():
        return {}

    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    cached: dict[str, dict] = {}
    pending: list[str] = []
    seen: set[str] = set()
    for candidate in user_ids:
        cleaned = _clean_discord_id(candidate)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        cached_entry = _ADMIN_PROFILE_CACHE.get(cleaned)
        if cached_entry and now - cached_entry[0] < _ADMIN_PROFILE_CACHE_TTL:
            cached[cleaned] = cached_entry[1]
            continue
        pending.append(cleaned)

    if not pending:
        return cached

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_discord_profile(user_id, client=client, headers=headers)
            for user_id in pending
        ]
        results = await asyncio.gather(*tasks)

    for user_id, profile in zip(pending, results):
        if not profile:
            continue
        cached[user_id] = profile
        _ADMIN_PROFILE_CACHE[user_id] = (now, profile)

    _prune_admin_profile_cache(now=now)

    return cached


async def _build_admin_roster_entries(
    admin_ids: Iterable[str],
    bios: Mapping[str, AdminBio],
    current_user_id: str | None,
    ranks: Mapping[str, str] | None = None,
    clearances: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    profiles = await _load_discord_profiles(admin_ids)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_id in admin_ids:
        user_id = _clean_discord_id(raw_id)
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        profile = profiles.get(user_id)
        name = _format_username(profile) if profile else f"Admin {user_id}"
        username = profile.get("username") if isinstance(profile, dict) else None
        avatar = _avatar_url(profile or {})
        display_initials = _guild_initials(name)
        bio_entry = bios.get(user_id)
        bio_text = normalise_bio_text(bio_entry.bio if bio_entry else "")
        role_text = normalise_rank_text(ranks.get(user_id) if ranks else "") or "System Overseer"
        clearance_text = normalise_clearance_text(
            clearances.get(user_id) if clearances else ""
        ) or "Omega-9"
        entries.append(
            {
                "id": user_id,
                "name": name,
                "username": username,
                "role": role_text,
                "avatar": avatar,
                "clearance": clearance_text,
                "initials": display_initials,
                "bio": bio_text,
                "profile_url": f"https://discord.com/users/{user_id}",
                "can_edit": current_user_id == user_id,
                "has_bio": bool(bio_text.strip()),
            }
        )
    return entries


def _default_admin_team_member_ids(owner_settings: OwnerSettings) -> list[str]:
    member_ids: list[str] = []
    seen: set[str] = set()
    for candidate in [OWNER_USER_KEY, *owner_settings.managers]:
        cleaned = _clean_discord_id(candidate)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            member_ids.append(cleaned)
    return member_ids


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
    await _remember_website_user(user)

    try:
        user_guilds = await get_user_guilds(token)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else None
        if status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            logger.info(
                "Discord rejected the OAuth token while loading guilds; clearing session and forcing re-auth."
            )
            request.session.pop("discord_token", None)
            request.session.pop("user", None)
            request.session.pop("guilds", None)
            request.session.pop("bot_guild_count", None)
            return None, []
        logger.exception(
            "Failed to load guild list for user %s", user.get("id", "<unknown>")
        )
        request.session["guilds"] = []
        request.session.pop("bot_guild_count", None)
        return user, []
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


def _session_user_is_admin(request: Request) -> bool:
    """Return ``True`` when the session represents a portal admin."""

    try:
        session = request.session
    except (RuntimeError, AssertionError):
        return False
    if not isinstance(session, dict):
        return False
    user = session.get("user")
    if not user:
        return False
    user_id = user.get("id")
    if not user_id:
        return False
    owner_settings, _ = load_owner_settings()
    return can_manage_portal(str(user_id), owner_settings.managers)


def _session_user_is_owner(request: Request) -> bool:
    """Return ``True`` when the session represents the configured owner."""

    try:
        session = request.session
    except (RuntimeError, AssertionError):
        return False
    if not isinstance(session, dict):
        return False
    user = session.get("user")
    if not isinstance(user, dict):
        return False
    user_id = user.get("id")
    if not user_id:
        return False
    return is_owner(user_id)


def _extract_actor_user_id(actor: str | None) -> str | None:
    """Return the numeric Discord ID embedded in the lock ``actor`` string."""

    if actor is None:
        return None
    cleaned = str(actor).strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return cleaned
    if "(" in cleaned and ")" in cleaned:
        inner = cleaned.rsplit("(", 1)[1]
        inner = inner.split(")", 1)[0].strip()
        digits = "".join(ch for ch in inner if ch.isdigit())
        if digits:
            return digits
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    return digits or None


def _session_user_matches_lock_actor(request: Request, state: Mapping[str, Any] | None) -> bool:
    """Return ``True`` when the session user matches the lock actor."""

    if not isinstance(state, Mapping):
        return False
    actor_id = _extract_actor_user_id(state.get("actor"))
    if not actor_id:
        return False
    try:
        session = request.session
    except (RuntimeError, AssertionError):
        return False
    if not isinstance(session, dict):
        return False
    user = session.get("user")
    if not isinstance(user, dict):
        return False
    user_id = user.get("id")
    if not user_id:
        return False
    return str(user_id) == actor_id


def _basic_auth_allows_admin(request: Request) -> bool:
    """Return ``True`` when HTTP Basic credentials unlock admin access."""

    header = request.headers.get("Authorization")
    if not header:
        return False
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, _, password = decoded.partition(":")
    if not password:
        return False
    return bool(ADMIN_USER and ADMIN_PASS) and compare_digest(username, ADMIN_USER) and compare_digest(password, ADMIN_PASS)


_MAINTENANCE_POLL_SECONDS = 30
_LOCK_MESSAGE_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _public_lock_actor_name(actor: Any) -> str | None:
    """Return the lock actor's display name without the trailing Discord ID."""

    if actor is None:
        return None
    cleaned = str(actor).strip()
    name, sep, tail = cleaned.rpartition(" (")
    if sep and tail.endswith(")") and tail[:-1].strip().isdigit():
        cleaned = name.strip()
    if cleaned.isdigit():
        return None
    return cleaned or None


def _parse_lock_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_lock_timestamp(value: Any) -> str:
    """Return a readable UTC label such as ``24 Oct 2026, 06:59 UTC``."""

    parsed = _parse_lock_timestamp(value)
    if parsed is None:
        return str(value).strip() if value else ""
    return f"{parsed.day} {parsed:%b %Y, %H:%M} UTC"


def _render_lock_time(value: Any) -> str:
    parsed = _parse_lock_timestamp(value)
    if parsed is None:
        return html.escape(str(value))
    return (
        f"<time datetime=\"{parsed.isoformat(timespec='seconds')}\" data-lock-time>"
        f"{html.escape(_format_lock_timestamp(parsed.isoformat()))}</time>"
        "<span class=\"rel\" data-rel hidden></span>"
    )


def _render_lock_message_html(message: str) -> str:
    """Escape the lockdown reason and turn bare http(s) URLs into links."""

    parts: list[str] = []
    last = 0
    for match in _LOCK_MESSAGE_URL_RE.finditer(message):
        url = match.group(0).rstrip(".,;:!?)]")
        parts.append(html.escape(message[last:match.start()]))
        safe_url = html.escape(url)
        parts.append(
            f"<a href=\"{safe_url}\" target=\"_blank\" rel=\"noopener noreferrer nofollow\">{safe_url}</a>"
        )
        last = match.start() + len(url)
    parts.append(html.escape(message[last:]))
    return "".join(parts)


def _wasp_player_markup() -> str:
    """The W.A.S.P. player include, for pages built outside a template response."""

    if templates is None:
        return ""
    try:
        return templates.get_template("_wasp_player.html").render()
    except Exception:
        logger.exception("Failed to render the W.A.S.P. player")
        return ""


def _build_maintenance_response(state: Mapping[str, Any], *, preview: bool = False) -> HTMLResponse:
    """Render the maintenance screen shown to non-admin visitors.

    The middleware intercepts every path while the lock is active (static
    assets included), so the page must stay self-contained apart from the
    W.A.S.P. player, whose files the middleware lets through.
    """

    brand = html.escape(BRAND)
    message = clean_site_lock_message(state.get("message"))
    has_reason = message != SITE_LOCK_MESSAGE_DEFAULT
    reason_block = (
        "<section class=\"notice\" aria-labelledby=\"notice-label\">"
        "<div class=\"notice-label\" id=\"notice-label\">Update from the team</div>"
        f"<p class=\"notice-body\">{_render_lock_message_html(message)}</p>"
        "</section>"
        if has_reason
        else ""
    )

    meta_items: list[str] = []
    activated_at = state.get("enabled_at")
    if activated_at:
        meta_items.append(f"<div><dt>Started</dt><dd>{_render_lock_time(activated_at)}</dd></div>")
    updated_at = state.get("updated_at")
    started = _parse_lock_timestamp(activated_at)
    updated = _parse_lock_timestamp(updated_at)
    if has_reason and updated and (started is None or (updated - started).total_seconds() >= 60):
        meta_items.append(f"<div><dt>Last update</dt><dd>{_render_lock_time(updated_at)}</dd></div>")
    actor_name = _public_lock_actor_name(state.get("actor"))
    if actor_name:
        meta_items.append(f"<div><dt>Initiated by</dt><dd>{html.escape(actor_name)}</dd></div>")
    meta_block = f"<dl class=\"meta\">{''.join(meta_items)}</dl>" if meta_items else ""

    preview_bar = (
        "<div class=\"preview-bar\" role=\"status\">Preview &middot; visitors see this page while the lockdown is active</div>"
        if preview
        else ""
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <meta name="color-scheme" content="dark">
  <title>{brand} &middot; Maintenance in progress</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/wasp_global_player.css?v=20261026a">
  <style>
    :root {{
      --bg: #080a0d;
      --card: rgba(15, 19, 24, 0.82);
      --edge: rgba(153, 164, 174, 0.16);
      --text: #eef2fb;
      --muted: #9ba6b1;
      --faint: #667381;
      --accent: #b1cda5;
      --amber: #f5b13d;
      /* The W.A.S.P. player in SPECTRE green (spectre_theme.css is not reachable here). */
      --wasp-player-border: rgba(142, 167, 132, 0.4);
      --wasp-player-bg: rgba(7, 11, 15, 0.92);
      --wasp-player-text: #d7dde5;
      --wasp-player-title: #8ea784;
      --wasp-player-divider: #182028;
      --wasp-player-track: #f3f6f8;
      --wasp-player-time: #7c8994;
      --wasp-player-accent: #8ea784;
      --wasp-player-volume: #9aa6b1;
      --wasp-player-status: #8ea784;
      --wasp-player-btn-border: #314136;
      --wasp-player-btn-bg: #0d1511;
      --wasp-player-btn-text: #d7dde5;
      --wasp-player-btn-hover-border: #8ea784;
      --wasp-player-btn-hover-bg: #223027;
      --wasp-player-btn-active-border: #8ea784;
      --wasp-player-btn-active-bg: #2c3d31;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{
      min-height: 100vh;
      min-height: 100dvh;
      display: grid;
      place-items: center;
      padding: 56px 16px 40px;
      font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
      color: var(--text);
      background:
        radial-gradient(56rem 36rem at 50% -12%, rgba(177, 205, 165, 0.11), transparent 62%),
        radial-gradient(40rem 28rem at 88% 112%, rgba(245, 177, 61, 0.07), transparent 60%),
        var(--bg);
      -webkit-font-smoothing: antialiased;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
      background-size: 44px 44px;
      -webkit-mask-image: radial-gradient(ellipse at center, #000 25%, transparent 72%);
      mask-image: radial-gradient(ellipse at center, #000 25%, transparent 72%);
    }}
    .shell {{ position: relative; width: 100%; max-width: 580px; display: grid; gap: 20px; }}
    .brand {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.34em;
      text-indent: 0.34em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .brand-mark {{
      width: 8px;
      height: 8px;
      transform: rotate(45deg);
      background: var(--accent);
      box-shadow: 0 0 14px rgba(177, 205, 165, 0.65);
    }}
    .card {{
      position: relative;
      overflow: hidden;
      padding: 36px 36px 26px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0) 38%), var(--card);
      border: 1px solid var(--edge);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 32px 80px -24px rgba(0, 0, 0, 0.7);
      -webkit-backdrop-filter: blur(14px);
      backdrop-filter: blur(14px);
    }}
    .card::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(245, 177, 61, 0.75), transparent);
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 6px 12px 6px 10px;
      border-radius: 999px;
      background: rgba(245, 177, 61, 0.1);
      border: 1px solid rgba(245, 177, 61, 0.28);
      color: #ffd690;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.04em;
    }}
    .pulse {{ position: relative; width: 8px; height: 8px; border-radius: 50%; background: var(--amber); }}
    .pulse::after {{
      content: "";
      position: absolute;
      inset: -4px;
      border-radius: 50%;
      border: 2px solid var(--amber);
      opacity: 0;
      animation: pulse 2.2s ease-out infinite;
    }}
    @keyframes pulse {{
      0% {{ transform: scale(0.5); opacity: 0.85; }}
      100% {{ transform: scale(1.6); opacity: 0; }}
    }}
    h1 {{
      margin: 20px 0 10px;
      font-size: clamp(28px, 6vw, 38px);
      line-height: 1.12;
      letter-spacing: -0.025em;
      font-weight: 700;
    }}
    .lede {{ margin: 0; color: var(--muted); font-size: 15.5px; line-height: 1.65; }}
    .notice {{
      margin-top: 24px;
      padding: 16px 18px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--edge);
      border-left: 3px solid var(--amber);
    }}
    .notice-label {{
      margin-bottom: 8px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--amber);
    }}
    .notice-body {{
      margin: 0;
      white-space: pre-line;
      overflow-wrap: anywhere;
      font-size: 15px;
      line-height: 1.65;
    }}
    .notice-body a {{ color: var(--accent); text-underline-offset: 3px; }}
    .meta {{
      margin: 24px 0 0;
      display: flex;
      flex-wrap: wrap;
      gap: 1px;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--edge);
      background: var(--edge);
    }}
    .meta > div {{ flex: 1 1 150px; padding: 12px 14px; background: #0e1115; }}
    .meta dt {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--faint); }}
    .meta dd {{ margin: 5px 0 0; font-size: 14px; font-weight: 500; }}
    .meta .rel {{ display: block; margin-top: 2px; font-size: 12.5px; font-weight: 400; color: var(--muted); }}
    .meta .rel[hidden] {{ display: none; }}
    .foot {{
      margin-top: 24px;
      padding-top: 18px;
      border-top: 1px solid var(--edge);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      color: var(--muted);
    }}
    .live {{ display: inline-flex; align-items: center; gap: 9px; }}
    .live-dot {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 10px rgba(177, 205, 165, 0.7);
      animation: blink 2.4s ease-in-out infinite;
    }}
    @keyframes blink {{ 50% {{ opacity: 0.3; }} }}
    .signin {{
      padding: 8px 14px;
      border-radius: 10px;
      border: 1px solid var(--edge);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      font-weight: 600;
      text-decoration: none;
      transition: border-color 0.15s ease, background 0.15s ease;
    }}
    .signin:hover, .signin:focus-visible {{
      border-color: rgba(177, 205, 165, 0.55);
      background: rgba(177, 205, 165, 0.08);
      outline: none;
    }}
    .code {{
      margin: 0;
      text-align: center;
      font: 500 11px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--faint);
    }}
    .preview-bar {{
      position: fixed;
      inset: 0 0 auto;
      z-index: 2;
      padding: 9px 16px;
      text-align: center;
      font-size: 13px;
      font-weight: 600;
      color: #1a1204;
      background: var(--amber);
    }}
    @media (max-width: 520px) {{
      .card {{ padding: 28px 20px 22px; border-radius: 16px; }}
      .foot {{ flex-direction: column; align-items: stretch; text-align: center; }}
      .live {{ justify-content: center; }}
      .signin {{ text-align: center; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .pulse::after, .live-dot {{ animation: none; }}
    }}
  </style>
</head>
<body>
  {preview_bar}
  <main class="shell">
    <div class="brand"><span class="brand-mark" aria-hidden="true"></span>{brand}</div>
    <article class="card" aria-labelledby="title">
      <div class="status"><span class="pulse" aria-hidden="true"></span>Maintenance in progress</div>
      <h1 id="title">We'll be back shortly</h1>
      <p class="lede">{brand} is temporarily offline while maintenance is carried out. Access will be restored as soon as the work is complete.</p>
      {reason_block}
      {meta_block}
      <footer class="foot">
        <span class="live"><span class="live-dot" aria-hidden="true"></span>Refreshes automatically when we're back</span>
        <a class="signin" href="/login">Administrator sign in &rarr;</a>
      </footer>
    </article>
    <p class="code">503 &middot; Service temporarily unavailable</p>
  </main>
  <script>
    (() => {{
      const relative = (ms) => {{
        const minutes = Math.max(0, Math.floor(ms / 60000));
        if (minutes < 1) return 'just now';
        if (minutes < 60) return `${{minutes}}m ago`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${{hours}}h ${{minutes % 60}}m ago`;
        const days = Math.floor(hours / 24);
        return `${{days}}d ${{hours % 24}}h ago`;
      }};
      const stamps = [...document.querySelectorAll('[data-lock-time]')];
      let localFormat = null;
      try {{
        localFormat = new Intl.DateTimeFormat(undefined, {{
          day: 'numeric', month: 'short',
          hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
        }});
      }} catch (_) {{}}
      stamps.forEach((el) => {{
        const when = new Date(el.getAttribute('datetime'));
        if (Number.isNaN(when.getTime()) || !localFormat) return;
        el.title = el.textContent;
        el.textContent = localFormat.format(when);
      }});
      const tick = () => stamps.forEach((el) => {{
        const when = new Date(el.getAttribute('datetime'));
        const rel = el.parentElement.querySelector('[data-rel]');
        if (!rel || Number.isNaN(when.getTime())) return;
        rel.textContent = relative(Date.now() - when.getTime());
        rel.hidden = false;
      }});
      tick();
      window.setInterval(tick, 30000);

      if ({'true' if preview else 'false'}) return;
      let checking = false;
      const check = async () => {{
        if (checking || document.hidden) return;
        checking = true;
        try {{
          const res = await fetch(window.location.href, {{ cache: 'no-store', credentials: 'same-origin', redirect: 'manual' }});
          if (res.status !== 503 && res.status < 500) window.location.reload();
        }} catch (_) {{
        }} finally {{
          checking = false;
        }}
      }};
      window.setInterval(check, {_MAINTENANCE_POLL_SECONDS * 1000});
      document.addEventListener('visibilitychange', check);
    }})();
  </script>
  {_wasp_player_markup()}
</body>
</html>
"""
    status_code = status.HTTP_200_OK if preview else status.HTTP_503_SERVICE_UNAVAILABLE
    return HTMLResponse(html_doc, status_code=status_code)


def _build_website_block_response(block: Mapping[str, Any]) -> HTMLResponse:
    """Notice shown to an account with an active website ban or suspension."""

    brand = html.escape(BRAND)
    is_ban = block.get("sanction") == "ban" and not block.get("endsAt")
    title = "Your access has been revoked" if is_ban else "Your access is suspended"
    reason = str(block.get("reason") or "").strip()
    reason_block = (
        f"<div class=\"notice\"><div class=\"notice-label\">Reason</div><p>{html.escape(reason)}</p></div>"
        if reason
        else ""
    )
    until = ""
    if block.get("endsAt"):
        until = f"<p class=\"meta\">Suspended until {_render_lock_time(block['endsAt'])}</p>"
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <link rel="stylesheet" href="/static/spectre_theme.css">
  <link rel="stylesheet" href="/static/wasp_global_player.css?v=20261026a">
  <title>{brand} &middot; Access restricted</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 48px 16px;
      background: radial-gradient(52rem 32rem at 50% -12%, rgba(142, 167, 132, 0.1), transparent 62%), var(--sp-bg);
      color: var(--sp-text); font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }}
    .card {{ width: 100%; max-width: 520px; padding: 32px; border: 1px solid var(--sp-border); border-radius: 16px;
      background: var(--sp-panel); box-shadow: 0 30px 70px -24px rgba(0, 0, 0, 0.7); }}
    .eyebrow {{ font-size: 11px; letter-spacing: 0.24em; text-transform: uppercase; color: var(--sp-label); margin: 0 0 14px; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(24px, 5vw, 30px); letter-spacing: -0.01em; }}
    p {{ margin: 0; line-height: 1.6; color: var(--sp-muted); }}
    .notice {{ margin-top: 20px; padding: 14px 16px; border-left: 3px solid #e5484d; border-radius: 10px;
      background: rgba(255, 255, 255, 0.03); }}
    .notice-label {{ font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: #ff8a8a; margin-bottom: 6px; }}
    .notice p {{ color: var(--sp-text); white-space: pre-line; }}
    .meta {{ margin-top: 16px; font-size: 14px; }}
    .meta .rel {{ margin-left: 6px; }}
    a {{ display: inline-block; margin-top: 22px; color: var(--sp-accent); text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <main class="card">
    <p class="eyebrow">{brand} &middot; Moderation</p>
    <h1>{title}</h1>
    <p>You have been signed out. If you think this is a mistake, contact the {brand} admin team on Discord.</p>
    {reason_block}
    {until}
    <a href="/">Return to the homepage</a>
  </main>
  {_wasp_player_markup()}
</body>
</html>
"""
    return HTMLResponse(html_doc, status_code=status.HTTP_403_FORBIDDEN)


def _war_outcome_copy(state: Mapping[str, Any] | None, war_status: str) -> str:
    payload = state if isinstance(state, Mapping) else {}
    message = str(payload.get("war_outcome_message") or "").strip()
    if war_status == "victory":
        return message or "Pyro secured. War map locked while command redeploys."
    if war_status == "retreat":
        return message or "Command ordered a strategic withdrawal. War map locked while fleets regroup."
    return message


def _normalise_health_status(value) -> str:
    key = str(value or "").strip().lower()
    if key in _HEALTH_STATUS_OPTIONS:
        return key
    return "online"


def _pop_owner_flash(request: Request) -> dict | None:
    return _pop_flash(request, _OWNER_FLASH_KEY)


def _pop_fleet_flash(request: Request) -> dict | None:
    return _pop_flash(request, _FLEET_FLASH_KEY)


def _pop_panel_flash(request: Request) -> dict | None:
    return _pop_flash(request, _PANEL_FLASH_KEY)


def _push_panel_flash(request: Request, status_label: str, message: str) -> None:
    _push_flash(request, _PANEL_FLASH_KEY, status_label=status_label, message=message)


def _pop_chat_access_flash(request: Request) -> dict | None:
    return _pop_flash(request, _CHAT_ACCESS_FLASH_KEY)


def _push_chat_access_flash(request: Request, status_label: str, message: str) -> None:
    _push_flash(request, _CHAT_ACCESS_FLASH_KEY, status_label=status_label, message=message)


def _pop_flash(request: Request, key: str) -> dict[str, Any] | None:
    data = request.session.get(key)
    if data is not None:
        request.session.pop(key, None)
    return data if isinstance(data, dict) else None


def _push_flash(request: Request, key: str, *, status_label: str, message: str) -> None:
    if not message:
        return
    request.session[key] = {
        "status": status_label,
        "message": message,
    }


def _render_panel_flash_block(data: dict | None) -> str:
    if not data:
        return ""
    message = str(data.get("message") or "").strip()
    if not message:
        return ""
    tone = str(data.get("status") or "info").strip().lower()
    if tone not in {"success", "error", "warn", "info"}:
        tone = "info"
    return f"<div class=\"flash flash--{tone}\">{html.escape(message)}</div>"


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


def _render_system_health_fact_value(state: Mapping[str, Any] | None) -> str:
    payload = state if isinstance(state, Mapping) else {}
    status = _normalise_health_status(payload.get("status"))
    option = _HEALTH_STATUS_OPTIONS.get(status, _HEALTH_STATUS_OPTIONS["online"])
    label = html.escape(option.get("label", status.title()))
    note = str(payload.get("note") or "").strip()
    if not note and status == "online":
        note = option.get("default_note", "")
    note_block = f"<span class=\"health-note\">{html.escape(note)}</span>" if note else ""
    return (
        "<div class=\"fact-health\">"
        f"<span class=\"status-chip {option['chip']}\">{label}</span>"
        f"{note_block}"
        "</div>"
    )


def _get_bot_uptime_fact() -> tuple[str, str]:
    start_time = _get_process_start_time()
    uptime_delta = _now() - start_time
    uptime_value = _format_duration_compact(uptime_delta)
    start_display = start_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    hint = f"Online since {start_display}."
    return uptime_value, hint


def _get_next_restart_fact() -> tuple[str, str, str | None]:
    state = read_restart_state() or {}
    started_at = state.get("started_at") if isinstance(state, dict) else None
    next_restart = state.get("next_restart_at") if isinstance(state, dict) else None

    if started_at is None:
        started_at = _get_process_start_time()
    if next_restart is None:
        schedule = get_process_restart_schedule() or get_restart_schedule()
        next_restart = compute_next_restart(started_at, schedule)

    if next_restart is None:
        return (
            "Disabled",
            "Automatic restart is disabled via SPECTRE_PROCESS_RESTART_DAYS and SPECTRE_AUTO_RESTART_DAYS.",
            None,
        )

    remaining = max(next_restart - _now(), timedelta(seconds=0))
    countdown = _format_duration_compact(remaining)
    next_display = next_restart.strftime("%Y-%m-%d %H:%M:%S %Z")
    value = f"in {countdown}"
    hint = f"Next planned process restart at {next_display}."
    return value, hint, next_restart.astimezone(timezone.utc).isoformat()


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
    health_state = get_system_health_state()

    facts: list[dict[str, Any]] = []

    def add_fact(label: str, value: str, hint: str, *, safe: bool = False) -> None:
        facts.append({"label": label, "value": value, "hint": hint, "safe": safe})

    if guild_count is not None:
        hint = (
            "Discord servers currently running the bot."
            if guild_count
            else "Invite the bot to a server to begin operations."
        )
        add_fact("Active servers", _format_number(int(guild_count)), hint)
    else:
        if not bot_token_available():
            hint = "Configure the bot token to unlock deployment stats."
        elif guild_count_error:
            hint = "Temporarily unable to reach Discord for deployment stats."
        else:
            hint = "Deployment data is temporarily unavailable."
        add_fact("Active servers", "—", hint)

    if files_total is not None:
        file_hint = (
            "Files indexed across every dossier category."
            if files_total
            else "No dossiers have been archived yet."
        )
        add_fact("Archive dossiers", _format_number(files_total), file_hint)
    else:
        add_fact(
            "Archive dossiers",
            "—",
            "Storage is unreachable right now; totals will update once connectivity returns.",
        )

    if configs_total is not None:
        config_hint = (
            "Guild configuration profiles stored in the archive."
            if configs_total
            else "No configuration profiles saved yet."
        )
        add_fact("Config profiles", _format_number(configs_total), config_hint)
    else:
        add_fact("Config profiles", "—", "Unable to read configuration storage right now.")

    if operator_total is not None:
        operator_hint = (
            "Operators with active ID codes in the roster."
            if operator_total
            else "No operator records have been registered yet."
        )
        add_fact("Registered operators", _format_number(operator_total), operator_hint)
    else:
        add_fact(
            "Registered operators",
            "—",
            "Operator registry is temporarily unavailable.",
        )

    uptime_value, uptime_hint = _get_bot_uptime_fact()
    add_fact("Current uptime", uptime_value, uptime_hint)

    restart_value, restart_hint, restart_iso = _get_next_restart_fact()
    add_fact("Next scheduled restart", restart_value, restart_hint)

    health_value = _render_system_health_fact_value(health_state)
    add_fact(
        "System health",
        health_value,
        "Status broadcast from the last system check.",
        safe=True,
    )

    items = []
    for fact in facts:
        label_html = html.escape(str(fact.get("label", "")))
        value_raw = str(fact.get("value", ""))
        if fact.get("safe"):
            value_html = value_raw
        else:
            value_html = html.escape(value_raw).replace("\n", "<br>")
        if str(fact.get("label", "")) == "Next scheduled restart" and restart_iso:
            value_html = (
                f'<span data-restart-countdown="{html.escape(restart_iso)}">{value_html}</span>'
            )
        hint_value = fact.get("hint")
        hint_html = (
            html.escape(str(hint_value)).replace("\n", "<br>") if hint_value else ""
        )
        hint_block = f"<div class=\"fact-hint\">{hint_html}</div>" if hint_html else ""
        item_html = "".join(
            [
                "<div class=\"fact\">",
                f"  <div class=\"fact-label\">{label_html}</div>",
                f"  <div class=\"fact-value\">{value_html}</div>",
                f"  {hint_block}",
                "</div>",
            ]
        )
        items.append(item_html)

    return "".join(items)


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
    live_bot_token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if bot_available and live_bot_token:
        try:
            bot_guilds = await get_bot_guilds()
        except httpx.HTTPError as exc:
            logger.exception("Discord API request failed while validating bot membership")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Failed to validate guild access via the Discord API.",
            ) from exc
    else:
        bot_available = False
        bot_guilds = []
        request.session.pop("bot_guild_count", None)

    common = _filter_common_guilds(user_guilds, bot_guilds)
    request.session["guilds"] = common
    if bot_available and live_bot_token:
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
    raw = r.json()
    categories = [
        {"id": x["id"], "name": x["name"], "position": x.get("position", 0)}
        for x in raw
        if x.get("type") == 4
    ]
    channels = [
        {
            "id": x["id"],
            "name": x["name"],
            "type": x["type"],
            "parent_id": x.get("parent_id"),
            "position": x.get("position", 0),
        }
        for x in raw
        if x.get("type") in (0, 5, 15)
    ]
    return {"channels": channels, "categories": categories}


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

    context = _inject_wallpaper(
        {
            "request": request,
            "accent": ACCENT,
            "brand": BRAND,
            "guild_name": guild_display_name,
            "guild_avatar": guild_avatar_html,
            "guild_id": str(guild_id),
            "guild_id_js": json.dumps(str(guild_id)),
            "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
        },
        "panel",
    )
    return templates.TemplateResponse(request, "panel.html", context)



def _render_war_outcome_page(request: Request, desired_status: str):
    state = load_pyro_war_state()
    war_status = str(state.get("war_status") or "active").strip().lower()
    if war_status not in _WAR_STATUS_VALUES:
        war_status = "active"

    if war_status == "active":
        return RedirectResponse(url="/operations/pyro-war", status_code=status.HTTP_303_SEE_OTHER)
    if war_status != desired_status:
        target_map = {
            "victory": "/operations/pyro-war/victory",
            "retreat": "/operations/pyro-war/retreat",
        }
        target = target_map.get(war_status, "/operations/pyro-war")
        return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)

    if templates is None:
        return JSONResponse(
            {"war_status": war_status, "message": _war_outcome_copy(state, war_status)}
        )

    is_admin_viewer = _session_user_is_admin(request) or _session_user_is_owner(request)
    context = {
        "request": request,
        "brand": BRAND,
        "accent": ACCENT,
        "war_status": war_status,
        "outcome_title": "Victory declared" if war_status == "victory" else "Strategic withdrawal",
        "outcome_message": _war_outcome_copy(state, war_status),
        "is_admin_viewer": is_admin_viewer,
    }
    return templates.TemplateResponse(request, "pyro_war_outcome.html", context)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    user_id = str(user.get("id")) if user and user.get("id") else None
    can_manage_owner_portal = can_manage_portal(user_id, owner_settings.managers)
    is_owner_viewer = _session_user_is_owner(request)
    latest_update = owner_settings.latest_update.strip()
    latest_update_priority = normalise_broadcast_priority(
        owner_settings.latest_update_priority
    )
    health_state = get_system_health_state()
    health_status = _normalise_health_status(health_state.get("status"))
    health_option = _HEALTH_STATUS_OPTIONS.get(health_status, _HEALTH_STATUS_OPTIONS["online"])
    health_note = str(health_state.get("note") or "").strip()
    if not health_note and health_status == "online":
        health_note = str(health_option.get("default_note") or "").strip()
    health_class = {
        "online": "health-status--online",
        "maintenance": "health-status--maintenance",
        "degraded": "health-status--degraded",
        "offline": "health-status--offline",
    }.get(health_status, "health-status--online")

    if templates is None:
        return HTMLResponse(
            "<html><body><h1>Project Spectre</h1><p>Landing page unavailable.</p></body></html>"
        )

    display_name = ""
    if user:
        display_name = (
            str(user.get("global_name") or "").strip()
            or str(user.get("username") or "").strip()
        )

    context = {
        "request": request,
        "brand": BRAND,
        "is_authenticated": bool(user),
        "display_name": display_name,
        "show_director_link": bool(is_owner_viewer),
        "show_admin_link": bool(can_manage_owner_portal),
        "latest_update": latest_update,
        "latest_update_priority": latest_update_priority,
        "system_health_label": str(health_option.get("label") or health_status.title()).upper(),
        "system_health_note": health_note,
        "system_health_class": health_class,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/features", include_in_schema=False)
async def features_page(request: Request):
    tos_redirect = _require_tos_consent(request)
    if tos_redirect:
        return tos_redirect

    user, _guilds = await _load_user_context(request)

    if templates is None:
        return HTMLResponse(
            "<html><body><h1>Project Spectre Features</h1><p>Feature page unavailable.</p></body></html>"
        )

    display_name = ""
    if user:
        display_name = (
            str(user.get("global_name") or "").strip()
            or str(user.get("username") or "").strip()
        )

    context = {
        "request": request,
        "brand": BRAND,
        "display_name": display_name,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(request, "features.html", context)


@app.get("/about", include_in_schema=False)
async def about_page(request: Request):
    user, _guilds = await _load_user_context(request)

    if templates is None:
        return HTMLResponse(
            "<html><body><h1>About Project Spectre</h1><p>About page unavailable.</p></body></html>"
        )

    display_name = ""
    if user:
        display_name = (
            str(user.get("global_name") or "").strip()
            or str(user.get("username") or "").strip()
        )

    context = {
        "request": request,
        "brand": BRAND,
        "display_name": display_name,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(request, "about.html", context)


@app.get("/mission-debrief-sz", include_in_schema=False)
async def mission_debrief_sz_page(request: Request):
    return await _render_wasp_map_page(request)


@app.get("/wasp", include_in_schema=False)
async def wasp_landing_page(request: Request):
    tos_redirect = _require_tos_consent(request)
    if tos_redirect:
        return tos_redirect

    user, _guilds = await _load_user_context(request)

    if templates is None:
        return HTMLResponse(
            "<html><body><h1>W.A.S.P. Section Zero</h1><p>Landing page unavailable.</p></body></html>"
        )

    display_name = ""
    if user:
        display_name = (
            str(user.get("global_name") or "").strip()
            or str(user.get("username") or "").strip()
        )

    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    context = {
        "request": request,
        "brand": BRAND,
        "display_name": display_name,
        "brand_image_url": brand_image_url,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(request, "wasp_landing.html", context)


@app.get("/spectre/archive", include_in_schema=False)
async def spectre_archive_page(request: Request):
    tos_redirect = _require_tos_consent(request)
    if tos_redirect:
        return tos_redirect

    token = request.session.get("discord_token")
    if not token:
        request.session["post_auth_redirect"] = "/spectre/archive"
        return RedirectResponse(url="/login")

    user, _managed_guilds = await _load_user_context(request)
    if user is None:
        request.session["post_auth_redirect"] = "/spectre/archive"
        return RedirectResponse(url="/login")

    display_name = (
        str(user.get("global_name") or "").strip()
        or str(user.get("username") or "").strip()
        or "Operator"
    )
    context = {
        "request": request,
        "brand": BRAND,
        "display_name": display_name,
        "guilds": await _archive_guild_options(request),
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(request, "wasp_archive.html", context)


@app.get("/wasp/archive", include_in_schema=False)
async def wasp_archive_page(request: Request):
    query = str(request.url.query or "").strip()
    target = "/spectre/archive"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


def _guild_permission_bits(guild_record: Mapping[str, Any] | None) -> int:
    if not isinstance(guild_record, Mapping):
        return 0
    perms_raw = guild_record.get("permissions")
    if perms_raw is None:
        perms_raw = guild_record.get("permissions_new")
    try:
        return int(perms_raw)
    except (TypeError, ValueError):
        return 0


def _live_bot_token() -> str:
    token = BOT_TOKEN or os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN") or ""
    return str(token).strip()


async def _archive_standing(
    request: Request, guild_id: str, user_id: str, *, refresh: bool = False
) -> archive_access.Standing:
    """The signed-in Discord account's standing in ``guild_id``, read from Discord.

    The bot fetches the member and the guild's roles, so ownership, the
    Administrator permission and roles are exactly what the Discord archive
    checks, not a copy kept in the browser session.
    """

    bot_token = _live_bot_token()
    if bot_token:
        try:
            member, guild = await asyncio.gather(
                archive_access.fetch_member(DISCORD_API, bot_token, guild_id, user_id, force=refresh),
                archive_access.fetch_guild(DISCORD_API, bot_token, guild_id, force=refresh),
            )
        except archive_access.DiscordLookupError as exc:
            logger.warning("Archive access check could not reach Discord: %s", exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Couldn't verify your Discord roles right now. Try again in a moment.",
            ) from exc
        if member is None or guild is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You are not a member of this server, or the archive bot is not in it.",
            )
        return await run_blocking(archive_access.standing_from_discord, int(guild_id), user_id, member, guild)

    # Without a bot token roles cannot be looked up. Fall back to the OAuth guild
    # list for membership, owner and Administrator; restricted files stay shut.
    try:
        user_guilds = await get_user_guilds(request.session.get("discord_token") or {})
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else None
        if status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Discord session expired. Sign in again.") from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't reach Discord. Try again in a moment.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't reach Discord. Try again in a moment.") from exc
    record = next(
        (g for g in user_guilds if isinstance(g, Mapping) and str(g.get("id")) == str(guild_id)),
        None,
    )
    if record is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this server.")
    is_owner = bool(record.get("owner"))
    is_admin = is_owner or _has_perm(_guild_permission_bits(record), ADMIN)
    return archive_access.Standing(
        user_id=user_id,
        is_owner=is_owner,
        is_admin=is_admin,
        is_high_command=is_admin,
        roles_verified=False,
    )


_BOT_GUILD_IDS_TTL_SECONDS = 60.0
_bot_guild_ids_cache: tuple[float, set[str]] | None = None


async def _cached_bot_guild_ids() -> set[str] | None:
    """IDs of guilds the bot is in, or ``None`` when that cannot be determined."""

    global _bot_guild_ids_cache
    if _bot_guild_ids_cache and time.monotonic() - _bot_guild_ids_cache[0] < _BOT_GUILD_IDS_TTL_SECONDS:
        return _bot_guild_ids_cache[1]
    if not bot_token_available():
        return None
    try:
        guilds = await get_bot_guilds()
    except httpx.HTTPError:
        logger.warning("Failed to list bot guilds for the archive server picker")
        return None
    ids = {str(g.get("id")) for g in guilds if isinstance(g, Mapping) and g.get("id") is not None}
    _bot_guild_ids_cache = (time.monotonic(), ids)
    return ids


async def _archive_guild_options(request: Request) -> list[dict[str, str]]:
    """Servers the visitor belongs to that have the archive bot.

    Unlike the dashboard, membership is enough: what a member may read is
    decided per file from their Discord roles.
    """

    try:
        user_guilds = await get_user_guilds(request.session.get("discord_token") or {})
    except httpx.HTTPError:
        logger.warning("Failed to load the visitor's guilds for the archive server picker")
        user_guilds = request.session.get("guilds") or []
    bot_ids = await _cached_bot_guild_ids()
    options: list[dict[str, str]] = []
    for guild in user_guilds:
        if not isinstance(guild, Mapping):
            continue
        gid = _clean_discord_id(guild.get("id"))
        if not gid or (bot_ids and gid not in bot_ids):
            continue
        options.append({"id": gid, "name": str(guild.get("name") or gid)})
    return sorted(options, key=lambda option: option["name"].lower())


def _normalise_archive_page(page: int, page_size: int) -> tuple[int, int]:
    clean_page = max(1, int(page))
    clean_size = max(1, min(100, int(page_size)))
    return clean_page, clean_size


def _parse_optional_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    return None


async def _archive_access_context(
    request: Request, guild_id: str, *, refresh: bool = False
) -> dict[str, Any]:
    """Authorise the visitor for ``guild_id``'s archive the way the Discord bot does."""

    if not request.session.get("discord_token"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    if not _clean_discord_id(guild_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid guild id")
    user = request.session.get("user")
    if not isinstance(user, Mapping):
        user, _guilds = await _load_user_context(request)
    user_id = _clean_discord_id(user.get("id")) if isinstance(user, Mapping) else None
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")

    standing = await _archive_standing(request, str(guild_id), user_id, refresh=refresh)
    locked = await run_blocking(archive_lock.is_locked, int(guild_id))
    if locked and not standing.is_high_command:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            "Archive lockdown in effect. Only High Command can open the archive.",
        )
    return {
        "user": user,
        "user_id": user_id,
        "is_owner": standing.is_owner,
        "is_admin": standing.is_admin,
        "is_high_command": standing.is_high_command,
        "member_roles": standing.roles,
        "roles_verified": standing.roles_verified,
        "locked": locked,
    }


def _descriptor_name(descriptor: Mapping[str, Any]) -> str:
    raw = descriptor.get("name") or descriptor.get("item") or ""
    return str(raw).strip()


def _descriptor_access_payload(
    descriptor: Mapping[str, Any],
    *,
    resolver: "archive_index.AccessResolver",
    member_roles: set[int],
    is_owner: bool,
    is_admin: bool,
) -> dict[str, Any]:
    category = str(descriptor.get("category") or "").strip()
    item_name = _descriptor_name(descriptor)
    required_roles = resolver.required_roles(category, item_name)
    role_match = resolver.allows(member_roles, required_roles)
    allowed = is_owner or is_admin or not required_roles or role_match
    level = resolver.level_for(required_roles)
    return {
        "required_roles": sorted(required_roles),
        "allowed": allowed,
        "clearance_level": level,
        "clearance_label": resolver.level_label(level),
    }


def _prepare_archive_item_payload(
    descriptor: Mapping[str, Any],
    *,
    access: Mapping[str, Any],
    category_label: str | None = None,
) -> dict[str, Any]:
    updated = descriptor.get("updated_at")
    if isinstance(updated, datetime):
        updated = updated.isoformat()
    category = str(descriptor.get("category") or "").strip()
    return {
        "key": str(descriptor.get("key") or "").strip(),
        "root": str(descriptor.get("root") or "").strip(),
        "category": category,
        "category_label": category_label or category,
        "name": _descriptor_name(descriptor),
        "ext": str(descriptor.get("ext") or "").strip(),
        "archived": bool(descriptor.get("archived")),
        "size": int(descriptor.get("size") or 0),
        "updated_at": str(updated or ""),
        "required_roles": list(access.get("required_roles") or []),
        "allowed": bool(access.get("allowed")),
        "clearance_level": access.get("clearance_level"),
        "clearance_label": str(access.get("clearance_label") or ""),
    }


def _archive_source_names(guild_id: int | None, settings: Any) -> tuple[str, dict[str, str], dict[str, Mapping[str, object]], str | None]:
    """Return the labels used to name archive sources without walking storage.

    Gives ``(base_label, link_names, summaries_by_root, local_root)``.
    """

    archive_cfg = settings.get("archive") if isinstance(settings, Mapping) else {}
    archive_cfg = archive_cfg if isinstance(archive_cfg, Mapping) else {}
    link_names: dict[str, str] = {}
    for entry in _normalise_link_entries(archive_cfg.get("links")):
        if not isinstance(entry, Mapping):
            continue
        root_value = str(entry.get("root_prefix") or "").strip("/")
        label = (entry.get("name") or entry.get("code") or "Linked archive")
        if root_value and isinstance(label, str):
            link_names[root_value] = label.strip()

    base_label = _archive_display_name(settings) or (BRAND and f"{BRAND} Archive") or "Primary Archive"

    summaries: dict[str, Mapping[str, object]] = {}
    try:
        summary = get_instance_summary()
    except Exception:
        logger.exception("Failed to load archive instance summary")
        summary = {}
    for entry in summary.get("archives", []) if isinstance(summary, Mapping) else []:
        if not isinstance(entry, Mapping):
            continue
        entry_guild = str(entry.get("guild_id") or "") or None
        if entry_guild != (str(guild_id) if guild_id is not None else None):
            continue
        summaries[str(entry.get("root_prefix") or "").strip("/")] = entry

    local_root = normalise_root_prefix(settings.get("ROOT_PREFIX")) if isinstance(settings, Mapping) else None
    return base_label, link_names, summaries, local_root


def _archive_sources(
    guild_id: int, index: "archive_index.ArchiveIndex", items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Name each archive root and count the files in ``items`` (what the viewer can see)."""
    settings = get_server_config(guild_id) or {}
    base_label, link_names, summaries, local_root = _archive_source_names(guild_id, settings)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["root"]] = counts.get(item["root"], 0) + 1
    sources: list[dict[str, Any]] = []
    for root in index.roots:
        cleaned = str(root or "").strip("/")
        summary_name = summaries.get(cleaned, {}).get("name") if cleaned in summaries else None
        name = summary_name.strip() if isinstance(summary_name, str) and summary_name.strip() else None
        sources.append(
            {
                "root_prefix": cleaned,
                "name": name or link_names.get(cleaned) or base_label,
                "origin": "Local" if cleaned == (local_root or "") else "Linked",
                "file_count": counts.get(root, 0),
            }
        )
    return sources


async def _archive_scope(
    request: Request, guild_id: str, *, refresh: bool = False
) -> tuple[int, "archive_index.ArchiveIndex", "archive_index.AccessResolver", dict[str, Any]]:
    """Authorise an archive API call and load the index, ACL and viewer roles."""

    # Authorise before touching storage so outsiders cannot trigger index builds.
    access_ctx = await _archive_access_context(request, guild_id, refresh=refresh)
    gid_int = int(str(guild_id))
    index, resolver = await asyncio.gather(
        run_blocking(archive_index.get_index, gid_int, force=refresh),
        run_blocking(archive_index.build_access_resolver, gid_int),
    )
    return gid_int, index, resolver, access_ctx


def _archive_item_payloads(
    index: "archive_index.ArchiveIndex",
    resolver: "archive_index.AccessResolver",
    access_ctx: Mapping[str, Any],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for entry in index.entries:
        # Discord only shows archived files in High Command's console.
        if entry["archived"] and not access_ctx.get("is_high_command"):
            continue
        access = _descriptor_access_payload(
            entry,
            resolver=resolver,
            member_roles=access_ctx["member_roles"],
            is_owner=access_ctx["is_owner"],
            is_admin=access_ctx["is_admin"],
        )
        payloads.append(
            _prepare_archive_item_payload(
                entry, access=access, category_label=index.category_labels.get(entry["category"])
            )
        )
    return payloads


def _archive_category_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item["category"]
        bucket = grouped.get(name.lower())
        if bucket is None:
            bucket = grouped[name.lower()] = {
                "name": name,
                "label": item.get("category_label") or name,
                "total": 0,
                "allowed": 0,
                "active": 0,
                "archived": 0,
            }
        bucket["total"] += 1
        bucket["allowed"] += 1 if item["allowed"] else 0
        bucket["archived" if item["archived"] else "active"] += 1
    return sorted(grouped.values(), key=lambda entry: str(entry["label"]).lower())


def _archive_role_label(access_ctx: Mapping[str, Any]) -> str:
    if access_ctx.get("is_owner"):
        return "Owner"
    if access_ctx.get("is_admin"):
        return "Administrator"
    if access_ctx.get("is_high_command"):
        return "High Command"
    return "Member"


def _archive_profile(
    access_ctx: Mapping[str, Any], resolver: "archive_index.AccessResolver | None" = None
) -> dict[str, Any]:
    profile = access_ctx.get("user") if isinstance(access_ctx.get("user"), Mapping) else {}
    level = resolver.member_level(set(access_ctx.get("member_roles") or ())) if resolver else None
    return {
        "id": str(profile.get("id") or "").strip(),
        "display_name": str(profile.get("global_name") or "").strip()
        or str(profile.get("username") or "").strip()
        or "Operator",
        "username": str(profile.get("username") or "").strip(),
        "guild_role": _archive_role_label(access_ctx),
        "clearance_level": level,
        "clearance_label": resolver.level_label(level) if resolver else "",
        "roles_verified": bool(access_ctx.get("roles_verified", True)),
    }


def _archive_stats(items: list[dict[str, Any]], sources: list[dict[str, Any]] | None = None) -> dict[str, int]:
    allowed = sum(1 for item in items if item["allowed"])
    return {
        "total_files": len(items),
        "allowed_files": allowed,
        "restricted_files": len(items) - allowed,
        "archived_files": sum(1 for item in items if item["archived"]),
        "category_count": len({item["category"].lower() for item in items}),
        "source_count": len(sources) if sources is not None else len({item["root"] for item in items}),
    }


def _compressed_json_response(request: Request, payload: Any, *, headers: Mapping[str, str] | None = None) -> Response:
    """JSON response gzipped for clients that accept it.

    Used for the archive index, which lists every file and can run to hundreds
    of kilobytes. (A global GZip middleware would also re-encode MP3 range
    responses, so compression is applied per endpoint.)
    """

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response_headers = {**(headers or {}), "Vary": "Accept-Encoding"}
    if len(body) > 1024 and "gzip" in request.headers.get("accept-encoding", "").lower():
        body = gzip.compress(body, compresslevel=5)
        response_headers["Content-Encoding"] = "gzip"
    return Response(content=body, media_type="application/json", headers=response_headers)


@app.get("/api/spectre/archive/index", include_in_schema=False)
@app.get("/api/wasp/archive/index", include_in_schema=False)
async def spectre_archive_index(request: Request, guild_id: str, refresh: bool = False):
    """Everything the archive page needs in one call: files, categories, stats and access."""

    gid_int, index, resolver, access_ctx = await _archive_scope(request, guild_id, refresh=refresh)
    items = _archive_item_payloads(index, resolver, access_ctx)
    sources = await run_blocking(_archive_sources, gid_int, index, items)
    levels = sorted(
        {item["clearance_level"] for item in items if item.get("clearance_level")}
    )
    return _compressed_json_response(
        request,
        {
            "guild_id": str(guild_id),
            "generated_at": datetime.fromtimestamp(index.built_at, timezone.utc).isoformat(),
            "profile": _archive_profile(access_ctx, resolver),
            "locked": bool(access_ctx.get("locked")),
            "stats": _archive_stats(items, sources),
            "sources": sources,
            "categories": _archive_category_summary(items),
            "clearance_levels": [
                {"level": level, "label": resolver.level_label(level)} for level in levels
            ],
            "items": items,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/spectre/archive", include_in_schema=False)
@app.get("/api/wasp/archive", include_in_schema=False)
async def spectre_archive_data(request: Request, guild_id: str):
    gid_int, index, resolver, access_ctx = await _archive_scope(request, guild_id)
    items = _archive_item_payloads(index, resolver, access_ctx)
    sources = await run_blocking(_archive_sources, gid_int, index, items)

    guild_payload = await run_blocking(read_json, guild_key(guild_id))
    settings = guild_payload.get("settings") if isinstance(guild_payload, Mapping) else None
    if not isinstance(settings, Mapping) and isinstance(guild_payload, Mapping):
        settings = guild_payload
    clearance_cfg = settings.get("clearance") if isinstance(settings, Mapping) else {}
    clearance_cfg = clearance_cfg if isinstance(clearance_cfg, dict) else {}
    clearance_levels = clearance_cfg.get("levels") if isinstance(clearance_cfg.get("levels"), dict) else {}

    profile = access_ctx.get("user") if isinstance(access_ctx.get("user"), Mapping) else {}
    profile_payload = {
        **_archive_profile(access_ctx),
        "email": str(profile.get("email") or "").strip(),
        "verified": bool(profile.get("verified")),
        "mfa_enabled": bool(profile.get("mfa_enabled")),
        "guild_role": "Administrator" if access_ctx["is_admin"] else "Member",
    }
    stats = _archive_stats(items, sources)
    return JSONResponse(
        {
            "overview": {
                "sources": sources,
                "total_files": stats["total_files"],
                "total_categories": stats["category_count"],
                "source_count": stats["source_count"],
            },
            "clearance": {
                "enabled": bool(clearance_cfg.get("enabled", True)),
                "levels": clearance_levels,
            },
            "profile": profile_payload,
            "stats": {
                "total_files": stats["total_files"],
                "allowed_files": stats["allowed_files"],
                "restricted_files": stats["restricted_files"],
            },
        }
    )


@app.get("/api/spectre/archive/categories", include_in_schema=False)
@app.get("/api/wasp/archive/categories", include_in_schema=False)
async def spectre_archive_categories(request: Request, guild_id: str):
    _gid, index, resolver, access_ctx = await _archive_scope(request, guild_id)
    grouped: dict[tuple[str, str, bool], dict[str, Any]] = {}

    for item in _archive_item_payloads(index, resolver, access_ctx):
        key = (item["root"], item["category"], item["archived"])
        bucket = grouped.get(key)
        if bucket is None:
            bucket = grouped[key] = {
                "root": key[0],
                "category": key[1],
                "label": item["category_label"],
                "archived": key[2],
                "total": 0,
                "allowed": 0,
            }
        bucket["total"] += 1
        if item["allowed"]:
            bucket["allowed"] += 1

    categories = sorted(
        grouped.values(),
        key=lambda entry: (
            str(entry.get("root") or "").lower(),
            bool(entry.get("archived")),
            str(entry.get("category") or "").lower(),
        ),
    )
    return JSONResponse({"guild_id": str(guild_id), "categories": categories})


@app.get("/api/spectre/archive/browse", include_in_schema=False)
@app.get("/api/wasp/archive/browse", include_in_schema=False)
async def spectre_archive_browse(
    request: Request,
    guild_id: str,
    category: str | None = None,
    archived: str | None = None,
    source: str | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 40,
    include_restricted: bool = False,
):
    page, page_size = _normalise_archive_page(page, page_size)
    archived_filter = _parse_optional_bool(archived)
    category_filter = str(category or "").strip().lower()
    source_filter = str(source or "").strip().strip("/").lower()
    search_filter = str(query or "").strip().lower()

    _gid, index, resolver, access_ctx = await _archive_scope(request, guild_id)
    items: list[dict[str, Any]] = []
    for payload in _archive_item_payloads(index, resolver, access_ctx):
        if source_filter and payload["root"].lower() != source_filter:
            continue
        if category_filter and payload["category"].lower() != category_filter:
            continue
        if archived_filter is not None and payload["archived"] != archived_filter:
            continue
        if search_filter:
            haystack = " ".join(
                [
                    payload["name"].lower(),
                    payload["category"].lower(),
                    payload["key"].lower(),
                    payload["root"].lower(),
                ]
            )
            if search_filter not in haystack:
                continue
        if not include_restricted and not payload["allowed"]:
            continue
        items.append(payload)

    items.sort(
        key=lambda value: (
            bool(value.get("archived")),
            str(value.get("category") or "").lower(),
            str(value.get("name") or "").lower(),
        )
    )

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "filters": {
                "category": category or "",
                "archived": archived_filter,
                "source": source or "",
                "query": query or "",
                "include_restricted": bool(include_restricted),
            },
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, (total + page_size - 1) // page_size) if total else 1,
            },
            "items": items[start:end],
        }
    )


@app.get("/api/spectre/archive/dossier", include_in_schema=False)
@app.get("/api/wasp/archive/dossier", include_in_schema=False)
async def spectre_archive_dossier(request: Request, guild_id: str, key: str):
    requested_key = str(key or "").strip().lstrip("/")
    if not requested_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing dossier key")

    access_ctx = await _archive_access_context(request, guild_id)
    gid_int = int(str(guild_id))
    # Only keys found in this guild's own index can be opened, which keeps
    # requests inside the guild's archive roots.
    descriptor, resolver = await asyncio.gather(
        run_blocking(archive_index.find_entry, gid_int, requested_key),
        run_blocking(archive_index.build_access_resolver, gid_int),
    )
    if not isinstance(descriptor, Mapping) or (
        descriptor.get("archived") and not access_ctx.get("is_high_command")
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dossier not found")

    access = _descriptor_access_payload(
        descriptor,
        resolver=resolver,
        member_roles=access_ctx["member_roles"],
        is_owner=access_ctx["is_owner"],
        is_admin=access_ctx["is_admin"],
    )
    if not access["allowed"]:
        user_id = access_ctx.get("user_id")
        category = str(descriptor.get("category") or "").strip()
        item_name = _descriptor_name(descriptor)
        has_temp = False
        if user_id:
            try:
                has_temp = await run_blocking(
                    check_temp_clearance, int(user_id), category, item_name, guild_id=gid_int
                )
            except (TypeError, ValueError):
                has_temp = False
        if not has_temp:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient clearance")

    try:
        content, ext = await run_blocking(read_dossier_body, requested_key, gid_int)
    except FileNotFoundError:
        archive_index.invalidate(gid_int)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dossier not found")
    safe_max = 200_000
    truncated = False
    if len(content) > safe_max:
        content = content[:safe_max]
        truncated = True

    index = await run_blocking(archive_index.get_index, gid_int)
    payload = _prepare_archive_item_payload(
        descriptor, access=access, category_label=index.category_labels.get(str(descriptor.get("category")))
    )
    payload["ext"] = ext or payload["ext"]

    structured_data: dict[str, Any] | None = None
    # Formatted uploads are JSON objects, but older ones were stored as .txt,
    # so parse any body that is a JSON object regardless of extension.
    if not truncated and content.lstrip().startswith("{"):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                structured_data = parsed
        except (TypeError, ValueError):
            structured_data = None
    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "dossier": payload,
            "content": content,
            "content_raw": content,
            "data": structured_data,
            "truncated": truncated,
        }
    )


async def _render_wasp_map_page(request: Request):
    user, _guilds = await _load_user_context(request)

    if templates is None:
        return HTMLResponse(
            "<html><body style=\"margin:0;background:#05080a;\"></body></html>"
        )

    display_name = ""
    if user:
        display_name = (
            str(user.get("global_name") or "").strip()
            or str(user.get("username") or "").strip()
        )

    can_edit_wasp_map = _can_edit_wasp_map(request)
    context = {
        "request": request,
        "display_name": display_name,
        "can_edit_wasp_map": can_edit_wasp_map,
        "can_view_wasp_map": can_edit_wasp_map or _can_read_wasp_map(request),
        "login_url": f"/login?next={quote(request.url.path)}",
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
        "wasp_asset_version": _wasp_map_client_asset_version(),
    }
    return templates.TemplateResponse(request, "wasp_map.html", context)


@app.get("/wasp-map", include_in_schema=False)
async def wasp_map_page(request: Request):
    return await _render_wasp_map_page(request)


def _wasp_map_session_user(request: Request) -> Mapping[str, Any] | None:
    try:
        session = request.session
    except (RuntimeError, AssertionError):
        return None
    user = session.get("user") if isinstance(session, dict) else None
    return user if isinstance(user, Mapping) and user else None


def _can_edit_wasp_map(request: Request) -> bool:
    try:
        return _session_user_is_owner(request) or _session_user_is_admin(request)
    except Exception:
        logger.exception("Failed to resolve WASP map edit permissions")
        return False


def _public_wasp_map_reads_enabled() -> bool:
    value = os.getenv("PUBLIC_WASP_MAP_READS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _can_read_wasp_map(request: Request) -> bool:
    """Any signed-in operator may watch the war; PUBLIC_WASP_MAP_READS opens it to everyone."""
    return _public_wasp_map_reads_enabled() or _wasp_map_session_user(request) is not None


def _require_wasp_map_reader(request: Request) -> None:
    if _can_read_wasp_map(request) or _can_edit_wasp_map(request):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to view the WASP war map.",
    )


def _require_wasp_map_editor(request: Request) -> None:
    if _can_edit_wasp_map(request):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="WASP map edits require owner or admin access.",
    )


def _wasp_state_response(state: dict[str, Any], etag: str | None) -> JSONResponse:
    response = JSONResponse(state)
    if etag:
        response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/wasp-map/state")
async def wasp_map_state_index(request: Request):
    _require_wasp_map_reader(request)
    state, etag = await run_blocking(load_wasp_map_state, with_etag=True)
    incoming_etag = (request.headers.get("if-none-match") or "").strip().strip('"')

    if etag and incoming_etag and incoming_etag == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": f'"{etag}"', "Cache-Control": "no-cache"},
        )
    return _wasp_state_response(state, etag)


@app.post("/api/wasp-map/ops")
async def wasp_map_apply_ops(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    """Apply admin edits (upsert/delete/meta/clear/replace) to the shared war map."""
    _require_wasp_map_editor(request)
    actor = _discord_display_name(_wasp_map_session_user(request))
    try:
        state, etag = await run_blocking(update_wasp_map_state, payload.get("ops"), actor=actor)
    except WaspMapOpError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WaspMapConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _wasp_state_response(state, etag)


@app.post("/api/admin/heartbeat")
async def admin_heartbeat(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    claims = await _authenticate_request(request)
    _require_staff_claims(claims)
    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    body_id = _clean_discord_id(payload.get("id"))
    if not body_id:
        return JSONResponse({"error": "Missing admin ID"}, status_code=status.HTTP_400_BAD_REQUEST)

    session_user_id = _clean_discord_id(user_id)
    if body_id != session_user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Heartbeat ID mismatch")

    resolved_name = (
        str(payload.get("name") or claims.get("name") or "").strip()
        or "Unknown"
    )
    ip_address = _client_ip_from_request(request)

    came_online = _record_admin_heartbeat(
        body_id,
        name=resolved_name,
        role=str(payload.get("role") or "System Overseer").strip() or None,
        clearance=str(payload.get("clearance") or "Omega-9").strip() or None,
        ip=ip_address,
    )
    # One feed entry per arrival; a line every 30 seconds would push real
    # incidents out of the 200-entry feed.
    if came_online:
        _log_activity("online", resolved_name, ip_address)
    return {"success": True}


def _session_portal_admin(request: Request) -> dict[str, Any] | None:
    """The signed-in Discord user when they are a portal admin, else ``None``."""

    try:
        session = request.session
    except (AssertionError, RuntimeError):
        return None
    user = session.get("user") if isinstance(session, dict) else None
    if not isinstance(user, dict):
        return None
    user_id = _clean_discord_id(user.get("id"))
    if not user_id or not _user_is_portal_admin(user_id):
        return None
    return user


def _mark_admin_present(user: Mapping[str, Any], ip: str) -> tuple[bool, str]:
    user_id = str(_clean_discord_id(user.get("id")))
    name = _user_display_name(dict(user)) or "Admin"
    came_online = _record_admin_heartbeat(
        user_id,
        name=name,
        role="Director" if is_owner(user_id) else None,
        ip=ip,
    )
    return came_online, name


async def _touch_admin_presence(request: Request, *, force: bool = False) -> bool:
    """Mark the signed-in admin as online, wherever on the site they are.

    Runs for every request; returns ``True`` when the request came from an admin.
    """

    user = _session_portal_admin(request)
    if user is None:
        return False
    user_id = str(_clean_discord_id(user.get("id")))
    now = time.monotonic()
    last = _ADMIN_PRESENCE_LAST_TOUCH.get(user_id)
    if not force and last is not None and now - last < _ADMIN_PRESENCE_TOUCH_SECONDS:
        return True
    _ADMIN_PRESENCE_LAST_TOUCH[user_id] = now
    ip = _client_ip_from_request(request)
    came_online, name = await run_blocking(_mark_admin_present, user, ip)
    if came_online:
        _log_activity("online", name, ip, background=True)
    return True


@app.post("/api/presence/ping")
async def admin_presence_ping(request: Request):
    """Keep-alive from static/js/admin_presence.js on any page an admin has open."""

    if not await _touch_admin_presence(request, force=True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Presence is tracked for admins only.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/admins/presence")
async def admin_presence_public(request: Request):
    """Who on the admin team is online, for the public Contact page.

    Deliberately minimal: Discord ID, Online/Offline and a coarse "last active".
    No IPs, names or clearances.
    """

    rows = [
        {"id": entry["id"], "status": entry["status"], "lastActive": entry["lastActive"]}
        for entry in _list_admin_presence(include_ip=False)
        if _user_is_portal_admin(entry.get("id"))
    ]
    return JSONResponse(rows, headers={"Cache-Control": "no-store"})


@app.get("/api/admins")
async def admin_presence_index(request: Request):
    # Any signed-in visitor may see who is online (no IPs); only staff may post heartbeats.
    await _authenticate_request(request)
    return JSONResponse(_list_admin_presence(include_ip=False))


@app.get("/api/director/admins")
async def director_admin_presence_index(request: Request):
    claims = await _authenticate_request(request)
    _require_director_claims(claims)
    return JSONResponse(_list_admin_presence(include_ip=True))


@app.get("/api/activity")
async def admin_activity_index(request: Request):
    claims = await _authenticate_request(request)
    _require_director_claims(claims)
    return JSONResponse(_activity_snapshot())


@app.get("/api/activity/stream")
async def admin_activity_stream(request: Request):
    claims = await _authenticate_request(request)
    _require_director_claims(claims)
    queue: asyncio.Queue[list[dict[str, Any]]] = asyncio.Queue(maxsize=1)
    with _ACTIVITY_SUBSCRIBERS_LOCK:
        _ACTIVITY_SUBSCRIBERS.add(queue)

    async def stream_events():
        try:
            yield f"data: {json.dumps(_activity_snapshot())}\n\n"
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            with _ACTIVITY_SUBSCRIBERS_LOCK:
                _ACTIVITY_SUBSCRIBERS.discard(queue)

    return StreamingResponse(stream_events(), media_type="text/event-stream")


@app.get("/api/auth/token")
async def issue_api_token(request: Request):
    user = _session_user_for_api_token(request)
    if not isinstance(user, dict):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    token = _mint_session_jwt(user, request=request)
    return {"token": token, "expiresIn": int(_JWT_TTL.total_seconds())}


@app.websocket("/ws/director/activity")
async def director_activity_socket(websocket: WebSocket):
    token = str(websocket.query_params.get("token") or "").strip()
    if not token:
        await websocket.close(code=1008, reason="No token")
        return

    try:
        claims = _decode_jwt_token(token)
        _require_director_claims(claims)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    await websocket.accept()
    with _ACTIVITY_SOCKET_SUBSCRIBERS_LOCK:
        _ACTIVITY_SOCKET_SUBSCRIBERS.add(websocket)

    await websocket.send_json({"event": "activity_update", "payload": _activity_snapshot()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        with _ACTIVITY_SOCKET_SUBSCRIBERS_LOCK:
            _ACTIVITY_SOCKET_SUBSCRIBERS.discard(websocket)


@app.get("/admin-team", include_in_schema=False)
async def admin_team(request: Request):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    team_settings = load_admin_team_settings()
    current_user_id = str(user.get("id")) if user and user.get("id") else None
    is_admin_viewer = can_manage_portal(current_user_id, owner_settings.managers)
    bios = load_admin_bios()
    roster_ids = team_settings.members or _default_admin_team_member_ids(owner_settings)
    roster = await _build_admin_roster_entries(
        roster_ids,
        bios,
        current_user_id,
        team_settings.ranks,
        team_settings.clearances,
    )
    panel_flash = _render_panel_flash_block(_pop_panel_flash(request))

    if templates is None:
        return JSONResponse(
            {
                "brand": BRAND,
                "accent": ACCENT,
                "roster": roster,
                "is_admin_viewer": is_admin_viewer,
            }
        )

    # Rendered server-side so the badges are right before any script runs; the
    # page then polls /api/admins/presence to keep them current.
    presence = {str(entry.get("id")): entry for entry in _list_admin_presence(include_ip=False)}
    for entry in roster:
        admin_id = str(entry.get("id") or "")
        seen = presence.get(admin_id)
        viewing_now = bool(is_admin_viewer and admin_id == current_user_id)
        entry["online"] = viewing_now or bool(seen and seen.get("status") == "Online")
        entry["last_active"] = "Recently" if viewing_now else (seen or {}).get("lastActive") or ""

    return templates.TemplateResponse(
        request,
        "admin_team.html",
        _inject_wallpaper(
            {
                "request": request,
                "brand": BRAND,
                "accent": ACCENT,
                "roster": roster,
                "panel_flash": panel_flash,
                "is_admin_viewer": is_admin_viewer,
                "viewer_name": _discord_display_name(user),
                "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
            },
            "admin-team",
        ),
    )


@app.get("/admin-team/messages", include_in_schema=False)
async def admin_team_messages_page(request: Request):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    current_user_id = str(user.get("id")) if user and user.get("id") else None
    if not can_manage_portal(current_user_id, owner_settings.managers):
        return RedirectResponse(url="/admin-team", status_code=status.HTTP_303_SEE_OTHER)

    if templates is None:
        return JSONResponse({"brand": BRAND, "accent": ACCENT})

    return templates.TemplateResponse(
        request,
        "admin_team_messages.html",
        _inject_wallpaper(
            {
                "request": request,
                "brand": BRAND,
                "accent": ACCENT,
                "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
            },
            "admin-team",
        ),
    )


@app.get("/admin-team/message/{target_admin_id}", include_in_schema=False)
async def admin_team_message_page(request: Request, target_admin_id: str):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    team_settings = load_admin_team_settings()
    bios = load_admin_bios()
    current_user_id = str(user.get("id")) if user and user.get("id") else None
    roster_ids = team_settings.members or _default_admin_team_member_ids(owner_settings)
    roster = await _build_admin_roster_entries(
        roster_ids,
        bios,
        current_user_id,
        team_settings.ranks,
        team_settings.clearances,
    )

    target_id = str(target_admin_id or "").strip()
    target_entry = next((entry for entry in roster if str(entry.get("id") or "") == target_id), None)
    if not target_entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Admin profile not found.")

    support_chat_mode = "discord" if _clean_discord_id(current_user_id) else "guest"
    has_guest_session = _support_chat_guest(request) is not None

    if templates is None:
        return JSONResponse(
            {
                "brand": BRAND,
                "accent": ACCENT,
                "target_admin_id": target_id,
                "target_admin_name": target_entry.get("name") or "Admin",
                "support_chat_mode": support_chat_mode,
                "has_guest_session": has_guest_session,
            }
        )

    return templates.TemplateResponse(
        request,
        "admin_team_message.html",
        _inject_wallpaper(
            {
                "request": request,
                "brand": BRAND,
                "accent": ACCENT,
                "target_admin_id": target_id,
                "target_admin_name": target_entry.get("name") or "Admin",
                "support_chat_mode": support_chat_mode,
                "has_guest_session": has_guest_session,
                "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
            },
            "admin-team",
        ),
    )


@app.post("/admin-team/bio", include_in_schema=False)
async def update_admin_bio(request: Request):
    user, _guilds = await _load_user_context(request)
    if not user:
        return RedirectResponse(url="/login")

    owner_settings, _etag = load_owner_settings()
    user_id = str(user.get("id")) if user and user.get("id") else None
    if not can_manage_portal(user_id, owner_settings.managers):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not authorised to edit bios.")

    form = await request.form()
    bio_text = form.get("bio")
    bios = save_admin_bio(user_id, bio_text)
    updated_entry = bios.get(str(user_id))
    if updated_entry:
        _push_panel_flash(request, "success", "About me saved.")
    else:
        _push_panel_flash(request, "success", "Bio cleared. You can add one any time.")
    return RedirectResponse(url="/admin-team", status_code=status.HTTP_303_SEE_OTHER)

# ---------------------------------------------------------------------------
# Support chat ("Message an admin"): one thread per (member, admin) pair.
# Members authenticate with the API token (Discord) or a guest session;
# portal admins read and answer every thread from the shared inbox.
# ---------------------------------------------------------------------------

_SUPPORT_GUEST_SESSION_KEY = "support_chat_guest"
_SUPPORT_GUEST_NAME_MAX = 60
_SUPPORT_STREAM_KEEPALIVE_SECONDS = 25.0
_SUPPORT_STREAM_MAX_SUBSCRIBERS = 200
_SUPPORT_STREAM_LOCK = threading.Lock()
# queue -> thread key it may see, or None for staff (every thread)
_SUPPORT_STREAM_SUBSCRIBERS: dict[asyncio.Queue[dict[str, Any]], str | None] = {}
_SUPPORT_MESSAGE_LIMITER = _SlidingWindowRateLimiter(limit=20, window_seconds=60.0)
_SUPPORT_GUEST_START_LIMITER = _SlidingWindowRateLimiter(limit=5, window_seconds=3600.0)


@dataclass(frozen=True)
class _SupportChatCaller:
    member_id: str
    label: str
    is_staff: bool
    is_guest: bool


def _support_chat_guest(request: Request) -> dict[str, str] | None:
    guest = request.session.get(_SUPPORT_GUEST_SESSION_KEY)
    if not isinstance(guest, dict):
        return None
    guest_id = support_chat.normalise_member_id(guest.get("id"))
    if not guest_id or not support_chat.GUEST_MEMBER_ID_RE.fullmatch(guest_id):
        return None
    return {"id": guest_id, "name": str(guest.get("name") or "Guest")}


def _support_chat_caller(request: Request, *, allow_query_token: bool = False) -> _SupportChatCaller:
    token = None
    if request.headers.get("authorization"):
        token = _extract_bearer_token(request)
    elif allow_query_token:
        # EventSource cannot send headers, so the stream takes the token as a query parameter.
        token = str(request.query_params.get("token") or "").strip() or None

    if token:
        claims = _decode_jwt_token(token)
        member_id = _clean_discord_id(claims.get("sub"))
        if not member_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        owner_settings, _etag = load_owner_settings()
        is_staff = _user_role_from_claims(claims) in _JWT_STAFF_ROLES and can_manage_portal(
            member_id, owner_settings.managers
        )
        label = str(claims.get("name") or "").strip() or ("Staff" if is_staff else "Member")
        return _SupportChatCaller(member_id=member_id, label=label, is_staff=is_staff, is_guest=False)

    guest = _support_chat_guest(request)
    if guest:
        return _SupportChatCaller(member_id=guest["id"], label=guest["name"], is_staff=False, is_guest=True)

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="Sign in with Discord or start a guest conversation first.",
    )


def _require_support_staff(caller: _SupportChatCaller) -> None:
    if not caller.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Support inbox is restricted to admins.")


def _support_chat_target_admin(raw_admin_id: object) -> str:
    """Return ``raw_admin_id`` when it names someone on the admin team roster."""

    admin_id = _clean_discord_id(str(raw_admin_id) if raw_admin_id is not None else None)
    if admin_id:
        owner_settings, _etag = load_owner_settings()
        roster_ids = load_admin_team_settings().members or _default_admin_team_member_ids(owner_settings)
        if admin_id in {str(member) for member in roster_ids}:
            return admin_id
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Admin not found.")


def _support_chat_thread_ids(member_raw: object, admin_raw: object) -> tuple[str, str]:
    member_id = support_chat.normalise_member_id(str(member_raw) if member_raw is not None else None)
    admin_id = _clean_discord_id(str(admin_raw) if admin_raw is not None else None)
    if not member_id or not admin_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid thread.")
    return member_id, admin_id


def _publish_support_event(thread_key: str, event: dict[str, Any]) -> None:
    with _SUPPORT_STREAM_LOCK:
        subscribers = list(_SUPPORT_STREAM_SUBSCRIBERS.items())
    for queue, scope in subscribers:
        if scope is not None and scope != thread_key:
            continue
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            continue


@app.post("/api/support-chat/guest/start")
async def support_chat_guest_start(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    name = " ".join(str(payload.get("name") or "").split())[:_SUPPORT_GUEST_NAME_MAX].strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Please enter a name.")

    existing = _support_chat_guest(request)
    if existing:
        guest_id = existing["id"]
    else:
        if _SUPPORT_GUEST_START_LIMITER.hit(_client_ip_from_request(request)):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many new conversations from this network. Try again later.",
            )
        guest_id = f"guest{secrets.token_hex(16)}"
    request.session[_SUPPORT_GUEST_SESSION_KEY] = {"id": guest_id, "name": name}
    return {"guestId": guest_id, "name": name}


@app.get("/api/support-chat/guest/me")
async def support_chat_guest_me(request: Request):
    return {"guest": _support_chat_guest(request)}


@app.get("/api/support-chat/with/{target_admin_id}")
async def support_chat_with_admin(request: Request, target_admin_id: str):
    caller = _support_chat_caller(request)
    admin_id = _support_chat_target_admin(target_admin_id)
    thread = await run_blocking(support_chat.get_thread_for_pair, caller.member_id, admin_id)
    if thread is None:
        thread = {
            "threadKey": f"{caller.member_id}:{admin_id}",
            "threadUserId": caller.member_id,
            "targetAdminId": admin_id,
            "userLabel": caller.label,
            "messages": [],
            "isGuestThread": caller.is_guest,
        }
    return {"thread": thread}


@app.post("/api/support-chat/messages")
async def support_chat_post_message(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    caller = _support_chat_caller(request)
    body = str(payload.get("body") or "")
    if not body.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Message body is required.")

    if payload.get("threadUserId"):
        # Staff reply into an existing member thread from the inbox.
        _require_support_staff(caller)
        member_id, admin_id = _support_chat_thread_ids(payload.get("threadUserId"), payload.get("targetAdminId"))
        existing = await run_blocking(support_chat.get_thread_for_pair, member_id, admin_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
        is_staff = True
    else:
        member_id = caller.member_id
        admin_id = _support_chat_target_admin(payload.get("targetAdminId"))
        is_staff = False

    over_budget = _SUPPORT_MESSAGE_LIMITER.hit(f"member:{caller.member_id}")
    if caller.is_guest and not over_budget:
        over_budget = _SUPPORT_MESSAGE_LIMITER.hit(f"ip:{_client_ip_from_request(request)}")
    if over_budget:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You're sending messages too quickly. Wait a moment and try again.",
        )

    try:
        entry, thread_key = await run_blocking(
            support_chat.append_message,
            member_id=member_id,
            target_admin_id=admin_id,
            sender_id=caller.member_id,
            sender_label=caller.label,
            is_staff=is_staff,
            body=body,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _publish_support_event(
        thread_key,
        {"type": "message", "message": entry, "threadUserId": member_id, "targetAdminId": admin_id},
    )
    return {"message": entry}


@app.get("/api/support-chat/inbox")
async def support_chat_inbox(request: Request):
    caller = _support_chat_caller(request)
    _require_support_staff(caller)
    threads = await run_blocking(support_chat.list_thread_summaries)
    return {"threads": threads}


@app.get("/api/support-chat/thread/{member_id}/{admin_id}")
async def support_chat_thread(request: Request, member_id: str, admin_id: str):
    caller = _support_chat_caller(request)
    _require_support_staff(caller)
    clean_member, clean_admin = _support_chat_thread_ids(member_id, admin_id)
    thread = await run_blocking(support_chat.get_thread_for_pair, clean_member, clean_admin)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return {"thread": thread}


@app.delete("/api/support-chat/thread/{member_id}/{admin_id}")
async def support_chat_delete_thread(request: Request, member_id: str, admin_id: str):
    caller = _support_chat_caller(request)
    _require_support_staff(caller)
    clean_member, clean_admin = _support_chat_thread_ids(member_id, admin_id)
    deleted = await run_blocking(support_chat.delete_thread_by_pair, clean_member, clean_admin)
    if deleted:
        thread_key = f"{clean_member}:{clean_admin}"
        _publish_support_event(thread_key, {"type": "thread_deleted", "threadScope": thread_key})
    return {"deleted": deleted}


@app.get("/api/support-chat/stream")
async def support_chat_stream(request: Request, targetAdminId: str | None = None):
    caller = _support_chat_caller(request, allow_query_token=True)
    if caller.is_staff and not targetAdminId:
        scope: str | None = None
    else:
        scope = f"{caller.member_id}:{_support_chat_target_admin(targetAdminId)}"

    with _SUPPORT_STREAM_LOCK:
        if len(_SUPPORT_STREAM_SUBSCRIBERS) >= _SUPPORT_STREAM_MAX_SUBSCRIBERS:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Live updates are busy; refresh later.")

    async def stream_events():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
        with _SUPPORT_STREAM_LOCK:
            _SUPPORT_STREAM_SUBSCRIBERS[queue] = scope
        try:
            yield 'data: {"type": "ready"}\n\n'
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_SUPPORT_STREAM_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    # Comment frame keeps proxies (Cloudflare/Railway) from closing an idle stream.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            with _SUPPORT_STREAM_LOCK:
                _SUPPORT_STREAM_SUBSCRIBERS.pop(queue, None)

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_ADMIN_HEALTH_TONES = {"online": "ok", "maintenance": "warn", "degraded": "warn", "offline": "bad"}
_ADMIN_WAR_LABELS = {
    "active": ("Active theatre", "ok"),
    "victory": ("Victory declared", "ok"),
    "retreat": ("Strategic withdrawal", "bad"),
    "peace": ("Stood down", "muted"),
}


async def _require_admin_user(request: Request) -> tuple[dict | None, list[dict], Any, Response | None]:
    user, guilds = await _load_user_context(request)
    if not user:
        return None, [], None, RedirectResponse(url="/login")
    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user.get("id") else None
    if not can_manage_portal(user_id, owner_settings.managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the admin controls.",
        )
    return user, guilds, owner_settings, None


@app.get("/admin/legacy", include_in_schema=False)
async def admin_console_legacy_redirect():
    return RedirectResponse(url="/admin", status_code=status.HTTP_308_PERMANENT_REDIRECT)


@app.get("/admin", include_in_schema=False)
async def admin_console(request: Request):
    tos_redirect = _require_tos_consent(request)
    if tos_redirect:
        return tos_redirect

    user, guilds, owner_settings, redirect = await _require_admin_user(request)
    if redirect:
        return redirect
    if templates is None:
        return HTMLResponse("<h1>Admin console unavailable</h1><p>Template rendering is unavailable.</p>")

    user_id = str(user.get("id"))
    display_name = str(user.get("global_name") or "").strip() or str(user.get("username") or "").strip()

    health_state = get_system_health_state()
    health_status = _normalise_health_status(health_state.get("status"))
    health_options = [
        {
            "key": key,
            "label": option.get("label", key.title()),
            "description": option.get("description", ""),
            "tone": _ADMIN_HEALTH_TONES.get(key, "muted"),
        }
        for key, option in _HEALTH_STATUS_OPTIONS.items()
    ]

    lock_state = getattr(request.state, "site_lock_state", None)
    if not isinstance(lock_state, Mapping):
        lock_state = get_site_lock_state()
    lock_message = clean_site_lock_message(lock_state.get("message"))

    war_state = load_pyro_war_state()
    war_status = str(war_state.get("war_status") or "active").strip().lower()
    if war_status not in _WAR_STATUS_VALUES:
        war_status = "active"
    war_label, war_tone = _ADMIN_WAR_LABELS.get(war_status, ("Active theatre", "ok"))

    try:
        bot_guilds = await get_bot_guilds()
    except httpx.HTTPError as exc:
        logger.warning(
            "Admin console: could not load the bot's Discord servers (%s)",
            _describe_discord_error(exc),
        )
        bot_guilds = []
    discord_servers = sorted(
        (
            {"id": str(guild["id"]), "name": str(guild.get("name") or guild["id"])}
            for guild in bot_guilds
            if isinstance(guild, dict) and guild.get("id")
        ),
        key=lambda guild: guild["name"].lower(),
    )

    try:
        server_blacklist = await run_blocking(list_blacklisted_guilds)
    except Exception:
        logger.exception("Admin console: could not read the server blacklist")
        server_blacklist = None
    else:
        try:
            await get_moderation_service().sync_server_blacklist(server_blacklist)
        except Exception:
            logger.exception("Admin console: could not match server sanctions to the blacklist")

    context = {
        "request": request,
        "brand": BRAND,
        "build": BUILD,
        "region": REGION,
        "space": SPACE,
        "display_name": display_name or "Admin",
        "is_director": is_owner(user_id),
        "flash": _render_panel_flash_block(_pop_panel_flash(request)),
        "health_status": health_status,
        "health_note": str(health_state.get("note") or ""),
        "health_options": health_options,
        "health_label": _HEALTH_STATUS_OPTIONS.get(health_status, {}).get("label", "Online"),
        "health_tone": _ADMIN_HEALTH_TONES.get(health_status, "muted"),
        "lock_state": lock_state,
        "lock_message_custom": "" if lock_message == SITE_LOCK_MESSAGE_DEFAULT else lock_message,
        "lock_message_default": SITE_LOCK_MESSAGE_DEFAULT,
        "lock_message_max": SITE_LOCK_MESSAGE_MAX_LENGTH,
        "lock_since_label": _format_lock_timestamp(lock_state.get("enabled_at")),
        "broadcast": {
            "version": owner_settings.bot_version.strip(),
            "message": owner_settings.latest_update.strip(),
            "priority": normalise_broadcast_priority(owner_settings.latest_update_priority),
        },
        "war_status": war_status,
        "war_label": war_label,
        "war_tone": war_tone,
        "war_message": _war_outcome_copy(war_state, war_status) if war_status != "active" else "",
        "discord_servers": discord_servers,
        "server_blacklist": [
            {**entry, "banned_label": _format_lock_timestamp(entry["banned_at"])}
            for entry in server_blacklist or []
        ],
        "server_blacklist_error": server_blacklist is None,
        "blacklist_reason_max": GUILD_BLACKLIST_REASON_MAX_LENGTH,
        "bot": await run_blocking(_director_bot_snapshot),
        "bot_facts": await _render_bot_facts_block(user, request),
        "user_guilds": [
            {"id": str(guild.get("id")), "name": str(guild.get("name") or guild.get("id"))}
            for guild in guilds
            if isinstance(guild, dict) and guild.get("id")
        ],
        "cors_origin": DASHBOARD_ORIGIN or "",
        "session_cookie_name": SESSION_COOKIE_NAME,
        "session_cookie_present": SESSION_COOKIE_NAME in request.cookies,
        "default_payload": DEFAULT_PAYLOAD,
        "console_config": {
            "brand": BRAND,
            "discordServers": discord_servers,
            "isDirector": is_owner(user_id),
        },
    }
    response = templates.TemplateResponse(request, "admin.html", context)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/admin/maintenance", include_in_schema=False)
async def update_maintenance_mode(request: Request):
    user, _guilds, _settings, redirect = await _require_admin_user(request)
    if redirect:
        return redirect

    form = await request.form()
    mode = str(form.get("mode") or "").strip().lower()
    actor = _format_actor(user)

    if mode == "enable":
        set_site_lock_state(True, actor=actor, message=form.get("lock_message"))
        _push_panel_flash(request, "warn", "Lockdown enabled. Visitors now see the maintenance notice.")
    elif mode == "update":
        update_site_lock_message(form.get("lock_message"))
        _push_panel_flash(request, "success", "Lockdown notice updated.")
    elif mode == "disable":
        set_site_lock_state(False, actor=actor)
        _push_panel_flash(request, "success", "Lockdown lifted. The website is open again.")
    else:
        _push_panel_flash(request, "error", "Unsupported lockdown action.")

    return RedirectResponse(url="/admin#site", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/definitions", include_in_schema=False)
async def definition_images_admin(request: Request, _: bool = Depends(require_portal_admin)):
    manifest = _definition_manifest()
    entries = _definition_image_entries(manifest)
    suggestions = _definition_label_suggestions(manifest)
    panel_flash = _render_panel_flash_block(_pop_panel_flash(request))
    brand_image_url = _brand_image_url(manifest)
    wallpaper_manifest = _wallpaper_manifest()
    wallpaper_entries = _wallpaper_entries(wallpaper_manifest)

    if templates is None:
        return JSONResponse(
            {
                "brand": BRAND,
                "brand_image_url": brand_image_url,
                "accent": ACCENT,
                "definitions": entries,
                "suggestions": suggestions,
                "max_size_bytes": _MAX_DEFINITION_IMAGE_BYTES,
                "accept": accepted_image_content_types(),
                "wallpapers": wallpaper_entries,
                "wallpaper_pages": _WALLPAPER_PAGES,
                "wallpaper_accept": accepted_wallpaper_types(),
            }
        )

    return templates.TemplateResponse(
        request,
        "definition_images.html",
        {
            "request": request,
            "brand": BRAND,
            "brand_image_url": brand_image_url,
            "accent": ACCENT,
            "entries": entries,
            "suggestions": suggestions,
            "panel_flash": panel_flash,
            "accept": _DEFINITION_ACCEPT_HEADER,
            "formats": _join_with_or(_DEFINITION_IMAGE_LABELS),
            "max_size_bytes": _MAX_DEFINITION_IMAGE_BYTES,
            "max_size_mb": _MAX_DEFINITION_IMAGE_BYTES // (1024 * 1024),
            "wallpapers": wallpaper_entries,
            "wallpaper_accept": _WALLPAPER_ACCEPT_HEADER,
            "wallpaper_pages": _WALLPAPER_PAGES,
        },
    )


@app.post("/admin/definitions", include_in_schema=False)
async def upload_definition_image(request: Request, _: bool = Depends(require_portal_admin)):
    form = await request.form()
    raw_slug = form.get("slug")
    slug = (raw_slug or "").strip()
    upload = _coerce_upload_file(form.get("image"))

    if not slug:
        _push_panel_flash(request, "error", "Enter a label for this definition image.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    if not upload or not upload.filename:
        _push_panel_flash(request, "error", "Choose an image file to upload.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    file_bytes = await upload.read()
    if not file_bytes:
        _push_panel_flash(request, "error", "Uploaded file was empty.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    if len(file_bytes) > _MAX_DEFINITION_IMAGE_BYTES:
        limit_mb = _MAX_DEFINITION_IMAGE_BYTES // (1024 * 1024)
        _push_panel_flash(
            request,
            "error",
            f"Image too large. Maximum size is {limit_mb} MB.",
        )
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    detected = detect_image_format(file_bytes)
    if not detected:
        _push_panel_flash(
            request,
            "error",
            f"Unsupported file type. Accepted formats: {_join_with_or(_DEFINITION_IMAGE_LABELS)}.",
        )
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    extension, content_type = detected
    try:
        save_definition_image(slug, file_bytes, content_type=content_type, extension=extension)
    except Exception:
        logger.exception("Failed to save definition image")
        _push_panel_flash(request, "error", "Could not save the image. Try again.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    cleaned = normalize_definition_slug(slug) or slug
    _push_panel_flash(
        request,
        "success",
        f"Updated image for '{cleaned}'.",
    )
    return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/definitions/delete", include_in_schema=False)
async def delete_definition_image_route(
    request: Request, _: bool = Depends(require_portal_admin)
):
    form = await request.form()
    slug = (form.get("slug") or "").strip()
    if not slug:
        _push_panel_flash(request, "error", "Missing definition name to delete.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    delete_definition_image(slug)
    cleaned = normalize_definition_slug(slug) or slug
    _push_panel_flash(request, "success", f"Removed image for '{cleaned}'.")
    return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/wallpapers", include_in_schema=False)
async def upload_wallpaper_route(request: Request, _: bool = Depends(require_portal_admin)):
    form = await request.form()
    raw_slug = form.get("page")
    slug = normalize_wallpaper_slug(raw_slug)
    upload = _coerce_upload_file(form.get("image"))

    if not slug or slug not in _WALLPAPER_PAGES:
        _push_panel_flash(request, "error", "Choose a valid page to update.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    if not upload or not upload.filename:
        _push_panel_flash(request, "error", "Choose an image file to upload.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    file_bytes = await upload.read()
    if not file_bytes:
        _push_panel_flash(request, "error", "Uploaded file was empty.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    if len(file_bytes) > _MAX_DEFINITION_IMAGE_BYTES:
        limit_mb = _MAX_DEFINITION_IMAGE_BYTES // (1024 * 1024)
        _push_panel_flash(
            request,
            "error",
            f"Image too large. Maximum size is {limit_mb} MB.",
        )
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    detected = detect_wallpaper_format(file_bytes)
    if not detected:
        _push_panel_flash(
            request,
            "error",
            f"Unsupported file type. Accepted formats: {_join_with_or(_DEFINITION_IMAGE_LABELS)}.",
        )
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    extension, content_type = detected
    try:
        save_wallpaper(slug, file_bytes, content_type=content_type, extension=extension)
    except Exception:
        logger.exception("Failed to save wallpaper image")
        _push_panel_flash(request, "error", "Could not save the wallpaper. Try again.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    _push_panel_flash(
        request,
        "success",
        f"Updated wallpaper for {_WALLPAPER_PAGES.get(slug, slug)}.",
    )
    return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/wallpapers/delete", include_in_schema=False)
async def delete_wallpaper_route(request: Request, _: bool = Depends(require_portal_admin)):
    form = await request.form()
    raw_slug = form.get("page")
    slug = normalize_wallpaper_slug(raw_slug)
    if not slug or slug not in _WALLPAPER_PAGES:
        _push_panel_flash(request, "error", "Missing wallpaper target to delete.")
        return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)

    delete_wallpaper(slug)
    _push_panel_flash(
        request,
        "success",
        f"Removed wallpaper for {_WALLPAPER_PAGES.get(slug, slug)}.",
    )
    return RedirectResponse(url="/admin/definitions", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/system-health", include_in_schema=False)
async def update_system_health(request: Request):
    user, _guilds = await _load_user_context(request)
    if not user:
        return RedirectResponse(url="/login")

    owner_settings, _ = load_owner_settings()
    user_id = str(user.get("id")) if user and user.get("id") else None
    if not can_manage_portal(user_id, owner_settings.managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the admin controls.",
        )

    form = await request.form()
    status_value = str(form.get("status") or "").strip().lower()
    note_value = form.get("note") or ""
    set_system_health_state(status_value, note_value)
    _push_panel_flash(request, "success", "System health broadcast updated.")
    return RedirectResponse(url="/admin#site", status_code=status.HTTP_303_SEE_OTHER)


def _moderation_actor(user: dict) -> dict[str, str | None]:
    """The admin as moderation records name them, matching the console's API token."""

    return {"id": _clean_discord_id(user.get("id")), "name": _user_display_name(user) or None}


@app.post("/admin/servers/blacklist", include_in_schema=False)
async def blacklist_server(request: Request):
    user, _guilds, _settings, redirect = await _require_admin_user(request)
    if redirect:
        return redirect

    form = await request.form()
    guild_id = normalise_guild_id(form.get("guild_id"))
    if guild_id is not None and guild_id == str(GUILD_ID):
        _push_panel_flash(request, "error", f"That is {BRAND}'s home server, so it can't be blacklisted.")
        return RedirectResponse(url="/admin#servers", status_code=status.HTTP_303_SEE_OTHER)

    try:
        bot_guilds = await get_bot_guilds()
    except httpx.HTTPError:
        bot_guilds = []
    name = next(
        (str(g.get("name") or "") for g in bot_guilds if isinstance(g, dict) and str(g.get("id")) == guild_id),
        None,
    )

    try:
        entry = await get_moderation_service().blacklist_server(
            form.get("guild_id"),
            reason=form.get("reason"),
            name=name,
            actor=_moderation_actor(user),
        )
    except ValueError as exc:
        _push_panel_flash(request, "error", str(exc))
        return RedirectResponse(url="/admin#servers", status_code=status.HTTP_303_SEE_OTHER)
    except Exception:
        logger.exception("Failed to save the server blacklist")
        _push_panel_flash(request, "error", "Could not save the blacklist. Try again.")
        return RedirectResponse(url="/admin#servers", status_code=status.HTTP_303_SEE_OTHER)

    logger.warning("Server %s blacklisted by %s: %s", entry["guild_id"], entry["actor"], entry["reason"])
    label = entry["name"] or f"server {entry['guild_id']}"
    _push_panel_flash(
        request,
        "success",
        f"Blacklisted {label}. Within {GUILD_BLACKLIST_POLL_SECONDS} seconds the bot answers everything there with the ban notice.",
    )
    return RedirectResponse(url="/admin#servers", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/servers/unblacklist", include_in_schema=False)
async def unblacklist_server(request: Request):
    user, _guilds, _settings, redirect = await _require_admin_user(request)
    if redirect:
        return redirect

    form = await request.form()
    guild_id = normalise_guild_id(form.get("guild_id"))
    try:
        lifted = await get_moderation_service().lift_server_blacklist(
            guild_id, reason="Lifted from the server blacklist", actor=_moderation_actor(user)
        )
    except Exception:
        logger.exception("Failed to save the server blacklist")
        _push_panel_flash(request, "error", "Could not save the blacklist. Try again.")
        return RedirectResponse(url="/admin#servers", status_code=status.HTTP_303_SEE_OTHER)

    if lifted:
        logger.warning("Server %s removed from the blacklist by %s", guild_id, _format_actor(user))
        _push_panel_flash(request, "success", f"Lifted the blacklist on server {guild_id}. The bot works there again.")
    else:
        _push_panel_flash(request, "error", "That server isn't on the blacklist.")
    return RedirectResponse(url="/admin#servers", status_code=status.HTTP_303_SEE_OTHER)


async def _require_director(request: Request) -> tuple[dict | None, RedirectResponse | None]:
    """Return the director user or a redirect response when unauthenticated."""

    user = request.session.get("user")
    if not user:
        return None, RedirectResponse(url="/login")

    if not is_owner(user.get("id")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the director console.",
        )

    return user, None


def _director_guild_id(request: Request) -> int | None:
    guild_hint = request.query_params.get("guild_id") if hasattr(request, "query_params") else None
    return int(guild_hint) if guild_hint and str(guild_hint).strip().isdigit() else None


_WASP_AUDIO_STORAGE_PREFIX = "assets/wasp_music"
_WASP_AUDIO_MAX_BYTES = 20 * 1024 * 1024
_WASP_AUDIO_MANIFEST_KEY = f"{_WASP_AUDIO_STORAGE_PREFIX}/manifest.json"


def _wasp_music_storage_key(filename: str) -> str:
    return f"{_WASP_AUDIO_STORAGE_PREFIX}/{filename}"


def _wasp_music_timestamp(filename: str) -> str:
    match = re.search(r"-(\d{8}-\d{6})\.mp3$", filename, re.IGNORECASE)
    if not match:
        return ""
    try:
        parsed = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return parsed.isoformat()


def _safe_music_filename(filename: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", os.path.splitext(filename)[0]).strip("-._")
    if not stem:
        stem = "wasp-track"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stem}-{timestamp}.mp3"


def _normalize_wasp_music_filename(value: Any) -> str | None:
    candidate = os.path.basename(str(value or "").strip())
    if candidate != str(value or "").strip():
        return None
    if not candidate.lower().endswith(".mp3"):
        return None
    return candidate


def _safe_music_rename_filename(filename: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", os.path.splitext(filename)[0]).strip("-._")
    if not stem:
        stem = "wasp-track"
    return f"{stem}.mp3"


def _load_wasp_music_order() -> list[str]:
    try:
        payload = read_json(_WASP_AUDIO_MANIFEST_KEY)
    except FileNotFoundError:
        return []
    except Exception:
        logger.exception("Failed to read W.A.S.P. music manifest")
        return []

    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("order")
    if not isinstance(raw, list):
        return []

    normalized: list[str] = []
    for item in raw:
        name = _normalize_wasp_music_filename(item)
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def _save_wasp_music_order(order: list[str]) -> None:
    payload = {
        "order": order,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json(_WASP_AUDIO_MANIFEST_KEY, payload)
    _invalidate_wasp_track_cache()


def _resolve_wasp_music_order(available_filenames: list[str]) -> list[str]:
    current_order = _load_wasp_music_order()
    ordered = [name for name in current_order if name in available_filenames]
    for name in available_filenames:
        if name not in ordered:
            ordered.append(name)
    return ordered


# Nearly every page embeds the playlist, so it is cached briefly instead of costing
# two storage round trips per render. Uploads, renames, deletes and reorders
# invalidate it immediately.
_WASP_TRACK_LIST_TTL_SECONDS = 30.0
_wasp_track_list_cache: dict[bool, tuple[float, list[dict[str, str]]]] = {}


def _list_uploaded_wasp_tracks(*, newest_first: bool = True) -> list[dict[str, str]]:
    now = time.monotonic()
    cached = _wasp_track_list_cache.get(newest_first)
    if cached and now - cached[0] < _WASP_TRACK_LIST_TTL_SECONDS:
        return [dict(item) for item in cached[1]]
    tracks = _scan_uploaded_wasp_tracks(newest_first=newest_first)
    if tracks is None:
        return []
    _wasp_track_list_cache[newest_first] = (now, tracks)
    return [dict(item) for item in tracks]


def _scan_uploaded_wasp_tracks(*, newest_first: bool) -> list[dict[str, str]] | None:
    tracks: list[dict[str, str]] = []
    try:
        _subdirs, files = list_dir(_WASP_AUDIO_STORAGE_PREFIX, limit=500)
    except Exception:
        logger.exception("Failed to list uploaded W.A.S.P. tracks")
        return None

    for filename, size in files:
        if "/" in filename:
            continue
        if not filename.lower().endswith(".mp3"):
            continue
        modified = _wasp_music_timestamp(filename)
        tracks.append(
            {
                "filename": filename,
                "size": str(size),
                "updated_at": modified,
                "url": f"/media/wasp/{quote(filename)}",
                "download_url": f"/media/wasp/{quote(filename)}?download=1",
            }
        )
    if newest_first:
        tracks.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return tracks

    tracks.sort(key=lambda item: item.get("updated_at", ""))
    tracks_by_name = {item["filename"]: item for item in tracks}
    ordered_names = _resolve_wasp_music_order(list(tracks_by_name.keys()))
    return [tracks_by_name[name] for name in ordered_names if name in tracks_by_name]


# Track metadata is cached briefly because browsers fire several Range requests per
# track (probe, buffer, seek) and each would otherwise cost a storage HEAD call.
_WASP_TRACK_STAT_TTL_SECONDS = 60.0
_wasp_track_stat_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _invalidate_wasp_track_cache() -> None:
    _wasp_track_stat_cache.clear()
    _wasp_track_list_cache.clear()


def _wasp_track_stat(key: str) -> dict[str, Any]:
    now = time.monotonic()
    cached = _wasp_track_stat_cache.get(key)
    if cached and now - cached[0] < _WASP_TRACK_STAT_TTL_SECONDS:
        return cached[1]
    info = storage_spaces.stat_file(key)
    _wasp_track_stat_cache[key] = (now, info)
    return info


class _UnsatisfiableRange(Exception):
    pass


def _parse_byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single ``bytes=`` range into an inclusive ``(start, end)`` pair.

    Returns ``None`` when the header is absent, malformed or asks for several
    ranges (the full body is served instead) and raises ``_UnsatisfiableRange``
    when the range lies outside the file.
    """

    if not header:
        return None
    unit, _, spec = header.strip().partition("=")
    if unit.strip().lower() != "bytes" or not spec or "," in spec:
        return None
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    first, last = first.strip(), last.strip()
    try:
        if not first:
            suffix = int(last)
            if suffix <= 0:
                raise _UnsatisfiableRange()
            start, end = max(0, size - suffix), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
    except ValueError:
        return None
    if start < 0 or end < start:
        return None
    if start >= size:
        raise _UnsatisfiableRange()
    return start, min(end, size - 1)


@app.api_route("/media/wasp/{filename}", methods=["GET", "HEAD"], include_in_schema=False)
async def get_wasp_music_track(request: Request, filename: str):
    candidate = os.path.basename(str(filename or "").strip())
    if candidate != filename or not candidate.lower().endswith(".mp3"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Track not found")

    key = _wasp_music_storage_key(candidate)
    try:
        info = await run_blocking(_wasp_track_stat, key)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Track not found")
    except Exception:
        logger.exception("Failed to read uploaded W.A.S.P. track: %s", candidate)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to read track")

    size = int(info.get("size") or 0)
    content_type = str(info.get("content_type") or "")
    media_type = "audio/mpeg" if content_type in ("", "application/octet-stream") else content_type
    etag = f'"{info.get("etag")}"' if info.get("etag") else ""
    download_requested = str(request.query_params.get("download") or "").strip().lower() in {"1", "true", "yes", "on"}
    content_disposition = "attachment" if download_requested else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        "Content-Disposition": f'{content_disposition}; filename="{candidate}"',
    }
    if etag:
        headers["ETag"] = etag
    modified = info.get("modified")
    if modified:
        headers["Last-Modified"] = datetime.fromtimestamp(float(modified), timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )

    if etag and request.headers.get("if-none-match", "").strip() in (etag, f"W/{etag}", "*"):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    range_header = request.headers.get("range")
    if_range = request.headers.get("if-range", "").strip()
    if if_range and if_range not in (etag, headers.get("Last-Modified")):
        range_header = None
    try:
        byte_range = _parse_byte_range(range_header, size)
    except _UnsatisfiableRange:
        headers["Content-Range"] = f"bytes */{size}"
        return Response(status_code=416, headers=headers)

    if byte_range is None:
        start, end, status_code = 0, size - 1, status.HTTP_200_OK
    else:
        start, end = byte_range
        status_code = status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(max(0, end - start + 1))

    if request.method == "HEAD" or size == 0:
        return Response(status_code=status_code, headers=headers, media_type=media_type)

    try:
        chunks = await run_blocking(
            storage_spaces.iter_file_range, key, start, end if byte_range is not None else None
        )
    except FileNotFoundError:
        _invalidate_wasp_track_cache()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Track not found")
    except Exception:
        logger.exception("Failed to stream uploaded W.A.S.P. track: %s", candidate)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to read track")
    return StreamingResponse(chunks, status_code=status_code, headers=headers, media_type=media_type)


def _director_bot_snapshot() -> dict[str, Any]:
    """Return the Discord bot's requested and reported state for the director console."""

    try:
        control = get_bot_control()
        bot_status = get_bot_status()
    except Exception:
        logger.exception("Failed to read Discord bot control state")
        return {
            "available": False,
            "desired": "running",
            "label": "Unavailable",
            "tone": "muted",
            "detail": "The bot state could not be read from storage.",
        }

    summary = describe_bot_state(control, bot_status)
    connected = bot_status["state"] == "online"
    return {
        "available": True,
        "desired": control["desired"],
        **summary,
        "actor": control["actor"],
        "reason": control["reason"],
        "updated_label": _format_lock_timestamp(control["updated_at"]),
        "heartbeat_at": bot_status["heartbeat_at"],
        "heartbeat_label": _format_lock_timestamp(bot_status["heartbeat_at"]),
        "bot_user": bot_status["bot_user"] if connected else None,
        "guild_count": bot_status["guild_count"] if connected else None,
        "latency_ms": bot_status["latency_ms"] if connected else None,
    }


@app.get("/director/bot/status", include_in_schema=False)
async def director_bot_status(request: Request):
    _user, redirect = await _require_director(request)
    if redirect:
        return redirect
    snapshot = await run_blocking(_director_bot_snapshot)
    return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})


@app.get("/director/website-management", include_in_schema=False)
async def director_website_management(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    owner_settings, etag = load_owner_settings(with_etag=True)
    lock_state = getattr(request.state, "site_lock_state", None)
    if not isinstance(lock_state, Mapping):
        lock_state = get_site_lock_state()

    admins = sorted(set(str(mid) for mid in owner_settings.managers if str(mid).strip()))
    uploads = _list_uploaded_wasp_tracks(newest_first=False)

    if templates is None:
        return JSONResponse(
            {
                "user": user,
                "site_lock_state": lock_state,
                "admins": admins,
                "music_uploads": uploads,
                "owner_user_id": OWNER_USER_KEY,
            }
        )

    lock_message = clean_site_lock_message(lock_state.get("message"))
    context = {
        "request": request,
        "brand": BRAND,
        "user": user,
        "etag": etag or "",
        "site_lock_state": lock_state,
        "lock_message_custom": "" if lock_message == SITE_LOCK_MESSAGE_DEFAULT else lock_message,
        "lock_message_default": SITE_LOCK_MESSAGE_DEFAULT,
        "lock_message_max": SITE_LOCK_MESSAGE_MAX_LENGTH,
        "lock_since_label": _format_lock_timestamp(lock_state.get("enabled_at")),
        "bot": await run_blocking(_director_bot_snapshot),
        "bot_reason_max": BOT_CONTROL_REASON_MAX_LENGTH,
        "admins": admins,
        "music_uploads": uploads,
        "panel_flash": _render_panel_flash_block(_pop_panel_flash(request)),
        "owner_user_id": OWNER_USER_KEY,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(
        request,
        "director_website_management.html",
        _inject_wallpaper(context, "director"),
    )


@app.post("/director/website-management/lockdown-preview", include_in_schema=False)
async def preview_director_lockdown_notice(request: Request):
    """Show directors the maintenance screen visitors would see, using the draft reason."""

    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    form = await request.form()
    state = dict(get_site_lock_state())
    state["message"] = form.get("lock_message")
    if not state.get("enabled"):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state.update({"actor": _format_actor(user), "enabled_at": now, "updated_at": now})
    return _build_maintenance_response(state, preview=True)


@app.post("/director/website-management", include_in_schema=False)
async def update_director_website_management(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    form = await request.form()
    action = str(form.get("action") or "").strip()

    if action == "toggle_lockdown":
        enabled = _form_bool(form.get("enabled"))
        actor = _format_actor(user)
        if enabled:
            set_site_lock_state(True, actor=actor, message=form.get("lock_message"))
            _push_panel_flash(request, "success", "Website lockdown enabled.")
        else:
            set_site_lock_state(False, actor=actor)
            _push_panel_flash(request, "success", "Website lockdown disabled.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    if action == "update_lockdown_message":
        update_site_lock_message(form.get("lock_message"))
        _push_panel_flash(request, "success", "Lockdown notice updated.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    if action == "bot_control":
        bot_action = str(form.get("bot_action") or "").strip().lower()
        if bot_action not in BOT_CONTROL_ACTIONS:
            _push_panel_flash(request, "error", "Unsupported bot action.")
        else:
            actor = _format_actor(user)
            try:
                await run_blocking(set_bot_control, bot_action, actor=actor, reason=form.get("bot_reason"))
            except Exception:
                logger.exception("Failed to record Discord bot %s request", bot_action)
                _push_panel_flash(request, "error", "Could not save the bot request to storage. Try again.")
            else:
                logger.warning("Director %s requested Discord bot %s", actor, bot_action)
                messages = {
                    "stop": "Shutdown sent. The bot disconnects from Discord within about 10 seconds.",
                    "start": "Start sent. The bot reconnects to Discord within about 10 seconds.",
                    "restart": "Restart sent. The bot reconnects to Discord within about 10 seconds.",
                }
                _push_panel_flash(request, "warn" if bot_action == "stop" else "success", messages[bot_action])
        return RedirectResponse(url="/director/website-management#bot-controls", status_code=status.HTTP_303_SEE_OTHER)

    if action == "upload_music":
        upload = _coerce_upload_file(form.get("music_file"))
        if upload is None:
            _push_panel_flash(request, "error", "Select an MP3 file to upload.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        filename = str(getattr(upload, "filename", "") or "").strip()
        if not filename.lower().endswith(".mp3"):
            _push_panel_flash(request, "error", "Only .mp3 files are supported.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        file_obj = getattr(upload, "file", None)
        if file_obj is None:
            _push_panel_flash(request, "error", "Upload stream was unavailable.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        file_obj.seek(0, os.SEEK_END)
        byte_size = file_obj.tell()
        file_obj.seek(0)

        if byte_size <= 0:
            _push_panel_flash(request, "error", "Uploaded file was empty.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)
        if byte_size > _WASP_AUDIO_MAX_BYTES:
            _push_panel_flash(request, "error", "MP3 upload is too large (max 20 MB).")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        safe_name = _safe_music_filename(filename)
        key = _wasp_music_storage_key(safe_name)
        buffered_stream = io.BytesIO(file_obj.read())
        save_text(key, buffered_stream, content_type="audio/mpeg")
        _invalidate_wasp_track_cache()
        try:
            existing_names = [item["filename"] for item in _list_uploaded_wasp_tracks(newest_first=False)]
            _save_wasp_music_order(_resolve_wasp_music_order(existing_names))
        except Exception:
            logger.exception("Failed to update W.A.S.P. music order after upload")
        _push_panel_flash(request, "success", f"Uploaded soundtrack: {safe_name}")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    if action == "rename_music":
        current_name = _normalize_wasp_music_filename(form.get("filename"))
        requested_name = str(form.get("new_filename") or "").strip()
        if not current_name:
            _push_panel_flash(request, "error", "Invalid source track filename.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)
        if not requested_name:
            _push_panel_flash(request, "error", "Enter a new filename for the track.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        renamed = _safe_music_rename_filename(requested_name)
        if current_name == renamed:
            _push_panel_flash(request, "error", "Track name is already set to that value.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        existing_names = [item["filename"] for item in _list_uploaded_wasp_tracks(newest_first=False)]
        if current_name not in existing_names:
            _push_panel_flash(request, "error", "Track no longer exists.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)
        if renamed in existing_names:
            _push_panel_flash(request, "error", f"A track named {renamed} already exists.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        source_key = _wasp_music_storage_key(current_name)
        destination_key = _wasp_music_storage_key(renamed)
        try:
            payload, content_type = storage_spaces.read_file(source_key)
            save_text(destination_key, io.BytesIO(payload), content_type=content_type or "audio/mpeg")
            delete_file(source_key)
            _invalidate_wasp_track_cache()
            order = _resolve_wasp_music_order(existing_names)
            order = [renamed if name == current_name else name for name in order]
            _save_wasp_music_order(order)
        except Exception:
            logger.exception("Failed to rename W.A.S.P. track from %s to %s", current_name, renamed)
            _push_panel_flash(request, "error", "Unable to rename track right now.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        _push_panel_flash(request, "success", f"Renamed soundtrack to {renamed}.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    if action == "delete_music":
        target = _normalize_wasp_music_filename(form.get("filename"))
        if not target:
            _push_panel_flash(request, "error", "Invalid track filename.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        existing_names = [item["filename"] for item in _list_uploaded_wasp_tracks(newest_first=False)]
        if target not in existing_names:
            _push_panel_flash(request, "error", "Track no longer exists.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        try:
            delete_file(_wasp_music_storage_key(target))
            _invalidate_wasp_track_cache()
            order = [name for name in _resolve_wasp_music_order(existing_names) if name != target]
            _save_wasp_music_order(order)
        except Exception:
            logger.exception("Failed to delete W.A.S.P. track %s", target)
            _push_panel_flash(request, "error", "Unable to delete track right now.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        _push_panel_flash(request, "success", f"Removed soundtrack: {target}.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    if action == "reorder_music":
        existing_names = [item["filename"] for item in _list_uploaded_wasp_tracks(newest_first=False)]
        if not existing_names:
            _push_panel_flash(request, "error", "No tracks available to reorder.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        existing_set = set(existing_names)
        slot_names = [_normalize_wasp_music_filename(x) for x in form.getlist("track_order")]
        slot_names = [name for name in slot_names if name]

        if slot_names:
            if len(slot_names) != len(existing_set) or set(slot_names) != existing_set:
                _push_panel_flash(
                    request,
                    "error",
                    "Track order did not match the current library; refresh the page and try again.",
                )
                return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)
            ordered = slot_names
        else:
            ranked: list[tuple[int, str]] = []
            for index, name in enumerate(existing_names, start=1):
                raw_rank = str(form.get(f"position_{name}") or "").strip()
                try:
                    rank_value = int(raw_rank)
                except ValueError:
                    rank_value = index
                ranked.append((max(rank_value, 1), name))
            ranked.sort(key=lambda item: (item[0], item[1].lower()))
            ordered = [name for _rank, name in ranked]
        try:
            _save_wasp_music_order(ordered)
        except Exception:
            logger.exception("Failed to persist W.A.S.P. music order")
            _push_panel_flash(request, "error", "Unable to save custom track order.")
            return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

        _push_panel_flash(request, "success", "Track order updated.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    settings, etag = load_owner_settings(with_etag=True)
    actor = _format_actor(user)

    if action == "add_admin":
        candidate = validate_discord_id(form.get("admin_id"))
        if not candidate:
            _push_panel_flash(request, "error", "Enter a valid numeric Discord user ID.")
        elif candidate == OWNER_USER_KEY:
            _push_panel_flash(request, "error", "The Director already has admin authority.")
        elif candidate in settings.managers:
            _push_panel_flash(request, "error", "That user is already listed as admin.")
        else:
            updated = settings.copy()
            updated.managers.append(candidate)
            updated.append_log_entry(build_change_entry(actor, "Admin added", f"Granted admin to {candidate}"))
            if save_owner_settings(updated, etag=etag):
                _push_panel_flash(request, "success", f"Admin access granted to {candidate}.")
            else:
                _push_panel_flash(request, "error", "Admin list changed on the server. Refresh and retry.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    if action == "remove_admin":
        target = validate_discord_id(form.get("admin_id"))
        if not target:
            _push_panel_flash(request, "error", "Enter a valid numeric Discord user ID.")
        elif target not in settings.managers:
            _push_panel_flash(request, "error", "That user is not in the admin list.")
        else:
            updated = settings.copy()
            updated.managers = [mid for mid in updated.managers if mid != target]
            updated.append_log_entry(build_change_entry(actor, "Admin removed", f"Revoked admin from {target}"))
            if save_owner_settings(updated, etag=etag):
                _push_panel_flash(request, "success", f"Admin removed: {target}.")
            else:
                _push_panel_flash(request, "error", "Admin list changed on the server. Refresh and retry.")
        return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)

    _push_panel_flash(request, "error", "Unsupported website management action.")
    return RedirectResponse(url="/director/website-management", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/director", include_in_schema=False)
async def director_console(request: Request):
    """Placeholder console reserved for the configured owner."""

    tos_redirect = _require_tos_consent(request)
    if tos_redirect:
        return tos_redirect

    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    guild_hint = request.query_params.get("guild_id") if hasattr(request, "query_params") else None
    guild_id = int(guild_hint) if guild_hint and str(guild_hint).strip().isdigit() else None

    personnel_records, personnel_notice = await run_blocking(_load_personnel_records, guild_id)
    personnel_stats = _summarise_personnel_records(personnel_records)
    broadcast_history = [entry.to_payload() for entry in load_broadcast_history(limit=5)]
    lock_state = getattr(request.state, "site_lock_state", None)
    if not isinstance(lock_state, Mapping):
        lock_state = get_site_lock_state()

    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    if templates is None:
        return JSONResponse(
            {
                "message": "Director console available only to the configured owner.",
                "user": user,
                "personnel_records": personnel_records,
                "personnel_notice": personnel_notice,
                "personnel_stats": personnel_stats,
                "broadcast_history": broadcast_history,
            }
        )

    context = {
        "request": request,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_image_url": brand_image_url,
        "user": user,
        "user_avatar": _avatar_url(user),
        "personnel_records": personnel_records,
        "personnel_notice": personnel_notice,
        "personnel_stats": personnel_stats,
        "broadcast_history": broadcast_history,
        "site_lock_state": lock_state,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }

    return templates.TemplateResponse(
        request,
        "director.html",
        _inject_wallpaper(context, "director"),
    )


@app.get("/director/personnel", include_in_schema=False)
async def director_personnel_console(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    owner_settings, _owner_etag = load_owner_settings()
    team_settings = load_admin_team_settings()
    bios = load_admin_bios()
    effective_members = team_settings.members or _default_admin_team_member_ids(owner_settings)
    roster = await _build_admin_roster_entries(
        effective_members,
        bios,
        str(user.get("id")),
        team_settings.ranks,
        team_settings.clearances,
    )

    if templates is None:
        return JSONResponse({"roster": roster, "member_ids": effective_members})

    return templates.TemplateResponse(
        request,
        "director_personnel.html",
        _inject_wallpaper(
            {
                "request": request,
                "brand": BRAND,
                "user": user,
                "roster": roster,
                "panel_flash": _render_panel_flash_block(_pop_panel_flash(request)),
                "member_ids": "\n".join(effective_members),
                "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
            },
            "director",
        ),
    )


@app.post("/director/personnel", include_in_schema=False)
async def update_director_personnel_console(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    form = await request.form()
    member_lines = str(form.get("member_ids") or "")
    parsed_members: list[str] = []
    seen: set[str] = set()
    for raw_line in member_lines.replace(",", "\n").splitlines():
        cleaned = _clean_discord_id(raw_line)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            parsed_members.append(cleaned)

    ranks: dict[str, str] = {}
    clearances: dict[str, str] = {}
    for key, value in form.multi_items():
        key_text = str(key)
        if key_text.startswith("rank_"):
            user_id = _clean_discord_id(key_text[5:])
            if not user_id:
                continue
            rank_text = normalise_rank_text(str(value) if value is not None else "")
            if rank_text:
                ranks[user_id] = rank_text
            continue
        if key_text.startswith("clearance_"):
            user_id = _clean_discord_id(key_text[10:])
            if not user_id:
                continue
            clearance_text = normalise_clearance_text(str(value) if value is not None else "")
            if clearance_text:
                clearances[user_id] = clearance_text

    save_admin_team_settings(
        AdminTeamSettings(members=parsed_members, ranks=ranks, clearances=clearances)
    )
    _push_panel_flash(request, "success", "Personnel roster updated.")
    return RedirectResponse(url="/director/personnel", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/director/archives", include_in_schema=False)
async def director_archives(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    guild_id = _director_guild_id(request)
    overview = await run_blocking(_build_archive_overview, guild_id)

    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    context = {
        "request": request,
        "brand": BRAND,
        "brand_image_url": brand_image_url,
        "user": user,
        "overview": overview,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }

    return templates.TemplateResponse(
        request,
        "director_archives.html",
        _inject_wallpaper(context, "director-archives"),
    )


@app.get("/director/security-overview", include_in_schema=False)
async def director_security_overview(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    admin_presence = _list_admin_presence(include_ip=True)
    activity_feed = _activity_snapshot()[:20]

    unique_ips = {
        str(entry.get("ip") or "").strip()
        for entry in admin_presence
        if isinstance(entry.get("ip"), str) and str(entry.get("ip")).strip()
    }
    summary = {
        "total_admins": len(admin_presence),
        "online_admins": sum(1 for entry in admin_presence if entry.get("status") == "Online"),
        "unique_ips": len(unique_ips),
        "activity_events": len(activity_feed),
        "monthly_visits": _monthly_site_visits(),
    }

    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    context = {
        "request": request,
        "brand": BRAND,
        "brand_image_url": brand_image_url,
        "user": user,
        "admin_presence": admin_presence,
        "activity_feed": activity_feed,
        "summary": summary,
        "shield_stats": SECURITY_SHIELD.stats(),
        "shield_blocks": SECURITY_SHIELD.active_blocks(),
        "shield_events": SECURITY_SHIELD.recent_events(25),
        "shield_flash": _render_panel_flash_block(_pop_flash(request, _SECURITY_FLASH_KEY)),
        "shield_block_durations": _SHIELD_MANUAL_BLOCK_DURATIONS,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }

    return templates.TemplateResponse(
        request,
        "director_security_overview.html",
        _inject_wallpaper(context, "director-security-overview"),
    )


_SECURITY_FLASH_KEY = "security_flash"
_SHIELD_MANUAL_BLOCK_DURATIONS = {
    "3600": "1 hour",
    "86400": "24 hours",
    "604800": "7 days",
    "2592000": "30 days",
}


@app.post("/director/security/block", include_in_schema=False)
async def director_block_ip(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect
    form = await request.form()
    duration = str(form.get("duration") or "86400")
    if duration not in _SHIELD_MANUAL_BLOCK_DURATIONS:
        duration = "86400"
    try:
        block = SECURITY_SHIELD.block_ip(
            str(form.get("ip") or ""),
            seconds=int(duration),
            reason=str(form.get("reason") or ""),
            actor=_format_actor(user),
        )
    except ValueError as exc:
        _push_flash(request, _SECURITY_FLASH_KEY, status_label="error", message=str(exc))
    else:
        SECURITY_SHIELD.schedule_flush()
        _push_flash(
            request,
            _SECURITY_FLASH_KEY,
            status_label="success",
            message=f"Blocked {block.ip} for {_SHIELD_MANUAL_BLOCK_DURATIONS[duration]}.",
        )
    return RedirectResponse(url="/director/security-overview", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/director/security/unblock", include_in_schema=False)
async def director_unblock_ip(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect
    form = await request.form()
    ip = str(form.get("ip") or "").strip()
    if SECURITY_SHIELD.unblock_ip(ip, actor=_format_actor(user)):
        SECURITY_SHIELD.schedule_flush()
        _push_flash(request, _SECURITY_FLASH_KEY, status_label="success", message=f"Lifted the block on {ip}.")
    else:
        _push_flash(
            request, _SECURITY_FLASH_KEY, status_label="error", message=f"{ip or 'That address'} is not blocked."
        )
    return RedirectResponse(url="/director/security-overview", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/director/archives/data", include_in_schema=False)
async def director_archives_data(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    guild_id = _director_guild_id(request)
    overview = await run_blocking(_build_archive_overview, guild_id)
    return JSONResponse(overview)


@app.get("/director/broadcasts", include_in_schema=False)
async def fetch_director_broadcasts(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    history = [entry.to_payload() for entry in load_broadcast_history(limit=20)]
    return JSONResponse({"broadcasts": history})


@app.post("/director/broadcasts", include_in_schema=False)
async def push_director_broadcast(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - defensive fallback for malformed JSON
        payload = {}

    raw_priority = str(payload.get("priority") or "standard").strip().lower()
    priority = normalise_broadcast_priority(raw_priority)
    message = str(payload.get("message") or "").strip()
    delivery = str(payload.get("delivery") or "dashboard").strip().lower()

    if raw_priority not in BROADCAST_PRIORITIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Unknown broadcast priority."
        )
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Broadcast message is required.")
    if delivery not in {"dashboard", "discord-alert"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Unknown delivery option.",
        )

    actor = _format_actor(user)
    entry = record_broadcast(message, priority=priority, actor=actor)
    set_operations_broadcast(message, priority=priority, actor=actor)
    dispatch_summary: dict[str, object] = {
        "attempted": 0,
        "delivered": 0,
        "failed": [],
        "skipped": "Dashboard broadcast does not send Discord owner DMs.",
    }
    if delivery == "discord-alert":
        dispatch_summary = await _dispatch_director_alert_to_server_owners(
            message=message,
            priority=priority,
            actor=actor,
        )
        failed = dispatch_summary.get("failed") or []
        logger.log(
            logging.WARNING if failed else logging.INFO,
            "Director alert by %s delivered to %s of %s server owners%s",
            actor,
            dispatch_summary.get("delivered", 0),
            dispatch_summary.get("attempted", 0),
            "".join(f"\n  - {item.get('owner_id') or 'n/a'}: {item.get('reason')}" for item in failed),
        )
    return JSONResponse(
        {
            "status": "ok",
            "broadcast": entry.to_payload(),
            "priority": priority,
            "delivery": delivery,
            "dispatch": dispatch_summary,
        }
    )


@app.post("/director/maintenance", include_in_schema=False)
async def update_director_maintenance(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - defensive fallback for malformed JSON
        payload = {}

    if "enabled" not in payload:
        return JSONResponse(
            {"detail": "Missing enabled flag."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    enabled = bool(payload.get("enabled"))
    actor = _format_actor(user)

    if enabled:
        set_site_lock_state(True, actor=actor, message=payload.get("message"))
    else:
        set_site_lock_state(False, actor=actor)

    return JSONResponse({"state": get_site_lock_state()})


def _build_director_file_payload(guild_id: int | None = None) -> dict[str, object]:
    descriptors = enumerate_dossier_files(guild_id=guild_id)
    valid_keys = {str(entry.get("key") or "").strip() for entry in descriptors if entry.get("key")}
    assignments = synchronise_file_assignments(valid_keys)
    for entry in descriptors:
        key = str(entry.get("key") or "")
        if key and key in assignments:
            entry["assigned_bot"] = assignments[key]
    return {"files": descriptors, "assignments": assignments}


def _collect_archive_items(base_root: str, category: str) -> list[dict[str, str]]:
    start = f"{base_root}/{category}".strip("/")
    stack = [start]
    seen: set[str] = set()
    items: list[dict[str, str]] = []

    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        dirs, files = _list_files_in(current)
        for name, _size in files:
            if not name.lower().endswith((".json", ".txt")):
                continue
            rel = f"{current}/{name}".replace("//", "/")
            rel_from_cat = rel[len(start):].strip("/").replace("\\", "/")
            items.append(
                {
                    "name": _strip_ext(rel_from_cat),
                    "path": rel_from_cat,
                }
            )
        for entry in dirs:
            stack.append(f"{current}/{entry.strip('/')}")

    return sorted(items, key=lambda item: item.get("name", "").lower())


def _build_archive_overview(guild_id: int | None = None) -> dict[str, object]:
    settings: Mapping[str, object] = (
        get_server_config(guild_id) if guild_id is not None else {}
    ) or {}
    base_label, link_names, summary_map, local_root = _archive_source_names(guild_id, settings)
    roots = _archive_root_prefixes(guild_id)
    sources: list[dict[str, object]] = []

    total_files = 0
    total_categories = 0

    for root in roots:
        cleaned_root = str(root or "").strip("/")

        def _append_categories(base_root: str, *, archived: bool = False) -> list[dict[str, object]]:
            nonlocal total_files, total_categories

            dirs, _files = _list_files_in(base_root)
            collected: list[dict[str, object]] = []
            for entry in dirs:
                if not entry.endswith("/"):
                    continue
                name = entry[:-1]
                items = _collect_archive_items(base_root, name)
                category_payload: dict[str, object] = {
                    "name": name,
                    "items": items,
                    "count": len(items),
                }
                if archived:
                    category_payload["archived"] = True
                collected.append(category_payload)
                total_files += len(items)
                total_categories += 1
            return collected

        categories: list[dict[str, object]] = []
        categories.extend(_append_categories(cleaned_root, archived=False))
        categories.extend(_append_categories(f"{cleaned_root}/_archived".strip("/"), archived=True))

        source_summary = summary_map.get(cleaned_root, {})
        source_name = None
        if isinstance(source_summary, Mapping):
            name_raw = source_summary.get("name")
            if isinstance(name_raw, str) and name_raw.strip():
                source_name = name_raw.strip()

        sources.append(
            {
                "root_prefix": cleaned_root,
                "origin": "Local" if cleaned_root == (local_root or "") else "Linked",
                "guild_id": guild_id,
                "name": source_name or link_names.get(cleaned_root) or base_label,
                "categories": sorted(categories, key=lambda entry: entry.get("name", "").lower()),
                "file_count": sum(cat.get("count", 0) for cat in categories),
                "category_count": len(categories),
                "updated_at": source_summary.get("updated_at") if isinstance(source_summary, Mapping) else None,
            }
        )

    return {
        "sources": sources,
        "total_files": total_files,
        "total_categories": total_categories,
        "source_count": len(sources),
    }


@app.get("/director/files", include_in_schema=False)
async def director_files(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    guild_id = _director_guild_id(request)
    payload = await run_blocking(_build_director_file_payload, guild_id)
    return JSONResponse(payload)


@app.get("/director/files/content", include_in_schema=False)
async def director_file_body(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    key = str(request.query_params.get("key") or "").strip()
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing file key")

    guild_id = _director_guild_id(request)
    try:
        body, ext = await run_blocking(read_dossier_body, key, guild_id)
        descriptor = await run_blocking(describe_dossier_key, key, guild_id)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    assignments = load_file_assignments()
    payload = {
        "key": key,
        "body": body,
        "ext": ext,
        "category": descriptor.get("category"),
        "item": descriptor.get("item"),
        "archived": bool(descriptor.get("archived")),
        "assigned_bot": assignments.get(key),
    }
    return JSONResponse(payload)


def _normalize_category_input(raw: str | None) -> str:
    if raw is None:
        return ""
    return str(raw).strip().strip("/")


@app.post("/director/files/update", include_in_schema=False)
async def director_update_file(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - defensive fallback for malformed JSON
        payload = {}

    key = str(payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing file key")

    guild_id = _director_guild_id(request)
    try:
        descriptor = describe_dossier_key(key, guild_id=guild_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    current_category = descriptor.get("category") or ""
    current_item = descriptor.get("item") or ""
    current_archived = bool(descriptor.get("archived"))
    ext = str(descriptor.get("ext") or "").lower()

    target_category = _normalize_category_input(payload.get("category")) or current_category
    target_item = _normalize_category_input(payload.get("name")) or current_item
    target_archived = bool(payload.get("archived")) if "archived" in payload else current_archived

    dest_category_slug = f"_archived/{target_category}" if target_archived else target_category
    src_category_slug = f"_archived/{current_category}" if current_archived else current_category

    updated_key = key
    if dest_category_slug != src_category_slug or target_item != current_item:
        try:
            updated_key = move_dossier_file(
                src_category_slug,
                current_item,
                dest_category_slug,
                new_item_rel_base=target_item,
                guild_id=guild_id,
            )
            descriptor = describe_dossier_key(updated_key, guild_id=guild_id)
            ext = str(descriptor.get("ext") or ext)
        except FileExistsError:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Target file already exists")
        except FileNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File no longer exists")

    if "content" in payload:
        body = str(payload.get("content") or "")
        try:
            if ext.lower() == ".json":
                parsed = json.loads(body)
                save_json(updated_key, parsed)
            else:
                save_text(updated_key, body)
        except json.JSONDecodeError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid JSON content")

    archive_index.invalidate(guild_id)
    assigned_bot = payload.get("assigned_bot")
    if updated_key != key:
        update_file_assignment(key, None)
    assignments = update_file_assignment(updated_key, assigned_bot)

    response_descriptor = describe_dossier_key(updated_key, guild_id=guild_id)
    response_descriptor.update({"assigned_bot": assignments.get(updated_key)})
    return JSONResponse({"status": "ok", "file": response_descriptor, "assignments": assignments})


@app.post("/director/files/delete", include_in_schema=False)
async def director_delete_file(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - defensive fallback for malformed JSON
        payload = {}

    key = str(payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing file key")

    guild_id = _director_guild_id(request)
    try:
        descriptor = describe_dossier_key(key, guild_id=guild_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    category_slug = descriptor.get("category") or ""
    archived = bool(descriptor.get("archived"))
    if archived:
        category_slug = f"_archived/{category_slug}"

    try:
        remove_dossier_file(category_slug, descriptor.get("item") or "", guild_id=guild_id)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found")

    archive_index.invalidate(guild_id)
    assignments = update_file_assignment(key, None)
    return JSONResponse({"status": "deleted", "assignments": assignments})


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
    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    if templates is None:
        return JSONResponse(
            {
                "bot_version": settings.bot_version,
                "latest_update": settings.latest_update,
                "managers": settings.managers,
                "fleet_managers": settings.fleet_managers,
                "chat_access": settings.chat_access,
                "bot_active": settings.bot_active,
                "moderation": settings.moderation.to_payload(),
                "change_log": [entry.to_payload() for entry in settings.change_log],
                "can_add_managers": owner_mode,
                "owner_user_id": OWNER_USER_KEY,
                "brand_image_url": brand_image_url,
            }
        )

    return templates.TemplateResponse(
        request,
        "owner.html",
        _inject_wallpaper(
            {
                "request": request,
                "accent": ACCENT,
                "brand": BRAND,
                "brand_image_url": brand_image_url,
                "user": user,
                "settings": settings,
                "etag": etag or "",
                "can_add_managers": owner_mode,
                "managers": settings.managers,
                "fleet_managers": settings.fleet_managers,
                "chat_access": settings.chat_access,
                "flash": flash,
                "owner_user_id": OWNER_USER_KEY,
                "is_owner": owner_mode,
                "change_log": settings.change_log,
            },
            "owner",
        ),
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
        new_priority = normalise_broadcast_priority(form.get("latest_update_priority"))
        updated.bot_version = new_version
        updated.latest_update = new_update
        updated.latest_update_priority = new_priority

        if (
            new_version == settings.bot_version
            and new_update == settings.latest_update
            and new_priority == settings.latest_update_priority
        ):
            message = "No broadcast changes detected."
        else:
            change_parts = []
            if new_version != settings.bot_version:
                change_parts.append(
                    f"version {settings.bot_version or '—'} → {new_version or '—'}"
                )
            if new_update != settings.latest_update:
                change_parts.append("announcement updated")
            if new_priority != settings.latest_update_priority:
                change_parts.append(
                    f"priority {settings.latest_update_priority or 'standard'} → {new_priority}"
                )
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
    elif action == "add_chat_access":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may add chat access."
        else:
            candidate = validate_discord_id(form.get("chat_access_id"))
            if not candidate:
                status_label = "error"
                message = "Enter a valid numeric Discord user ID."
            elif candidate == OWNER_USER_KEY:
                status_label = "error"
                message = "The owner already has full access."
            elif candidate in settings.chat_access:
                status_label = "error"
                message = "That user already has chat access."
            else:
                updated = settings.copy()
                updated.chat_access.append(candidate)
                updated.append_log_entry(
                    build_change_entry(
                        actor,
                        "Chat access granted",
                        f"Approved A.L.I.C.E. chat for {candidate}",
                    )
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    _clear_chat_access_request(candidate)
                    message = "Chat access added successfully."
                else:
                    status_label = "error"
                    message = "The chat access list changed on the server. Refresh and try again."
    elif action == "remove_chat_access":
        if not owner_mode:
            status_label = "error"
            message = "Only the owner may remove chat access."
        else:
            target = validate_discord_id(form.get("chat_access_id"))
            if not target:
                status_label = "error"
                message = "Enter a valid numeric Discord user ID."
            elif target not in settings.chat_access:
                status_label = "error"
                message = "That user does not have chat access."
            else:
                updated = settings.copy()
                updated.chat_access = [uid for uid in updated.chat_access if uid != target]
                updated.append_log_entry(
                    build_change_entry(
                        actor,
                        "Chat access revoked",
                        f"Removed A.L.I.C.E. chat from {target}",
                    )
                )
                if save_owner_settings(updated, etag=form_etag or etag):
                    message = "Chat access removed."
                else:
                    status_label = "error"
                    message = "The chat access list changed on the server. Refresh and try again."
    elif action == "send_discord_alert":
        if not owner_mode:
            status_label = "error"
            message = "Only the director may send Discord Alerts."
        else:
            alert_message = (form.get("alert_message") or "").strip()
            raw_alert_priority = str(form.get("alert_priority") or "standard").strip().lower()
            alert_priority = normalise_broadcast_priority(raw_alert_priority)

            if raw_alert_priority not in BROADCAST_PRIORITIES:
                status_label = "error"
                message = "Choose a valid alert priority."
            elif not alert_message:
                status_label = "error"
                message = "Enter a Discord alert message before sending."
            else:
                dispatch_summary = await _dispatch_director_alert_to_server_owners(
                    message=alert_message,
                    priority=alert_priority,
                    actor=actor,
                )
                delivered = int(dispatch_summary.get("delivered", 0) or 0)
                attempted = int(dispatch_summary.get("attempted", 0) or 0)
                failed = dispatch_summary.get("failed", [])
                if attempted and delivered:
                    message = (
                        f"Discord Alert sent to {delivered} of {attempted} server owners."
                    )
                    if failed:
                        status_label = "error"
                        message = (
                            f"Discord Alert partially delivered ({delivered}/{attempted})."
                        )
                elif attempted and not delivered:
                    status_label = "error"
                    message = "Discord Alert could not be delivered to server owners."
                else:
                    skip_reason = dispatch_summary.get("skipped")
                    if skip_reason:
                        status_label = "error"
                        message = f"Discord Alert skipped: {skip_reason}"
                    else:
                        status_label = "error"
                        message = "No server owners were available for Discord Alert delivery."
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
    fdd_ships = list(get_fdd_ships())
    fdd_ship_payloads = [ship.to_payload() for ship in fdd_ships]
    spec_slugs = {ship.slug for ship in fdd_ships}
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

    for ship in fdd_ships:
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
    format_labels = _join_with_or(_TECH_SPEC_IMAGE_LABELS)
    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    if templates is None:
        return JSONResponse(
            {
                "last_updated": manifest.last_updated,
                "vessels": [v.to_payload() for v in manifest.vessels],
                "can_manage": can_manage,
                "brand_image_url": brand_image_url,
                "viewer": {
                    "name": viewer_name,
                    "id": viewer_id,
                    "authenticated": is_authenticated,
                },
                "tech_spec_ships": tech_spec_ships,
                "tech_spec_options": tech_spec_options,
                "tech_spec_entries": fdd_ship_payloads,
                "tech_spec_prefill_entries": tech_spec_prefill_entries,
                "tech_spec_accept_types": accepted_image_content_types(),
                "tech_spec_format_labels": format_labels,
            }
        )

    return templates.TemplateResponse(
        request,
        "fleet.html",
        _inject_wallpaper(
            {
                "request": request,
                "accent": ACCENT,
                "brand": BRAND,
                "brand_image_url": brand_image_url,
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
                "tech_spec_entries": fdd_ship_payloads,
                "tech_spec_prefill_entries": tech_spec_prefill_entries,
                "tech_spec_accept_types": _TECH_SPEC_ACCEPT_HEADER,
                "tech_spec_format_labels": format_labels,
            },
            "fleet",
        ),
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


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(_: bool = Depends(require_portal_admin)):
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
async def api_docs(_: bool = Depends(require_portal_admin)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{BRAND} API")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    # Allow-list the landing page rather than listing private paths to avoid.
    return Response("User-agent: *\nAllow: /$\nDisallow: /\n", media_type="text/plain")


def _brand_initials(name: str | None) -> str:
    if not name:
        return "HD"
    parts = [segment for segment in name.strip().split() if segment]
    if not parts:
        return "HD"
    initials = "".join(part[0] for part in parts)[:2]
    return initials.upper() or "HD"


@app.get("/branding/definitions/manifest", include_in_schema=False)
async def definition_image_manifest():
    manifest = _definition_manifest()
    payload = {
        slug: {
            "url": _definition_image_url(slug, manifest),
            "updated_at": meta.get("updated_at", ""),
            "content_type": meta.get("content_type", ""),
        }
        for slug, meta in manifest.items()
    }
    headers = {"Cache-Control": "public, max-age=300"}
    return JSONResponse(payload, headers=headers)


@app.get("/branding/definitions/{slug}", include_in_schema=False)
async def definition_image(slug: str):
    try:
        data, content_type = get_definition_image_bytes(slug)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    headers = {"Cache-Control": "public, max-age=3600"}
    return Response(content=data, media_type=content_type, headers=headers)


@app.get("/branding/wallpapers/manifest", include_in_schema=False)
async def wallpaper_manifest():
    manifest = _wallpaper_manifest()
    payload = {
        slug: {
            "url": _wallpaper_url(slug, manifest),
            "updated_at": meta.get("updated_at", ""),
            "content_type": meta.get("content_type", ""),
        }
        for slug, meta in manifest.items()
    }
    headers = {"Cache-Control": "public, max-age=300"}
    return JSONResponse(payload, headers=headers)


@app.get("/branding/wallpapers/{slug}", include_in_schema=False)
async def wallpaper_image(slug: str):
    try:
        data, content_type = get_wallpaper_bytes(slug)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    headers = {"Cache-Control": "public, max-age=3600"}
    return Response(content=data, media_type=content_type, headers=headers)


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


@app.get("/dossiers/personnel", include_in_schema=False)
async def personnel_board(request: Request, _: bool = Depends(require_auth)):
    guild_hint = request.query_params.get("guild_id") if hasattr(request, "query_params") else None
    guild_id = int(guild_hint) if guild_hint and str(guild_hint).strip().isdigit() else None

    records, notice = await run_blocking(_load_personnel_records, guild_id)
    stats = _summarise_personnel_records(records)
    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

    payload = {
        "brand": BRAND,
        "accent": ACCENT,
        "records": records,
        "stats": stats,
        "notice": notice,
        "brand_image_url": brand_image_url,
    }

    if templates is None:
        return JSONResponse(payload)

    context = _inject_wallpaper(
        {
            "request": request,
            "brand": BRAND,
            "accent": ACCENT,
            "records": records,
            "stats": stats,
            "notice": notice,
            "brand_image_url": brand_image_url,
        },
        "personnel-board",
    )
    return templates.TemplateResponse(request, "personnel_board.html", context)


@app.get("/alice", include_in_schema=False)
async def alice_terminal(request: Request):
    user = request.session.get("user")
    token = request.session.get("discord_token")

    if not user or not token:
        target = str(request.url.path)
        if request.url.query:
            target = f"{target}?{request.url.query}"

        request.session["post_auth_redirect"] = _clean_redirect_target(target, "/alice")
        qp = httpx.QueryParams({"next": target})
        return RedirectResponse(url=f"/login?{qp}")

    if templates is None:
        return JSONResponse({"status": "alice-terminal", "brand": BRAND})

    return templates.TemplateResponse(
        request,
        "alice.html",
        {
            "request": request,
            "brand": BRAND,
            "operator_name": _discord_display_name(user),
            **_chat_access_prompt_context(request),
        },
    )


@app.get("/alice/chat", include_in_schema=False)
async def alice_chat_legacy_redirect(request: Request):
    # The operator chatroom moved out of A.L.I.C.E. and became Project ZETA.
    target = "/zeta"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/zeta", include_in_schema=False)
async def zeta_chat_page(request: Request):
    user = request.session.get("user")
    user_id = _clean_discord_id((user or {}).get("id"))
    viewer_id = _session_chat_viewer_id(request)
    ban = _zeta_ban_for(request, viewer_id)
    vpn_block = None if ban else _zeta_vpn_block(request)
    has_chat_access = viewer_id is not None and ban is None and vpn_block is None
    chat_flash = _pop_chat_access_flash(request)
    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    if has_chat_access:
        _zeta_note_traces(request, viewer_id)
    if has_chat_access and viewer_id == user_id:
        _zeta_remember_member(user)
        try:
            _zeta_import_legacy_dispatches(user_id)
        except zeta_dm.DirectMessageConflict:
            pass  # Picked up again on the next visit.
    elif has_chat_access and _zeta_claim_guest(_zeta_session_guest(request)):
        _zeta_release_guest_name(request)
        _push_chat_access_flash(
            request, "error", "Someone took your name while you were away. Pick a new one."
        )
        return RedirectResponse(url="/zeta", status_code=status.HTTP_303_SEE_OTHER)
    directory = _zeta_directory()
    member = directory.get(viewer_id or "")
    if member and not is_moderator:
        operator_display = member["label"]
    elif member and member["group"] == "guest":
        operator_display = member["name"]
    elif has_chat_access:
        operator_display = _chat_operator_name(user, is_moderator=is_moderator)
    else:
        operator_display = "Unassigned"

    if templates is None:
        return JSONResponse(
            {
                "status": "zeta-chat",
                "brand": BRAND,
                "has_chat_access": has_chat_access,
                "ban_notice": _zeta_ban_notice(ban) if ban else None,
                "flash": chat_flash,
                "operator_name": operator_display,
            }
        )

    return templates.TemplateResponse(
        request,
        "zeta.html",
        {
            "request": request,
            "brand": BRAND,
            "operator_name": operator_display,
            "is_moderator": is_moderator,
            "has_chat_access": has_chat_access,
            "chat_flash": chat_flash,
            "chat_max_length": _ALICE_CHAT_MAX_LENGTH,
            "guest_name_max": _ZETA_GUEST_NAME_MAX,
            "ban_notice": _zeta_ban_notice(ban) if ban else None,
            "vpn_block": vpn_block,
            "ban_durations": [(key, label) for key, (_length, label) in _ZETA_BAN_DURATIONS.items()],
        },
    )


_ZETA_JOIN_LIMITER = _SlidingWindowRateLimiter(limit=5, window_seconds=3600.0)


@app.post("/zeta/join", include_in_schema=False)
async def join_zeta(request: Request):
    """Give the caller a ZETA guest identity under the name they entered."""

    form = await request.form()
    session_guest = request.session.get(_ZETA_GUEST_SESSION_KEY)
    existing_id = str(session_guest.get("id") or "") if isinstance(session_guest, dict) else ""
    ban = _zeta_ban_for(request, existing_id or None)
    refusal = _zeta_ban_notice(ban) if ban else _zeta_vpn_block(request)
    if refusal:
        _push_chat_access_flash(request, "error", refusal)
        return RedirectResponse(url="/zeta", status_code=status.HTTP_303_SEE_OTHER)

    name = _zeta_clean_guest_name(form.get("name"))
    problem = _zeta_guest_name_problem(name) if name else "Enter a name to join Project ZETA."
    if problem:
        _push_chat_access_flash(request, "error", problem)
        return RedirectResponse(url="/zeta", status_code=status.HTTP_303_SEE_OTHER)

    if _ZETA_GUEST_ID_RE.fullmatch(existing_id):
        guest_id = existing_id
    else:
        if _ZETA_JOIN_LIMITER.hit(_client_ip_from_request(request)):
            _push_chat_access_flash(
                request, "error", "Too many new names from this network. Try again later."
            )
            return RedirectResponse(url="/zeta", status_code=status.HTTP_303_SEE_OTHER)
        guest_id = f"zeta{secrets.token_hex(16)}"
    guest = {"id": guest_id, "name": name}
    problem = _zeta_claim_guest(guest, force=True)
    if problem:
        _push_chat_access_flash(request, "error", problem)
        return RedirectResponse(url="/zeta", status_code=status.HTTP_303_SEE_OTHER)
    request.session[_ZETA_GUEST_SESSION_KEY] = guest
    _zeta_note_traces(request, guest_id)
    return RedirectResponse(url="/zeta", status_code=status.HTTP_303_SEE_OTHER)


_ALICE_COMMAND_MAX_LENGTH = 2_000
_ALICE_COMMAND_LIMITER = _SlidingWindowRateLimiter(limit=10, window_seconds=60.0)
# Any Discord account can open the terminal and every command is a paid model
# call, so cap each account and the whole site per day. A run of throwaway
# accounts then hits the site-wide budget (and raises an alert) instead of the bill.
_ALICE_DAILY_PER_ACCOUNT = _SlidingWindowRateLimiter(
    limit=security_shield.env_int("ALICE_DAILY_COMMANDS_PER_USER", 150, minimum=1), window_seconds=86400.0
)
_ALICE_DAILY_SITE_WIDE = _SlidingWindowRateLimiter(
    limit=security_shield.env_int("ALICE_DAILY_COMMANDS_TOTAL", 1500, minimum=1), window_seconds=86400.0
)
_ALICE_BUDGET_ALERTED_AT: float | None = None


@app.post("/api/alice/command")
async def alice_command(
    request: Request,
    payload: dict[str, str] = Body(...),
    _: bool = Depends(require_auth),
):
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Command message is required")
    if len(message) > _ALICE_COMMAND_MAX_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Command message must be {_ALICE_COMMAND_MAX_LENGTH} characters or fewer",
        )

    global _ALICE_BUDGET_ALERTED_AT
    session_user = request.session.get("user") or {}
    caller_key = _clean_discord_id(session_user.get("id")) or f"ip:{_client_ip_from_request(request)}"
    if _ALICE_COMMAND_LIMITER.hit(caller_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many A.L.I.C.E commands. Wait a minute and try again.",
        )
    if _ALICE_DAILY_PER_ACCOUNT.hit(caller_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You've reached today's A.L.I.C.E command limit. Try again tomorrow.",
        )
    if _ALICE_DAILY_SITE_WIDE.hit("site"):
        now = time.monotonic()
        if _ALICE_BUDGET_ALERTED_AT is None or now - _ALICE_BUDGET_ALERTED_AT > 3600:
            _ALICE_BUDGET_ALERTED_AT = now
            SECURITY_SHIELD.report(
                "llm-budget",
                "A.L.I.C.E daily command budget exhausted site-wide; commands are paused. "
                "If this was not expected, someone may be abusing the AI terminal.",
                ip=_client_ip_from_request(request),
                severity="critical",
            )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A.L.I.C.E is at capacity for today. Try again later.",
        )

    try:
        reply = await run_blocking(llm_client.run_assistant, message)
    except Exception as exc:  # pragma: no cover - best-effort logging for live LLM calls
        logger.exception("A.L.I.C.E command failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Failed to process command")

    return JSONResponse({"reply": reply})


@app.post("/zeta/decision", include_in_schema=False)
@app.post("/alice/chat/decision", include_in_schema=False)
async def decide_chat_access(request: Request):
    user, _guilds = await _load_user_context(request)
    if not user:
        return RedirectResponse(url="/login")

    settings, etag = load_owner_settings(with_etag=True)
    actor_id = _clean_discord_id(user.get("id"))
    if not can_manage_chat_access(actor_id, settings.managers):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage chat access.",
        )

    form = await request.form()
    target = validate_discord_id(form.get("user_id"))
    decision = (form.get("decision") or "").strip().lower()
    next_page = _clean_redirect_target(form.get("next")) or "/dashboard"
    status_label = "success"
    message = ""

    if not target:
        status_label = "error"
        message = "A valid Discord user ID is required."
    elif decision not in {"grant", "deny"}:
        status_label = "error"
        message = "Choose grant or deny to continue."
    else:
        updated = settings.copy()
        actor = _format_actor(user)
        if decision == "grant":
            if can_access_chat(target, updated.managers, updated.chat_access):
                message = "That operator already has chat access."
            else:
                updated.chat_access.append(target)
                updated.append_log_entry(
                    build_change_entry(
                        actor,
                        "Chat access granted",
                        f"Approved Project ZETA access for {target}",
                    )
                )
                if save_owner_settings(updated, etag=etag):
                    settings = updated
                    message = "Chat access granted."
                else:
                    status_label = "error"
                    message = "Chat access changed on the server. Refresh and try again."
        else:
            _clear_chat_access_request(target)
            message = "Chat access request denied."

        if status_label == "success":
            _clear_chat_access_request(target)

    if next_page.startswith("/owner"):
        request.session[_OWNER_FLASH_KEY] = {"status": status_label, "message": message}
    elif next_page.startswith("/zeta"):
        _push_chat_access_flash(request, status_label, message)
    else:
        _push_panel_flash(request, status_label, message)

    return RedirectResponse(url=next_page, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/api/alice/chat")
async def alice_chat_log(request: Request, _: bool = Depends(require_chat_access)):
    chat_log, etag = _enforce_chat_retention()
    headers = {"Cache-Control": "no-store"}
    if etag:
        headers["ETag"] = etag

    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    messages = _render_chat_entries(
        chat_log.get("messages", []),
        is_moderator=is_moderator,
        viewer_id=_session_chat_viewer_id(request),
        directory=_zeta_directory(),
    )
    return JSONResponse({"messages": messages}, headers=headers)


@app.post("/api/alice/chat")
async def alice_chat_message(
    request: Request,
    payload: dict[str, str] = Body(...),
    _: bool = Depends(require_chat_access),
):
    message = payload.get("message") or ""
    if message.strip():
        _zeta_enforce_send_limit(_session_chat_viewer_id(request))
        _zeta_note_sender(request)
    entry = _append_chat_message(request=request, message=message)
    chat_log, _ = _load_alice_chat()
    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    viewer_id = _session_chat_viewer_id(request)
    directory = _zeta_directory()
    messages = chat_log.get("messages", [])
    return JSONResponse(
        {
            "message": _render_chat_entry(
                entry, is_moderator=is_moderator, viewer_id=viewer_id, directory=directory
            ),
            "messages": _render_chat_entries(
                messages, is_moderator=is_moderator, viewer_id=viewer_id, directory=directory
            ),
        }
    )


@app.delete("/api/alice/chat/{message_id}")
async def delete_chat_message(
    request: Request,
    message_id: str,
    _: bool = Depends(require_chat_access),
):
    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    viewer_id = _session_chat_viewer_id(request)
    if not is_moderator:
        current, _ = _load_alice_chat()
        target = next(
            (entry for entry in current.get("messages", []) if entry.get("id") == message_id),
            None,
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Message not found")
        if not viewer_id or target.get("user_id") != viewer_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="You can only remove your own messages",
            )

    chat_log = _delete_chat_message(message_id=message_id)
    return JSONResponse(
        {
            "messages": _render_chat_entries(
                chat_log.get("messages", []),
                is_moderator=is_moderator,
                viewer_id=viewer_id,
                directory=_zeta_directory(),
            )
        }
    )


_ZETA_SEND_INTERVAL_SECONDS = 3.0
# One message every three seconds per member, across the channel and every DM.
_ZETA_SEND_LIMITER = _SlidingWindowRateLimiter(limit=1, window_seconds=_ZETA_SEND_INTERVAL_SECONDS)


def _zeta_note_sender(request: Request) -> None:
    """Keep the sender's name on record: Discord members by display name, guests in the registry.

    Called before the message is stored, so a guest whose name was taken cannot post under it.
    """

    guest = _zeta_session_guest(request)
    if guest and guest["id"] == _session_chat_viewer_id(request):
        if _zeta_claim_guest(guest):
            _zeta_release_guest_name(request)
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="Someone took your name while you were away. Join again with a new one.",
            )
    else:
        _zeta_remember_member(request.session.get("user"))


def _zeta_enforce_send_limit(viewer_id: str | None) -> None:
    if viewer_id and _ZETA_SEND_LIMITER.hit(viewer_id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Slow down: one message every 3 seconds.",
            headers={"Retry-After": str(int(_ZETA_SEND_INTERVAL_SECONDS))},
        )


def _zeta_viewer(request: Request) -> tuple[str, bool]:
    viewer_id = _session_chat_viewer_id(request)
    if not viewer_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Enter a name on the Project ZETA page to join.")
    return viewer_id, _session_user_is_admin(request) or _session_user_is_owner(request)


def _zeta_resolve_peer(
    handle: str, *, viewer_id: str, directory: Mapping[str, Mapping[str, str]], is_moderator: bool
) -> tuple[dict[str, str], bool]:
    """Find the member behind ``handle``; return it and whether they are still a member.

    Threads with people who have since lost access stay readable, so the
    viewer's inbox is searched too.
    """

    for member in directory.values():
        if _zeta_handle(member["id"]) == handle:
            return dict(member), True
    for peer_id in zeta_dm.load_inbox(_storage_backend(), viewer_id):
        if _zeta_handle(peer_id) == handle:
            names = _zeta_member_names()
            return _zeta_former_member(peer_id, is_moderator=is_moderator, names=names), False
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Operator not found")


def _zeta_render_dm(
    peer: Mapping[str, str],
    messages: Iterable[Mapping[str, str]],
    *,
    viewer_id: str,
    viewer: Mapping[str, str] | None,
    is_moderator: bool,
    active: bool,
) -> dict[str, Any]:
    peer_public = _zeta_public_member(peer, is_moderator=is_moderator, viewer_id=viewer_id)
    peer_public["active"] = active
    me_label = viewer["label"] if viewer else "You"
    me_initial = viewer["initial"] if viewer else "Y"
    if viewer and is_moderator:
        me_label = viewer["name"]
    rendered = []
    for entry in messages:
        mine = entry["sender_id"] == viewer_id
        rendered.append(
            {
                "id": entry["id"],
                "message": entry["message"],
                "created_at": entry["created_at"],
                "mine": mine,
                "operator": me_label if mine else peer_public["label"],
                "initial": me_initial if mine else peer_public["initial"],
                "handle": "" if mine else peer_public["handle"],
            }
        )
    return {"peer": peer_public, "messages": rendered}


@app.get("/api/zeta/sync")
async def zeta_sync(
    request: Request,
    dm: str | None = None,
    members: bool = False,
    _: bool = Depends(require_chat_access),
):
    """Everything the ZETA page polls for, in one request.

    Returns the channel, the viewer's direct-message threads, and the open
    thread when ``dm`` names one (opening it marks it read). ``members=1``
    adds the member list.
    """

    viewer_id, is_moderator = _zeta_viewer(request)
    settings, _etag = load_owner_settings()
    directory = _zeta_directory(settings)
    backend = _storage_backend()
    chat_log, _chat_etag = _enforce_chat_retention()

    viewer = directory.get(viewer_id)
    payload: dict[str, Any] = {
        "me": _zeta_public_member(viewer, is_moderator=is_moderator, viewer_id=viewer_id)
        if viewer
        else None,
        "channel": _render_chat_entries(
            chat_log.get("messages", []),
            is_moderator=is_moderator,
            viewer_id=viewer_id,
            directory=directory,
        ),
    }

    inbox = zeta_dm.load_inbox(backend, viewer_id)
    if dm:
        peer, active = _zeta_resolve_peer(
            dm, viewer_id=viewer_id, directory=directory, is_moderator=is_moderator
        )
        messages = zeta_dm.load_thread(backend, viewer_id, peer["id"])
        if inbox.get(peer["id"], {}).get("unread"):
            try:
                zeta_dm.mark_read(backend, user_id=viewer_id, peer_id=peer["id"])
                inbox[peer["id"]]["unread"] = 0
            except zeta_dm.DirectMessageConflict:
                pass  # Stays unread until the next poll.
        payload["dm"] = _zeta_render_dm(
            peer, messages, viewer_id=viewer_id, viewer=viewer, is_moderator=is_moderator, active=active
        )

    names: dict[str, str] | None = None
    threads = []
    for peer_id, entry in inbox.items():
        if not entry.get("last_at"):
            continue
        member = directory.get(peer_id)
        if member is None:
            if names is None:
                names = _zeta_member_names()
            member = _zeta_former_member(peer_id, is_moderator=is_moderator, names=names)
        public = _zeta_public_member(member, is_moderator=is_moderator, viewer_id=viewer_id)
        public.update(
            active=peer_id in directory,
            preview=entry["preview"],
            last_at=entry["last_at"],
            last_from_me=entry["last_sender_id"] == viewer_id,
            unread=entry["unread"],
        )
        threads.append(public)
    threads.sort(key=lambda thread: thread["last_at"], reverse=True)
    payload["threads"] = threads
    payload["unread_total"] = sum(thread["unread"] for thread in threads)

    if members:
        payload["members"] = [
            _zeta_public_member(member, is_moderator=is_moderator, viewer_id=viewer_id)
            for member in directory.values()
        ]
        if is_moderator:
            payload["bans"] = [_zeta_public_ban(ban) for ban in _zeta_active_bans()]

    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/zeta/dm/{handle}")
async def zeta_send_direct_message(
    request: Request,
    handle: str,
    payload: dict[str, str] = Body(...),
    _: bool = Depends(require_chat_access),
):
    viewer_id, is_moderator = _zeta_viewer(request)
    directory = _zeta_directory()
    peer, active = _zeta_resolve_peer(
        handle, viewer_id=viewer_id, directory=directory, is_moderator=is_moderator
    )
    if not active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="This operator no longer has Project ZETA access.",
        )
    if peer["id"] == viewer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="You cannot message yourself")
    if str(payload.get("message") or "").strip():
        _zeta_enforce_send_limit(viewer_id)
        _zeta_note_sender(request)

    try:
        _entry, messages = zeta_dm.append_message(
            _storage_backend(),
            sender_id=viewer_id,
            recipient_id=peer["id"],
            message=str(payload.get("message") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except zeta_dm.DirectMessageConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))

    return JSONResponse(
        {
            "dm": _zeta_render_dm(
                peer,
                messages,
                viewer_id=viewer_id,
                viewer=directory.get(viewer_id),
                is_moderator=is_moderator,
                active=active,
            )
        }
    )


@app.delete("/api/zeta/dm/{handle}/{message_id}")
async def zeta_delete_direct_message(
    request: Request,
    handle: str,
    message_id: str,
    _: bool = Depends(require_chat_access),
):
    viewer_id, is_moderator = _zeta_viewer(request)
    directory = _zeta_directory()
    peer, active = _zeta_resolve_peer(
        handle, viewer_id=viewer_id, directory=directory, is_moderator=is_moderator
    )
    try:
        messages = zeta_dm.delete_message(
            _storage_backend(), user_id=viewer_id, peer_id=peer["id"], message_id=message_id
        )
    except zeta_dm.DirectMessageNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    except zeta_dm.DirectMessageConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))

    return JSONResponse(
        {
            "dm": _zeta_render_dm(
                peer,
                messages,
                viewer_id=viewer_id,
                viewer=directory.get(viewer_id),
                is_moderator=is_moderator,
                active=active,
            )
        }
    )


# ---------------------------------------------------------------------------
# Project ZETA bans. A moderator bans a member's ZETA identity together with
# the traces it was recently seen with: IP addresses, the device marker and
# browser fingerprint set by static/js/zeta_device.js, and a signed-in Discord
# account. Any one of them matching keeps the person out, for a set time or
# permanently. IPs, markers and fingerprints are only stored as keyed hashes.
# Guests also cannot use ZETA through a VPN, proxy or Tor (vpn_blocklist), so
# a banned guest cannot simply hop to a new IP. Bans and lifts go to the admin
# console's audit log.
# ---------------------------------------------------------------------------

_ZETA_BANS_KEY = "zeta/bans.json"
_ZETA_TRACES_PREFIX = "zeta/traces"
_ZETA_TRACES_MAX = 5  # per kind, newest kept
_ZETA_TRACE_INTERVAL_SECONDS = 3600.0
_ZETA_DEVICE_COOKIE = "zeta_device"
_ZETA_FINGERPRINT_COOKIE = "zeta_fp"
_ZETA_DEVICE_RE = re.compile(r"^[0-9a-f]{32}$")
_ZETA_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
# Trace kind -> ban field holding it.
_ZETA_TRACE_FIELDS = {
    "ips": "ip_hashes",
    "devices": "device_hashes",
    "fingerprints": "fingerprint_hashes",
    "discord": "discord_ids",
}
_ZETA_BAN_REASON_MAX = 300
_ZETA_BANS_CACHE_SECONDS = 10.0
# Key -> (length, label). ``None`` means permanent.
_ZETA_BAN_DURATIONS: dict[str, tuple[timedelta | None, str]] = {
    "15m": (timedelta(minutes=15), "15 minutes"),
    "1h": (timedelta(hours=1), "1 hour"),
    "6h": (timedelta(hours=6), "6 hours"),
    "24h": (timedelta(hours=24), "24 hours"),
    "3d": (timedelta(days=3), "3 days"),
    "7d": (timedelta(days=7), "7 days"),
    "30d": (timedelta(days=30), "30 days"),
    "permanent": (None, "permanently"),
}
_zeta_bans_cache: tuple[float, list[dict[str, Any]]] | None = None
# (member ID, traces) -> when they were last written, so polling does not rewrite them.
_zeta_traces_written: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def _zeta_trace_hash(kind: str, value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned.lower() == "unknown":
        return None
    key = f"zeta-{kind}:{SESSION_SECRET}".encode("utf-8")
    return hmac.new(key, cleaned.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _zeta_request_traces(request: Request) -> dict[str, str]:
    """This request's ban-relevant traces, by kind (only those present)."""

    traces: dict[str, str] = {}
    ip_hash = _zeta_trace_hash("ip", _client_ip_from_request(request))
    if ip_hash:
        traces["ips"] = ip_hash
    device = str(request.cookies.get(_ZETA_DEVICE_COOKIE) or "")
    if _ZETA_DEVICE_RE.fullmatch(device):
        traces["devices"] = _zeta_trace_hash("device", device)
    fingerprint = str(request.cookies.get(_ZETA_FINGERPRINT_COOKIE) or "")
    if _ZETA_FINGERPRINT_RE.fullmatch(fingerprint):
        traces["fingerprints"] = _zeta_trace_hash("fingerprint", fingerprint)
    user = request.session.get("user") if isinstance(request.session, dict) else None
    discord_id = _clean_discord_id((user or {}).get("id"))
    if discord_id:
        traces["discord"] = discord_id
    return traces


def _zeta_note_traces(request: Request, member_id: str) -> None:
    """Remember which traces ``member_id`` was seen with, so a ban can cover them."""

    traces = _zeta_request_traces(request)
    if not traces:
        return
    signature = (member_id, tuple(sorted(traces.items())))
    now = time.monotonic()
    written = _zeta_traces_written.get(signature)
    if written is not None and now - written < _ZETA_TRACE_INTERVAL_SECONDS:
        return
    if len(_zeta_traces_written) > 10_000:
        _zeta_traces_written.clear()
    key = f"{_ZETA_TRACES_PREFIX}/{member_id}.json"
    seen_at = datetime.now(timezone.utc).isoformat()
    backend = _storage_backend()
    for _attempt in range(3):
        try:
            payload, etag = backend.read_json(key, with_etag=True)
        except FileNotFoundError:
            payload, etag = {}, None
        document: dict[str, dict[str, str]] = {}
        for kind in _ZETA_TRACE_FIELDS:
            seen = dict((payload or {}).get(kind) or {})
            if kind in traces:
                seen[traces[kind]] = seen_at
            newest = sorted(seen.items(), key=lambda item: str(item[1]), reverse=True)[:_ZETA_TRACES_MAX]
            if newest:
                document[kind] = dict(newest)
        if backend.write_json(key, document, etag=etag):
            _zeta_traces_written[signature] = now
            return


def _zeta_member_traces(member_id: str) -> dict[str, list[str]]:
    try:
        payload = _storage_backend().read_json(f"{_ZETA_TRACES_PREFIX}/{member_id}.json")
    except FileNotFoundError:
        payload = {}
    return {kind: [str(value) for value in ((payload or {}).get(kind) or {})] for kind in _ZETA_TRACE_FIELDS}


def _zeta_ban_active(ban: Mapping[str, Any], now: datetime) -> bool:
    expires_at = ban.get("expires_at")
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(str(expires_at)) > now
    except ValueError:
        return False


def _zeta_read_bans() -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload, etag = _storage_backend().read_json(_ZETA_BANS_KEY, with_etag=True)
    except FileNotFoundError:
        return [], None
    bans = (payload or {}).get("bans") if isinstance(payload, dict) else None
    return [dict(ban) for ban in (bans or []) if isinstance(ban, dict) and ban.get("id")], etag


def _zeta_active_bans() -> list[dict[str, Any]]:
    """Bans in force now, re-read at most every few seconds."""

    global _zeta_bans_cache
    cached = _zeta_bans_cache
    if cached is None or time.monotonic() - cached[0] > _ZETA_BANS_CACHE_SECONDS:
        bans, _etag = _zeta_read_bans()
        cached = (time.monotonic(), bans)
        _zeta_bans_cache = cached
    now = datetime.now(timezone.utc)
    return [ban for ban in cached[1] if _zeta_ban_active(ban, now)]


def _zeta_update_bans(change) -> None:
    """Apply ``change`` to the ban list (dropping expired bans) and save it."""

    global _zeta_bans_cache
    backend = _storage_backend()
    for _attempt in range(3):
        bans, etag = _zeta_read_bans()
        now = datetime.now(timezone.utc)
        bans = change([ban for ban in bans if _zeta_ban_active(ban, now)])
        if backend.write_json(_ZETA_BANS_KEY, {"bans": bans}, etag=etag):
            _zeta_bans_cache = None
            return
    raise HTTPException(status.HTTP_409_CONFLICT, detail="The ban list changed while saving. Try again.")


def _zeta_banned_ids() -> set[str]:
    return {str(ban.get("member_id")) for ban in _zeta_active_bans() if ban.get("member_id")}


def _zeta_ban_for(request: Request, member_id: str | None) -> dict[str, Any] | None:
    """The ban keeping this caller out of ZETA, matched by identity or any trace. Moderators are never banned."""

    if _session_user_is_admin(request) or _session_user_is_owner(request):
        return None
    traces = _zeta_request_traces(request)
    for ban in _zeta_active_bans():
        if member_id and ban.get("member_id") == member_id:
            return ban
        for kind, value in traces.items():
            if value in (ban.get(_ZETA_TRACE_FIELDS[kind]) or []):
                return ban
    return None


_ZETA_VPN_LABELS = {"tor": "Tor", "vpn": "a VPN", "datacenter": "a VPN, proxy or hosting network"}


def _zeta_vpn_block(request: Request) -> str | None:
    """Why this guest may not use ZETA from their network, or ``None``.

    Moderators and anyone signed in with Discord are exempt: a Discord account
    is far harder to replace than an IP, so it is the way in for people who
    need a VPN.
    """

    if not _ZETA_VPN_BLOCK_ENABLED:
        return None
    if _session_user_is_admin(request) or _session_user_is_owner(request):
        return None
    user = request.session.get("user") if isinstance(request.session, dict) else None
    if _clean_discord_id((user or {}).get("id")):
        return None
    kind = vpn_blocklist.classify(_client_ip_from_request(request))
    if kind is None:
        return None
    return (
        f"Guests can't use Project ZETA through {_ZETA_VPN_LABELS[kind]}. "
        "Turn it off, or sign in with Discord to use ZETA from this network."
    )


def _zeta_ban_notice(ban: Mapping[str, Any]) -> str:
    expires_at = ban.get("expires_at")
    if not expires_at:
        notice = "You are permanently banned from Project ZETA."
    else:
        until = datetime.fromisoformat(str(expires_at)).astimezone(timezone.utc)
        notice = f"You are banned from Project ZETA until {until:%d %b %Y, %H:%M} UTC."
    reason = str(ban.get("reason") or "").strip()
    return f"{notice} Reason: {reason}" if reason else notice


def _zeta_public_ban(ban: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ban["id"],
        "label": ban.get("name") or "Unknown",
        "reason": ban.get("reason") or "",
        "duration": ban.get("duration_label") or "",
        "created_at": ban.get("created_at") or "",
        "expires_at": ban.get("expires_at"),
        "banned_by": (ban.get("actor") or {}).get("name") or "",
    }


def _zeta_require_moderator(request: Request) -> tuple[str, dict[str, Any]]:
    viewer_id, is_moderator = _zeta_viewer(request)
    if not is_moderator:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only moderators can manage Project ZETA bans.")
    return viewer_id, _moderation_actor(request.session.get("user") or {})


async def _zeta_audit(event_type: str, actor: dict[str, Any], metadata: dict[str, Any]) -> None:
    try:
        await get_moderation_service().record_audit(
            event_type=event_type, source="zeta", actor=actor, metadata=metadata
        )
    except Exception:  # pragma: no cover - the ban itself is already saved
        logger.exception("Could not record %s in the audit log", event_type)


@app.post("/api/zeta/bans")
async def zeta_ban_member(
    request: Request,
    payload: dict[str, Any] = Body(...),
    _: bool = Depends(require_chat_access),
):
    viewer_id, actor = _zeta_require_moderator(request)
    duration_key = str(payload.get("duration") or "")
    if duration_key not in _ZETA_BAN_DURATIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Choose how long the ban lasts.")
    length, duration_label = _ZETA_BAN_DURATIONS[duration_key]
    reason = " ".join(str(payload.get("reason") or "").split())[:_ZETA_BAN_REASON_MAX]

    directory = _zeta_directory()
    handle = str(payload.get("handle") or "")
    member = next((m for m in directory.values() if _zeta_handle(m["id"]) == handle), None)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Operator not found")
    if member["id"] == viewer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="You cannot ban yourself.")
    if member["group"] == "command" or is_owner(member["id"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Command members cannot be banned.")

    now = datetime.now(timezone.utc)
    traces = _zeta_member_traces(member["id"])
    if member["id"].isdigit() and member["id"] not in traces["discord"]:
        traces["discord"].append(member["id"])
    ban = {
        "id": secrets.token_hex(8),
        "member_id": member["id"],
        "name": member["name"],
        "group": member["group"],
        **{field: traces[kind] for kind, field in _ZETA_TRACE_FIELDS.items()},
        "reason": reason,
        "duration_label": duration_label,
        "created_at": now.isoformat(),
        "expires_at": (now + length).isoformat() if length else None,
        "actor": actor,
    }
    # A new ban for the same member replaces the old one.
    _zeta_update_bans(lambda bans: [b for b in bans if b.get("member_id") != member["id"]] + [ban])
    await _zeta_audit(
        "zeta.banned",
        actor,
        {
            "zetaMember": member["name"],
            "zetaGroup": member["group"],
            "duration": duration_label,
            "expiresAt": ban["expires_at"],
            "reason": reason,
            "ipCount": len(ban["ip_hashes"]),
            "deviceCount": len(ban["device_hashes"]),
            "fingerprintCount": len(ban["fingerprint_hashes"]),
            "discordCount": len(ban["discord_ids"]),
            "banId": ban["id"],
        },
    )
    return JSONResponse({"bans": [_zeta_public_ban(b) for b in _zeta_active_bans()]})


@app.delete("/api/zeta/bans/{ban_id}")
async def zeta_lift_ban(request: Request, ban_id: str, _: bool = Depends(require_chat_access)):
    _viewer_id, actor = _zeta_require_moderator(request)
    lifted: list[dict[str, Any]] = []

    def _lift(bans):
        lifted.extend(b for b in bans if b.get("id") == ban_id)
        return [b for b in bans if b.get("id") != ban_id]

    _zeta_update_bans(_lift)
    if not lifted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That ban has already ended.")
    await _zeta_audit(
        "zeta.unbanned",
        actor,
        {
            "zetaMember": lifted[0].get("name") or "Unknown",
            "zetaGroup": lifted[0].get("group") or "",
            "banId": ban_id,
        },
    )
    return JSONResponse({"bans": [_zeta_public_ban(b) for b in _zeta_active_bans()]})


# ---------------------------------------------------------------------------
# Site-wide ping: every page polls for the newest unread direct message.
# ---------------------------------------------------------------------------


def _zeta_ping_enabled(request: Request) -> bool:
    """Whether this page should load the DM ping (anyone with a ZETA identity, away from ZETA itself)."""

    try:
        if request.url.path.startswith("/zeta"):
            return False
        return _session_chat_viewer_id(request) is not None
    except Exception:  # pragma: no cover - never break a page over the ping
        return False


@app.post("/api/zeta/ping")
async def zeta_ping(request: Request):
    """Claim the newest direct message the caller has not been pinged about, if any."""

    viewer_id = _session_chat_viewer_id(request)
    if not viewer_id or _zeta_ban_for(request, viewer_id) or _zeta_vpn_block(request):
        return JSONResponse({"ping": None}, headers={"Cache-Control": "no-store"})
    backend = _storage_backend()
    claimed = zeta_dm.claim_ping(backend, viewer_id)
    if claimed is None:
        return JSONResponse({"ping": None}, headers={"Cache-Control": "no-store"})

    peer_id, entry = claimed
    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    peer = _zeta_directory().get(peer_id) or _zeta_former_member(
        peer_id, is_moderator=is_moderator, names=_zeta_member_names()
    )
    public = _zeta_public_member(peer, is_moderator=is_moderator, viewer_id=viewer_id)
    unread_total = sum(thread["unread"] for thread in zeta_dm.load_inbox(backend, viewer_id).values())
    return JSONResponse(
        {
            "ping": {
                "from": public["label"],
                "initial": public["initial"],
                "preview": entry["preview"],
                "url": f"/zeta#dm-{public['handle']}",
                "unread_total": unread_total,
            }
        },
        headers={"Cache-Control": "no-store"},
    )


_ZETA_PURGE_TASK: asyncio.Task | None = None
_ZETA_BLOCKLIST_TASK: asyncio.Task | None = None


async def _zeta_blocklist_loop() -> None:
    """Load the cached VPN/Tor lists, then download fresh ones once a day."""

    backend = _storage_backend()
    try:
        fetched_at = await run_blocking(vpn_blocklist.load_cached, backend)
    except Exception:  # pragma: no cover - a bad cache just means downloading now
        logger.warning("Could not read the cached VPN blocklists", exc_info=True)
        fetched_at = None
    if fetched_at is not None:
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        await asyncio.sleep(max(0.0, vpn_blocklist.REFRESH_SECONDS - age))
    async with httpx.AsyncClient(follow_redirects=True) as client:
        while True:
            ok = await vpn_blocklist.refresh(backend, client)
            # Retry a failed download within the hour instead of waiting a day.
            await asyncio.sleep(vpn_blocklist.REFRESH_SECONDS if ok else 3600)


async def _zeta_purge_loop() -> None:
    while True:
        try:
            await run_blocking(_enforce_chat_retention)
        except Exception:  # pragma: no cover - storage hiccups retry on the next sweep
            logger.warning("Project ZETA channel purge failed", exc_info=True)
        await asyncio.sleep(_ZETA_PURGE_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_zeta_purge() -> None:
    global _ZETA_PURGE_TASK, _ZETA_BLOCKLIST_TASK
    _ZETA_PURGE_TASK = asyncio.get_running_loop().create_task(_zeta_purge_loop())
    if _ZETA_VPN_BLOCK_ENABLED:
        _ZETA_BLOCKLIST_TASK = asyncio.get_running_loop().create_task(_zeta_blocklist_loop())


@app.on_event("shutdown")
async def _stop_zeta_purge() -> None:
    for task in (_ZETA_PURGE_TASK, _ZETA_BLOCKLIST_TASK):
        if task is not None:
            task.cancel()


@app.get("/api/hd2/summary")
async def hd2_summary(_: bool = Depends(require_auth)):
    payload, error = await _collect_hd2_summary()
    if error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=error)
    return JSONResponse(payload)


@app.get("/helldivers", include_in_schema=False)
async def helldivers_page(request: Request):
    if templates is None:
        manifest = _definition_manifest()
        return JSONResponse(
            {
                "status": "under_construction",
                "brand_image_url": _brand_image_url(manifest),
            }
        )

    definition_manifest = _definition_manifest()
    context = {
        "request": request,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_initials": _brand_initials(BRAND),
        "brand_image_url": _brand_image_url(definition_manifest),
        "build": BUILD,
    }

    can_view_intel = _session_user_is_admin(request) or _session_user_is_owner(request)
    if not can_view_intel:
        return templates.TemplateResponse(
            request,
            "helldivers_placeholder.html",
            _inject_wallpaper(context, "helldivers-placeholder"),
        )

    summary, summary_error = await _collect_hd2_summary()
    context.update({"summary": summary, "summary_error": summary_error})
    return templates.TemplateResponse(
        request,
        "helldivers.html",
        _inject_wallpaper(context, "helldivers"),
    )


@app.get("/operations/pyro-war", include_in_schema=False)
async def pyro_war_page(request: Request):
    if templates is None:
        return JSONResponse({"image": "/images/pyro-map.svg"})

    state = load_pyro_war_state()
    war_status = str(state.get("war_status") or "active").strip().lower()
    if war_status not in _WAR_STATUS_VALUES:
        war_status = "active"

    is_admin_viewer = _session_user_is_admin(request) or _session_user_is_owner(request)
    if war_status == "peace":
        if is_admin_viewer:
            return RedirectResponse(
                url="/admin/war-manager", status_code=status.HTTP_303_SEE_OTHER
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if war_status in {"victory", "retreat"} and not is_admin_viewer:
        target = "/operations/pyro-war/victory" if war_status == "victory" else "/operations/pyro-war/retreat"
        return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)

    war_outcome_notice = _war_outcome_copy(state, war_status) if war_status != "active" else ""

    manifest, _ = load_fleet_manifest()
    fleet_roster = [
        {
            "id": vessel.vessel_id,
            "name": vessel.name,
            "type": vessel.vessel_type,
            "assignment": vessel.assignment,
            "squadron": vessel.assigned_squadron,
            "status": vessel.status,
        }
        for vessel in manifest.vessels
    ]
    context = {
        "request": request,
        "brand": BRAND,
        "system_bodies": PYRO_SYSTEM_BODIES,
        "sectors": PYRO_WAR_SECTORS,
        "orbital_layout": PYRO_WAR_ORBITAL_LAYOUT,
        "battle_readiness": state.get("battle_readiness", {}),
        "attack_focus": state.get("attack_focus", ""),
        "state_labels": PYRO_WAR_STATE_LABELS,
        "fleet_assignments": state.get("fleet_assignments", {}),
        "fleet_vessels": fleet_roster,
        "war_status": war_status,
        "war_outcome_message": state.get("war_outcome_message", ""),
        "war_outcome_notice": war_outcome_notice,
        "is_admin_viewer": is_admin_viewer,
        "wasp_music_tracks": _list_uploaded_wasp_tracks(newest_first=False),
    }
    return templates.TemplateResponse(
        request,
        "pyro_war.html",
        _inject_wallpaper(context, "pyro-war"),
    )


@app.get("/operations/pyro-war/victory", include_in_schema=False)
async def pyro_war_victory(request: Request):
    return _render_war_outcome_page(request, "victory")


@app.get("/operations/pyro-war/retreat", include_in_schema=False)
async def pyro_war_retreat(request: Request):
    return _render_war_outcome_page(request, "retreat")


@app.get("/admin/pyro-war", include_in_schema=False)
async def pyro_war_admin(request: Request, _: bool = Depends(require_portal_admin)):
    context = _build_pyro_war_admin_context(request)

    if templates is None:
        return JSONResponse(_serialize_war_context(context))

    return templates.TemplateResponse(
        request,
        "pyro_war_admin.html",
        _inject_wallpaper(context, "pyro-war-admin"),
    )


@app.post("/admin/pyro-war", include_in_schema=False)
async def update_pyro_war_admin(
    request: Request, _: bool = Depends(require_portal_admin)
):
    return await _update_war_state(request, redirect_url="/admin/pyro-war")


@app.get("/admin/war-manager", include_in_schema=False)
async def war_manager(request: Request, _: bool = Depends(require_portal_admin)):
    context = _build_pyro_war_admin_context(request)
    context.update(
        {
            "page_title": "War Manager",
            "page_description": (
                "Set battle states, station ships, and broadcast the latest orders for the war map. "
                "Changes take effect immediately on the public view."
            ),
            "form_action": "/admin/war-manager",
        }
    )

    if templates is None:
        return JSONResponse(_serialize_war_context(context))

    return templates.TemplateResponse(
        request,
        "war_manager.html",
        _inject_wallpaper(context, "war-manager"),
    )


@app.post("/admin/war-manager", include_in_schema=False)
async def update_war_manager(request: Request, _: bool = Depends(require_portal_admin)):
    return await _update_war_state(request, redirect_url="/admin/war-manager")


def _build_pyro_war_admin_context(request: Request) -> dict[str, object]:
    state, etag = load_pyro_war_state(with_etag=True)
    panel_flash = _render_panel_flash_block(_pop_panel_flash(request))
    bodies = pyro_war_body_listing(include_primary=False)
    manifest, _ = load_fleet_manifest()

    context: dict[str, object] = {
        "request": request,
        "brand": BRAND,
        "accent": ACCENT,
        "state": state,
        "etag": etag,
        "bodies": bodies,
        "state_options": PYRO_WAR_STATE_CHOICES,
        "war_status_options": PYRO_WAR_STATUS_CHOICES,
        "panel_flash": panel_flash,
        "fleet_vessels": manifest.vessels,
    }
    return context


def _serialize_war_context(context: dict[str, object]) -> dict[str, object]:
    payload = dict(context)
    payload.pop("request", None)
    fleet_vessels = payload.get("fleet_vessels") or []
    payload["fleet_vessels"] = [
        vessel.to_payload() if hasattr(vessel, "to_payload") else vessel
        for vessel in fleet_vessels
    ]
    return payload


async def _update_war_state(request: Request, *, redirect_url: str) -> Response:
    form = await request.form()
    etag = str(form.get("etag") or "").strip() or None
    battle_readiness: dict[str, str] = {}
    fleet_assignments: dict[str, list[str]] = {}
    for body in pyro_war_body_listing(include_primary=False):
        body_id = body.get("id")
        if body_id:
            battle_readiness[body_id] = str(form.get(body_id) or "")
            assignments = form.getlist(f"assignments-{body_id}")
            cleaned = [entry.strip() for entry in assignments if entry and entry.strip()]
            if cleaned:
                fleet_assignments[body_id] = cleaned
    attack_focus = form.get("attack_focus")
    war_status = form.get("war_status")
    war_outcome_message = form.get("war_outcome_message")

    try:
        saved = save_pyro_war_state(
            battle_readiness,
            attack_focus,
            fleet_assignments,
            war_status,
            war_outcome_message,
            etag=etag,
        )
    except Exception:
        logger.exception("Failed to persist Pyro war map changes")
        saved = False

    if not saved:
        _push_panel_flash(
            request,
            "error",
            "Pyro war map changed elsewhere. Refresh and try again.",
        )
    else:
        _push_panel_flash(request, "success", "Pyro war map updated.")

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


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
    return "Awaiting FDD tech specs."


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


@app.get("/fdd/tech-specs", include_in_schema=False)
async def fdd_tech_specs(request: Request):
    ships = list(get_fdd_ships())
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
            payload["image_url"] = f"/fdd/tech-specs/images/{slug}{query}"
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
    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)

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
                "brand_image_url": brand_image_url,
                "ships": viewer_ships,
                "manifest": manifest_payload,
                "registered_vessel_count": manifest_count,
            }
        )

    context = {
        "request": request,
        "accent": ACCENT,
        "brand": BRAND,
        "brand_image_url": brand_image_url,
        "brand_initials": _brand_initials(BRAND),
        "ships": viewer_ships,
        "initial_ship": viewer_ships[0] if viewer_ships else None,
        "manifest_last_updated": manifest_payload["last_updated"],
        "registered_vessel_count": manifest_count,
    }
    return templates.TemplateResponse(
        request,
        "fdd_specs.html",
        _inject_wallpaper(context, "fdd-tech-specs"),
    )


@app.get("/fdd/tech-specs/images/{slug}", include_in_schema=False)
async def fdd_tech_spec_image(slug: str):
    ship = get_ship_by_slug(slug)
    if ship is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ship not found")
    try:
        data, content_type = get_ship_image_bytes(slug)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    headers = {"Cache-Control": "public, max-age=3600"}
    return Response(content=data, media_type=content_type, headers=headers)


@app.post("/fdd/tech-specs/upload", include_in_schema=False)
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
    for ship in get_fdd_ships():
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
        format_hint = _join_with_or(_TECH_SPEC_IMAGE_LABELS) or "supported"
        message = f"Attach a {format_hint} image to continue."
    else:
        file_bytes = await upload_file.read()

        if not file_bytes:
            status_label = "error"
            message = "The uploaded file was empty."
        elif len(file_bytes) > _MAX_TECH_SPEC_IMAGE_BYTES:
            status_label = "error"
            message = "Images must be 5 MB or smaller."
        else:
            detected = detect_image_format(file_bytes)
            if detected is None:
                status_label = "error"
                format_hint = _join_with_or(_TECH_SPEC_IMAGE_LABELS) or "supported"
                message = f"Upload a {format_hint} image."
            else:
                extension, content_type = detected
                save_ship_image(
                    slug,
                    file_bytes,
                    content_type=content_type,
                    extension=extension,
                )
                vessel_name = ships.get(slug) or slug
                message = f"{vessel_name} tech spec updated."

    if upload_file is not None:
        await upload_file.close()

    request.session[_FLEET_FLASH_KEY] = {"status": status_label, "message": message}
    return RedirectResponse(url="/fleet", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/fdd/tech-specs/spec", include_in_schema=False)
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
            save_fdd_ship_spec(payload)
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
    await _require_guild_session_access(request, guild_id)
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
    access_sequence_clean = _normalise_access_sequence_settings(archive_copy.get("access_sequence"))
    if access_sequence_clean:
        archive_copy["access_sequence"] = access_sequence_clean
    else:
        archive_copy.pop("access_sequence", None)
    protocols_clean = _normalise_protocol_settings(copied_settings.get("protocols"))
    if protocols_clean:
        copied_settings["protocols"] = protocols_clean
    else:
        copied_settings.pop("protocols", None)
    admin_clean = _normalise_admin_settings(copied_settings.get("admin"))
    if admin_clean:
        copied_settings["admin"] = admin_clean
    else:
        copied_settings.pop("admin", None)
    mission_reports_clean = _normalise_mission_reports_settings(
        copied_settings.get("mission_reports")
    )
    if mission_reports_clean:
        copied_settings["mission_reports"] = mission_reports_clean
    else:
        copied_settings.pop("mission_reports", None)
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
    await _require_guild_session_access(request, guild_id)
    payload = await request.json()

    try:
        gid_int = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid guild ID.") from exc

    current, etag = read_json(guild_key(guild_id), with_etag=True)
    current_settings = current.get("settings") if isinstance(current, Mapping) else None

    settings = payload.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        payload["settings"] = settings

    if "clearance" not in settings:
        existing_clearance = None
        if isinstance(current_settings, Mapping):
            existing_clearance = current_settings.get("clearance")
        if not isinstance(existing_clearance, Mapping) and isinstance(current, Mapping):
            existing_clearance = current.get("clearance")
        if isinstance(existing_clearance, Mapping):
            settings["clearance"] = dict(existing_clearance)
            payload["clearance"] = settings["clearance"]

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
    access_sequence_clean = _normalise_access_sequence_settings(archive_cfg.get("access_sequence"))
    if access_sequence_clean:
        archive_cfg["access_sequence"] = access_sequence_clean
    else:
        archive_cfg.pop("access_sequence", None)

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

    # Preserve previously stored clearance levels when the dashboard payload
    # does not include any. This avoids unintentionally resetting all level
    # mappings when a non-clearance setting is changed.
    existing_levels_raw: Mapping[str, Any] | None = None
    if isinstance(current_settings, Mapping):
        existing_clearance = current_settings.get("clearance")
        if isinstance(existing_clearance, Mapping):
            existing_levels_raw = existing_clearance.get("levels")  # type: ignore[assignment]
    if not isinstance(existing_levels_raw, Mapping) and isinstance(current, Mapping):
        legacy_clearance = current.get("clearance")
        if isinstance(legacy_clearance, Mapping):
            existing_levels_raw = legacy_clearance.get("levels")  # type: ignore[assignment]

    merged_levels: dict[str, dict[str, Any]] = {}
    if isinstance(existing_levels_raw, Mapping):
        for level_key, entry in existing_levels_raw.items():
            if not isinstance(entry, Mapping):
                continue
            try:
                level_int = int(level_key)
            except (TypeError, ValueError):
                continue
            if level_int < 1 or level_int > 6:
                continue
            merged_levels[str(level_int)] = dict(entry)

    # When the dashboard sends explicit level mappings, overlay them on top of
    # any existing ones. If it sends none (e.g. due to a UI bug), we keep the
    # previously stored levels instead of clearing them.
    # Never accept a payload that would reduce the number of configured levels.
    if cleaned_levels:
        if len(cleaned_levels) < len(merged_levels):
            logger.warning(
                "Rejecting clearance payload for guild %s: would reduce levels from %d to %d. Preserving existing.",
                guild_id,
                len(merged_levels),
                len(cleaned_levels),
            )
        else:
            merged_levels.update(cleaned_levels)
    elif merged_levels:
        logger.info(
            "Preserving existing clearance levels for guild %s (payload missing/empty levels).",
            guild_id,
        )

    # Store role IDs as strings so JavaScript JSON.parse() cannot silently
    # corrupt them through floating-point precision loss (Discord snowflakes
    # exceed Number.MAX_SAFE_INTEGER).
    for _entry in merged_levels.values():
        if isinstance(_entry.get("roles"), list):
            _entry["roles"] = [str(r) for r in _entry["roles"]]

    if merged_levels:
        clearance_cfg["levels"] = merged_levels
    else:
        clearance_cfg.pop("levels", None)

    if "strict_levels" in clearance_cfg:
        clearance_cfg["strict_levels"] = clearance_cfg["strict_levels"] is True

    if clearance_cfg:
        settings["clearance"] = clearance_cfg
        payload["clearance"] = clearance_cfg
    else:
        settings.pop("clearance", None)
        payload.pop("clearance", None)

    protocols_clean = _normalise_protocol_settings(settings.get("protocols"))
    if protocols_clean:
        settings["protocols"] = protocols_clean
        payload["protocols"] = protocols_clean
    else:
        settings.pop("protocols", None)
        payload.pop("protocols", None)

    admin_clean = _normalise_admin_settings(settings.get("admin"))
    if admin_clean:
        settings["admin"] = admin_clean
        payload["admin"] = admin_clean
    else:
        settings.pop("admin", None)
        payload.pop("admin", None)

    mission_reports_clean = _normalise_mission_reports_settings(settings.get("mission_reports"))
    if mission_reports_clean:
        settings["mission_reports"] = mission_reports_clean
        payload["mission_reports"] = mission_reports_clean
    else:
        settings.pop("mission_reports", None)
        payload.pop("mission_reports", None)

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
    await _require_guild_session_access(request, guild_id)

    try:
        gid_int = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid guild ID.") from exc

    doc, _etag = read_json(guild_key(guild_id), with_etag=True)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No configuration stored for this server yet.")

    try:
        queue_payload = _build_deploy_queue_payload(
            doc, trigger="manual_dashboard_deploy", deploy_target="all"
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Configure a menu channel before deploying."
        ) from exc

    menu_channel = queue_payload["menu_channel_id"]
    try:
        save_json(f"deploy-queue/{gid_int}.json", queue_payload)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to enqueue manual menu deployment for guild %s", guild_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Unable to queue deployment. Try again later.",
        ) from exc

    local_trigger: dict[str, Any] = {
        "deploy_target": queue_payload.get("deploy_target", "all"),
        "menu_channel_id": menu_channel,
    }
    mr_channel = queue_payload.get("mission_reports_menu_channel_id")
    if mr_channel is not None:
        local_trigger["mission_reports_menu_channel_id"] = mr_channel

    try:
        request_deploy(gid_int, reason="dashboard", **local_trigger)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to queue local deploy trigger for guild %s", guild_id)

    return JSONResponse({
        "ok": True,
        "queued_at": queue_payload["queued_at"],
        "menu_channel_id": menu_channel,
        "deploy_target": queue_payload.get("deploy_target", "all"),
        "mission_reports_menu_channel_id": mr_channel,
    })


def _extract_mission_reports_menu_channel(doc: Any) -> int | None:
    if not isinstance(doc, Mapping):
        return None
    settings = doc.get("settings")
    if not isinstance(settings, Mapping):
        return None
    mr = settings.get("mission_reports")
    if not isinstance(mr, Mapping):
        return None
    return _coerce_channel_id(mr.get("menu_channel"))


def _mission_reports_enabled(doc: Any) -> bool:
    if not isinstance(doc, Mapping):
        return False
    settings = doc.get("settings")
    if not isinstance(settings, Mapping):
        return False
    mr = settings.get("mission_reports")
    return isinstance(mr, Mapping) and bool(mr.get("enabled"))


def _build_deploy_queue_payload(
    doc: Mapping[str, Any],
    *,
    trigger: str,
    deploy_target: str = "all",
) -> dict[str, Any]:
    """Build a deploy-queue payload for archive and optional mission report menus."""

    menu_channel = _extract_menu_channel(doc)
    if menu_channel is None:
        raise ValueError("menu channel required")

    payload: dict[str, Any] = {
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "menu_channel_id": menu_channel,
        "deploy_target": deploy_target,
        "trigger": trigger,
    }
    if _mission_reports_enabled(doc):
        mr_channel = _extract_mission_reports_menu_channel(doc)
        if mr_channel is not None:
            payload["mission_reports_menu_channel_id"] = mr_channel
    return payload


@app.post("/configs/{guild_id}/deploy-mission-reports")
async def request_mission_reports_deploy(
    guild_id: str, request: Request, _: bool = Depends(require_auth)
):
    await _require_guild_session_access(request, guild_id)

    try:
        gid_int = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid guild ID.") from exc

    doc, _etag = read_json(guild_key(guild_id), with_etag=True)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No configuration stored for this server yet.")

    settings = doc.get("settings") if isinstance(doc, Mapping) else None
    mr_cfg = settings.get("mission_reports") if isinstance(settings, Mapping) else None
    if not isinstance(mr_cfg, Mapping) or not mr_cfg.get("enabled"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Enable mission reports and save before deploying.",
        )

    menu_channel = _extract_mission_reports_menu_channel(doc)
    if menu_channel is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Configure a mission reports menu channel before deploying.",
        )

    queue_payload = {
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "mission_reports_menu_channel_id": menu_channel,
        "deploy_target": "mission_reports",
        "trigger": "manual_dashboard_mission_reports_deploy",
    }
    try:
        save_json(f"deploy-queue/{gid_int}.json", queue_payload)
    except Exception as exc:
        logger.exception("Failed to enqueue mission reports deploy for guild %s", guild_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Unable to queue deployment. Try again later.",
        ) from exc

    try:
        request_deploy(
            gid_int,
            reason="dashboard_mission_reports",
            deploy_target="mission_reports",
            mission_reports_menu_channel_id=menu_channel,
        )
    except Exception:
        logger.exception("Failed to queue local mission reports deploy for guild %s", guild_id)

    return JSONResponse({
        "ok": True,
        "queued_at": queue_payload["queued_at"],
        "mission_reports_menu_channel_id": menu_channel,
    })


@app.delete("/configs/{guild_id}")
async def delete_guild_config(guild_id: str, request: Request, _: bool = Depends(require_auth)):
    await _require_guild_session_access(request, guild_id)

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
