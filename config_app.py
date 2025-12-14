import os
import json
import logging
import secrets
from secrets import compare_digest
import asyncio
from urllib.parse import parse_qs, urlparse, quote
import html
import base64
import binascii
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections.abc import Iterable, Mapping
from typing import Any, Callable, Mapping

import httpx
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    Depends,
    status,
    Body,
    UploadFile as FastAPIUploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import psutil

import llm_client
from async_utils import run_blocking
import importlib
import storage_spaces
from storage_spaces import read_json, write_json, backup_json, list_dir, delete_file, save_json, save_text
from utils.guild_store import request_deploy
from constants import ROOT_PREFIX
from config import (
    get_site_lock_state,
    get_system_health_state,
    set_site_lock_state,
    set_system_health_state,
    SITE_LOCK_MESSAGE_DEFAULT,
    SYSTEM_HEALTH_STATUSES,
)
from operator_login import list_operators
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
from admin_roster import AdminBio, load_admin_bios, save_admin_bio, normalise_bio_text
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
import psutil

logger = logging.getLogger("config_app")
logger.setLevel(logging.INFO)

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
_ALICE_PRIVATE_MESSAGE_RECIPIENT = (
    os.getenv("ALICE_PRIVATE_MESSAGE_RECIPIENT_ID")
    or os.getenv("ALICE_DM_RECIPIENT_ID")
    or OWNER_USER_KEY
)
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

app = FastAPI()
auth = HTTPBasic(auto_error=False)
try:
    templates = Jinja2Templates(directory="templates")
except AssertionError:
    templates = None

if os.path.isdir("images"):
    app.mount("/images", StaticFiles(directory="images"), name="images")
else:
    logger.warning("images directory is missing; /images assets will not be served.")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logger.warning("static directory is missing; onboarding assets will not be served.")

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

_MAINTENANCE_BYPASS_PATHS = {"/login", "/callback"}


class MaintenanceLockMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces the maintenance lock for non-admin visitors."""

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - exercised via tests
        path = request.url.path
        if path in _MAINTENANCE_BYPASS_PATHS:
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

# Add session middleware with cross-site friendly settings
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="none",
    https_only=True,
    session_cookie=SESSION_COOKIE_NAME,
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


def require_chat_access(
    request: Request, creds: HTTPBasicCredentials | None = Depends(auth)
):
    require_auth(request, creds)
    user = request.session.get("user") or {}
    user_id = _clean_discord_id(user.get("id"))
    settings, _etag = load_owner_settings()
    if can_access_chat(user_id, settings.managers, settings.chat_access):
        return True
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Chat access is restricted to approved operators.",
    )


def _is_safe_redirect(target: str | None) -> bool:
    if not target:
        return False

    parsed = urlparse(target)
    return parsed.scheme == "" and parsed.netloc == "" and target.startswith("/")


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
    if creds and (
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


def _render_chat_entry(entry: Mapping[str, str], *, is_moderator: bool) -> dict[str, str]:
    cleaned_entry = dict(entry) if isinstance(entry, Mapping) else {}
    if is_moderator:
        return cleaned_entry

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


def _render_chat_entries(
    entries: Iterable[Mapping[str, str]] | None, *, is_moderator: bool
) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    if not entries:
        return rendered

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        rendered.append(_render_chat_entry(entry, is_moderator=is_moderator))

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


def _register_chat_access_request(user: Mapping[str, Any]) -> bool:
    user_id = _clean_discord_id(user.get("id"))
    if not user_id:
        return False

    settings, _etag = load_owner_settings()
    if can_access_chat(user_id, settings.managers, settings.chat_access):
        return False

    requests, etag = _load_chat_access_requests(with_etag=True)
    if any(entry.get("user_id") == user_id for entry in requests):
        return False

    entry = {
        "user_id": user_id,
        "display_name": _discord_display_name(user),
        "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    requests.append(entry)
    return _save_chat_access_requests(requests, etag=etag)


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


def _private_message_recipients(
    settings: OwnerSettings | None = None,
) -> list[dict[str, str]]:
    if settings is None:
        settings, _ = load_owner_settings()

    candidates: list[str | None] = []
    if _ALICE_PRIVATE_MESSAGE_RECIPIENT:
        candidates.append(_ALICE_PRIVATE_MESSAGE_RECIPIENT)
    candidates.extend(settings.managers)
    candidates.extend(settings.chat_access)

    seen: set[str] = set()
    ids: list[str] = []
    for candidate in candidates:
        cleaned = _clean_discord_id(candidate)
        if cleaned and cleaned not in seen:
            ids.append(cleaned)
            seen.add(cleaned)

    operators = {str(op.user_id): op for op in list_operators()}

    recipients: list[dict[str, str]] = []
    used_initials: set[str] = set()

    for user_id in ids:
        record = operators.get(user_id)
        name = ""
        if record:
            name = str(getattr(record, "name", "") or "").strip()

        label = name or getattr(record, "id_code", None) or f"Operator {user_id}"
        initial = _allocate_alias_initial(label, used_initials)
        used_initials.add(initial)

        recipients.append({"id": user_id, "label": _masked_operator_label(initial), "initial": initial})

    return recipients


def _queue_private_message(
    *, request: Request, message: str, recipient_id: str | None
) -> dict[str, str]:
    recipients = _private_message_recipients()
    if not recipients:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private messaging is not configured.",
        )

    allowed_targets = {entry.get("id") for entry in recipients if entry.get("id")}
    target = _clean_discord_id(recipient_id)

    if not target or target not in allowed_targets:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Select a valid operator for private dispatch.",
        )

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
        payload, etag = _load_private_messages(with_etag=True)
        messages = payload.get("messages", [])

        user = request.session.get("user") if isinstance(request.session, dict) else None
        sender_id = _clean_discord_id((user or {}).get("id")) or ""
        sender_name = _discord_display_name(user)

        entry = {
            "id": secrets.token_hex(8),
            "recipient_id": target,
            "sender_id": sender_id,
            "sender": sender_name,
            "message": cleaned_message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        messages.append(entry)
        messages = _clean_private_message_log({"messages": messages})["messages"]

        if _save_private_messages(messages, etag=etag):
            return entry

    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail="Private message queue updated, please retry your message",
    )


def _pop_private_messages_for_user(
    user_id: str | None, *, recipients: list[dict[str, str]] | None = None
) -> list[dict[str, str]]:
    recipients = recipients or _private_message_recipients()
    allowed = {entry.get("id") for entry in recipients if entry.get("id")}

    cleaned_id = _clean_discord_id(user_id)
    if not allowed or not cleaned_id or cleaned_id not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You do not have any private messages queued.",
        )

    attempts = 0
    while attempts < 3:
        attempts += 1
        payload, etag = _load_private_messages(with_etag=True)
        messages = payload.get("messages", [])

        pending: list[dict[str, str]] = []
        remaining: list[dict[str, str]] = []

        for entry in messages:
            recipient_id = _clean_discord_id(entry.get("recipient_id"))
            if recipient_id == cleaned_id:
                delivered = dict(entry)
                delivered["delivered_at"] = datetime.now(timezone.utc).isoformat()
                pending.append(delivered)
            else:
                remaining.append(entry)

        if not pending:
            return []

        if _save_private_messages(remaining, etag=etag):
            return pending

    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail="Private messages updated, please retry",
    )


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

        user = request.session.get("user") if isinstance(request.session, dict) else None
        actor_label = _format_actor(user)
        is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
        operator_name = _discord_display_name(user)
        operator_initial = _operator_initial(user)

        entry = {
            "id": secrets.token_hex(8),
            "message": cleaned_message,
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
                request.session["user"] = resp.json()
        else:  # pragma: no cover - defensive guard
            logger.warning("OAuth token missing access_token; skipping profile load")

        redirect_target = _clean_redirect_target(
            request.session.pop("post_auth_redirect", None)
        )

        return RedirectResponse(url=redirect_target)

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
    }
    return templates.TemplateResponse(
        "dashboard.html",
        _inject_wallpaper(context, "dashboard"),
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


_ADMIN_PROFILE_CACHE: dict[str, tuple[datetime, dict]] = {}
_ADMIN_PROFILE_CACHE_TTL = timedelta(minutes=30)


def _clean_discord_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate.isdigit():
        return None
    return candidate


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

    if not bot_token_available():
        return {}

    now = datetime.now(timezone.utc)
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

    return cached


async def _build_admin_roster_entries(
    admin_ids: Iterable[str],
    bios: Mapping[str, AdminBio],
    current_user_id: str | None,
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
        entries.append(
            {
                "id": user_id,
                "name": name,
                "username": username,
                "avatar": avatar,
                "initials": display_initials,
                "bio": bio_text,
                "profile_url": f"https://discord.com/users/{user_id}",
                "can_edit": current_user_id == user_id,
                "has_bio": bool(bio_text.strip()),
            }
        )
    return entries


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
    return compare_digest(username, ADMIN_USER) and compare_digest(password, ADMIN_PASS)


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
        "<div class=\"field account-actions\">"
        "  <a class=\"btn\" href=\"/dashboard\">Open Dashboard</a>"
        "  <a class=\"btn btn--alice\" href=\"/alice\">Take me to A.L.I.C.E</a>"
        + (
            "  <a class=\"btn btn--ghost admin-only\" href=\"/owner\">Admin controls</a>"
            if show_admin_link
            else ""
        )
        + "</div>"
    )


def _render_maintenance_card(state: Mapping[str, Any]) -> str:
    active = bool(state.get("enabled"))
    chip_class = "status-chip status-chip--alert" if active else "status-chip status-chip--active"
    status_label = "Active" if active else "Standby"
    message = html.escape(state.get("message") or SITE_LOCK_MESSAGE_DEFAULT)
    actor = state.get("actor")
    activated_at = state.get("enabled_at")
    hint = (
        "Non-admins currently see the maintenance warning."
        if active
        else "Visitors have full access."
    )
    meta_lines: list[str] = [f"<div>{html.escape(hint)}</div>"]
    if actor:
        meta_lines.append(
            "<div>Activated by <span class=\"chip\">{}</span></div>".format(
                html.escape(str(actor))
            )
        )
    if active and activated_at:
        meta_lines.append(
            "<div>Since <span class=\"chip\">{}</span></div>".format(
                html.escape(str(activated_at))
            )
        )
    meta_block = "<div class=\"maintenance-meta\">{}</div>".format("".join(meta_lines))

    button_label = "Restore normal access" if active else "Enter maintenance mode"
    button_mode = "disable" if active else "enable"
    button_class = "btn btn--ghost" if active else "btn btn--warning"

    return (
        "<div class=\"card card--maintenance\">"
        "  <h3>Maintenance mode</h3>"
        f"  <div class=\"{chip_class}\">{status_label}</div>"
        f"  <p class=\"maintenance-note\">{message}</p>"
        f"  {meta_block}"
        "  <form method=\"post\" action=\"/admin/maintenance\" class=\"maintenance-form\">"
        f"    <input type=\"hidden\" name=\"mode\" value=\"{button_mode}\">"
        f"    <button class=\"{button_class}\" type=\"submit\">{button_label}</button>"
        "  </form>"
        "</div>"
    )


def _build_maintenance_response(state: Mapping[str, Any]) -> HTMLResponse:
    """Render the orange warning screen shown to non-admin visitors."""

    message = html.escape(state.get("message") or SITE_LOCK_MESSAGE_DEFAULT)
    actor = state.get("actor")
    activated_at = state.get("enabled_at")
    actor_line = (
        "<p class=\"meta\">Activated by <span>{}</span></p>".format(
            html.escape(str(actor))
        )
        if actor
        else ""
    )
    time_line = (
        "<p class=\"meta\">Since <span>{}</span></p>".format(
            html.escape(str(activated_at))
        )
        if activated_at
        else ""
    )
    html_doc = f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Maintenance in progress</title>
  <style>
    body {{
      margin:0;
      min-height:100vh;
      font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont;
      background:#0b0e14;
      color:#fff7ed;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:40px 20px;
    }}
    .notice {{
      max-width: 560px;
      background: linear-gradient(180deg, rgba(249,115,22,.2), rgba(249,115,22,.05));
      border: 2px solid rgba(249,115,22,.5);
      border-radius: 24px;
      padding: 32px;
      text-align: center;
      box-shadow: 0 30px 80px rgba(0,0,0,.45);
    }}
    .badge {{
      display:inline-flex;
      padding:6px 14px;
      border-radius:999px;
      background:rgba(249,115,22,.2);
      border:1px solid rgba(249,115,22,.5);
      font-size:12px;
      letter-spacing:.2em;
      text-transform:uppercase;
      color:#fed7aa;
      margin-bottom:12px;
    }}
    h1 {{
      font-size: clamp(26px, 5vw, 42px);
      margin: 0;
      color:#ffedd5;
    }}
    p {{
      line-height:1.6;
      font-size: 16px;
      margin: 16px 0 0;
    }}
    .meta {{
      font-size: 14px;
      color:#fed7aa;
    }}
    .meta span {{
      font-weight:600;
    }}
    .cta {{
      margin-top:24px;
      display:inline-flex;
      padding: 12px 20px;
      border-radius: 12px;
      border:1px solid rgba(255,255,255,.3);
      color:#0b0e14;
      background:#f97316;
      font-weight:700;
      text-decoration:none;
    }}
  </style>
</head>
<body>
  <div class=\"notice\">
    <div class=\"badge\">Maintenance</div>
    <h1>Systems offline for servicing</h1>
    <p>{message}</p>
    {actor_line}
    {time_line}
    <p class=\"meta\">If you're an administrator you may still <a href=\"/login\" class=\"cta\">sign in</a>.</p>
  </div>
</body>
</html>
"""
    return HTMLResponse(html_doc, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


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
    settings: OwnerSettings,
    can_manage_owner: bool,
    *,
    admin_only: bool = False,
    is_owner: bool = False,
) -> str:
    version = settings.bot_version.strip()
    if version:
        version_html = f"<span class=\"chip\">{html.escape(version)}</span>"
    else:
        version_html = "<span class=\"muted\">Not set</span>"

    update = settings.latest_update.strip()
    priority = normalise_broadcast_priority(settings.latest_update_priority)
    priority_labels = {
        "standard": "Standard broadcast",
        "high-priority": "Priority broadcast",
        "emergency": "Emergency broadcast",
    }
    priority_label = priority_labels.get(priority, "Standard broadcast")
    priority_chip = (
        f"<span class=\"status-chip status-chip--broadcast status-chip--{priority}\">"
        f"{priority_label}</span>"
    )
    if update:
        update_html = html.escape(update).replace("\n", "<br>")
        update_block = f"<div class=\"owner-update owner-update--{priority}\">{update_html}</div>"
    else:
        update_block = "<div class=\"muted small\">No update broadcast yet.</div>"

    manage_button = ""
    if can_manage_owner:
        primary_links = []
        secondary_links = []
        primary_links.append("<a class=\"btn\" href=\"/owner\">Manage broadcast</a>")
        secondary_links.append("<a class=\"btn btn--ghost\" href=\"/fleet\">Fleet manager</a>")

        all_links = [*primary_links, *secondary_links]
        manage_button = (
            "<div class=\"field\" style=\"margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;\">"
            + "".join(all_links)
            + "</div>"
        )

    classes = "card card--owner"
    if admin_only:
        classes += " admin-only"

    return (
        f"<div class=\"{classes}\">"
        "  <h3>Operations broadcast</h3>"
        "  <p class=\"owner-lede\">Welcome to the public-facing command console. Update your outbound bulletin and keep Spectre's status aligned with the current mission.</p>"
        "  <div class=\"muted\">Bot version</div>"
        f"  <div class=\"owner-version\">{version_html}</div>"
        f"  <div class=\"owner-broadcast-meta\">{priority_chip}</div>"
        "  <div class=\"muted\" style=\"margin-top:12px;\">Latest update</div>"
        f"  {update_block}"
        f"  {manage_button}"
        "</div>"
    )


def _war_outcome_copy(state: Mapping[str, Any] | None, war_status: str) -> str:
    payload = state if isinstance(state, Mapping) else {}
    message = str(payload.get("war_outcome_message") or "").strip()
    if war_status == "victory":
        return message or "Pyro secured. War map locked while command redeploys."
    if war_status == "retreat":
        return message or "Command ordered a strategic withdrawal. War map locked while fleets regroup."
    return message


def _render_war_card_block(state: Mapping[str, Any] | None, *, is_admin: bool) -> str:
    payload = state if isinstance(state, Mapping) else {}
    war_status = str(payload.get("war_status") or "active").strip().lower()
    if war_status not in _WAR_STATUS_VALUES:
        war_status = "active"

    if war_status == "peace" and not is_admin:
        return ""

    outcome_copy = _war_outcome_copy(payload, war_status)
    status_title = "Active theatre"
    status_body = (
        "Command has authorised full mobilisation. Review the Pyro theatre overlay before deploying squads."
    )
    tone = "active"
    primary_href = "/operations/pyro-war"
    primary_label = "Launch War Map"
    card_class = "card card--war"
    access_note = ""
    admin_ctas: list[str] = []

    if war_status == "victory":
        status_title = "Victory declared"
        status_body = outcome_copy or status_body
        tone = "victory"
        primary_href = "/operations/pyro-war/victory"
        primary_label = "View victory screen"
        card_class = "card card--war card--war-victory"
        access_note = (
            "<p class=\\\"muted\\\" style=\\\"margin-top:10px;\\\">War map access is limited to admins until the next declaration.</p>"
        )
    elif war_status == "retreat":
        status_title = "Strategic withdrawal"
        status_body = outcome_copy or status_body
        tone = "retreat"
        primary_href = "/operations/pyro-war/retreat"
        primary_label = "View withdrawal notice"
        card_class = "card card--war card--war-retreat"
        access_note = (
            "<p class=\\\"muted\\\" style=\\\"margin-top:10px;\\\">War map access is limited to admins until the next declaration.</p>"
        )
    elif war_status == "peace":
        status_title = "Theatre offline"
        status_body = outcome_copy or (
            "The Pyro war map has been stood down during peacetime."
        )
        tone = "inactive"
        primary_button = '<span class="btn btn--ghost" aria-label="War map offline">War map offline</span>'
        primary_href = None
        access_note = (
            "<p class=\"muted\" style=\"margin-top:10px;\">The theatre is unavailable until operations resume.</p>"
        )
        if is_admin:
            admin_ctas.append(
                '<a class="btn btn--ghost btn--admin" href="/admin/war-manager" aria-label="Re-open the war map">Admin: re-open war map</a>'
            )

    status_body_html = html.escape(status_body).replace("\n", "<br>")
    primary_button_class = "btn btn--war" if war_status == "active" else "btn btn--ghost"
    primary_button = ""
    if war_status != "peace":
        primary_button = (
            f'<a class="{primary_button_class}" href="{primary_href}" aria-label="{primary_label}">{primary_label}</a>'
        )

    buttons: list[str] = []
    if is_admin:
        admin_ctas.append(
            '<a class="btn btn--ghost btn--admin" href="/admin/war-manager" aria-label="Manage the war map">Open War Manager</a>'
        )
        buttons.extend([cta for cta in admin_ctas if cta])
    else:
        if primary_button:
            buttons.append(primary_button)
    button_block = "\n          ".join([b for b in buttons if b])
    return f"""
      <div class=\"{card_class}\" role=\"region\" aria-labelledby=\"warMapTitle\"> 
        <div class=\"war-card__eyebrow\">Pyro War Theatre</div>
        <h3 id=\"warMapTitle\">Pyro War Status</h3>
        <div class=\"war-card__status\" data-tone=\"{tone}\"> 
          <div class=\"war-card__status-title\">{html.escape(status_title)}</div>
          <div class=\"war-card__status-body\">{status_body_html}</div>
        </div>
        <div class=\"field\" style=\"margin-top:16px;\">
          {button_block}
        </div>
        {access_note}
      </div>
    """


def _normalise_health_status(value) -> str:
    key = str(value or "").strip().lower()
    if key in _HEALTH_STATUS_OPTIONS:
        return key
    return "online"


def _render_health_card(state: Mapping[str, Any] | None) -> str:
    payload = state if isinstance(state, Mapping) else {}
    status = _normalise_health_status(payload.get("status"))
    note_value = html.escape(str(payload.get("note") or ""), quote=True)
    option_rows: list[str] = []
    for key, option in _HEALTH_STATUS_OPTIONS.items():
        checked = " checked" if key == status else ""
        label = html.escape(option.get("label", key.title()))
        description = html.escape(option.get("description", ""))
        option_rows.append(
            "<label class=\"health-option\">"
            f"  <input type=\"radio\" name=\"status\" value=\"{key}\"{checked} required>"
            f"  <span class=\"status-chip {option['chip']}\">{label}</span>"
            f"  <span class=\"health-option-note\">{description}</span>"
            "</label>"
        )
    options_block = "".join(option_rows)
    return f"""
      <div class=\"card card--health\">
        <h3>System health broadcast</h3>
        <p class=\"muted small\">Choose the prefix and optional note shown under Bot Intel.</p>
        <form method=\"post\" action=\"/admin/system-health\" class=\"health-form\">
          <div class=\"health-grid\">
            {options_block}
          </div>
          <label for=\"healthNote\">Status note</label>
          <input id=\"healthNote\" name=\"note\" type=\"text\" maxlength=\"140\" value=\"{note_value}\" placeholder=\"Add a short operator note\" autocomplete=\"off\">
          <div class=\"field\" style=\"margin-top:14px;\">
            <button class=\"btn\" type=\"submit\">Update broadcast</button>
          </div>
        </form>
      </div>
    """


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


def _pop_panel_flash(request: Request) -> dict | None:
    data = request.session.get(_PANEL_FLASH_KEY)
    if data is not None:
        request.session.pop(_PANEL_FLASH_KEY, None)
    return data if isinstance(data, dict) else None


def _push_panel_flash(request: Request, status_label: str, message: str) -> None:
    if not message:
        return
    request.session[_PANEL_FLASH_KEY] = {
        "status": status_label,
        "message": message,
    }


def _pop_chat_access_flash(request: Request) -> dict | None:
    data = request.session.get(_CHAT_ACCESS_FLASH_KEY)
    if data is not None:
        request.session.pop(_CHAT_ACCESS_FLASH_KEY, None)
    return data if isinstance(data, dict) else None


def _push_chat_access_flash(request: Request, status_label: str, message: str) -> None:
    if not message:
        return
    request.session[_CHAT_ACCESS_FLASH_KEY] = {
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
    if bot_available and (os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN") or BOT_TOKEN):
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

    context = _inject_wallpaper(
        {
            "request": request,
            "accent": ACCENT,
            "brand": BRAND,
            "guild_name": guild_display_name,
            "guild_avatar": guild_avatar_html,
            "guild_id": str(guild_id),
            "guild_id_js": json.dumps(str(guild_id)),
        },
        "panel",
    )
    return templates.TemplateResponse("panel.html", context)



def _render_config_panel_html(**context):
    context.setdefault("FLASH_BLOCK", "")
    context.setdefault("HEALTH_CARD", "")
    context.setdefault("WAR_CARD", "")
    context.setdefault("BRANDING_CARD", "")
    html_doc = """
<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{BRAND} Config Panel</title>
<meta name=\"theme-color\" content=\"{ACCENT}\">
<script src=\"/static/onboarding.js\" defer></script>
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
  .wrap {{ max-width: 1220px; margin: 0 auto; padding: 40px 18px 64px; position: relative; }}
  .title-row {{ display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap; }}
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
  .row {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap:14px; margin-top:22px; }}
  .card {{
    background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 16px; padding: 16px 16px 14px;
    box-shadow: 0 8px 30px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.04);
    backdrop-filter: blur(4px);
  }}
  .card--war {{
    border-color: rgba(248,113,113,.6);
    background: linear-gradient(180deg, rgba(127,29,29,.75), rgba(30,6,6,.9));
    box-shadow: 0 18px 48px rgba(239,68,68,.35), inset 0 1px 0 rgba(255,255,255,.08);
    position: relative;
    overflow: hidden;
  }}
  .card--war:before {{
    content: "";
    position: absolute;
    inset: 4px;
    border-radius: 12px;
    border: 1px solid rgba(248,113,113,.35);
    pointer-events: none;
    box-shadow: 0 0 55px rgba(248,113,113,.35);
  }}
  .card--war-victory {{
    border-color: rgba(52,211,153,.7);
    background: linear-gradient(180deg, rgba(5,46,22,.86), rgba(6,78,59,.92));
    box-shadow: 0 18px 48px rgba(16,185,129,.35), inset 0 1px 0 rgba(255,255,255,.08);
  }}
  .card--war-victory:before {{
    border-color: rgba(52,211,153,.4);
    box-shadow: 0 0 55px rgba(16,185,129,.32);
  }}
  .card--war-retreat {{
    border-color: rgba(127,29,29,.75);
    background: linear-gradient(180deg, rgba(55,7,7,.92), rgba(19,3,3,.94));
    box-shadow: 0 18px 48px rgba(127,29,29,.45), inset 0 1px 0 rgba(255,255,255,.06);
  }}
  .card--war-retreat:before {{
    border-color: rgba(127,29,29,.55);
    box-shadow: 0 0 55px rgba(68,9,9,.45);
  }}
  .war-card__eyebrow {{
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: .35em;
    color: rgba(254,226,226,.85);
    margin-bottom: 6px;
  }}
  .war-card__status {{
    margin: 10px 0 0;
    padding: 12px 14px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,.08);
    background: rgba(54,9,14,.4);
  }}
  .war-card__status[data-tone="victory"] {{
    border-color: rgba(52,211,153,.38);
    background: rgba(5,46,22,.38);
  }}
  .war-card__status[data-tone="retreat"] {{
    border-color: rgba(239,68,68,.38);
    background: rgba(55,7,7,.45);
  }}
  .war-card__status-title {{
    font-size: 13px;
    letter-spacing: .18em;
    text-transform: uppercase;
    font-weight: 700;
  }}
  .war-card__status-body {{
    margin-top: 6px;
    color: #f5f7ff;
    line-height: 1.5;
  }}
  .card h3 {{ margin:0 0 10px; font-size: 16px; color:#cfd6e4; font-weight:700; letter-spacing:.3px }}
  .btn {{
    display:inline-flex; align-items:center; justify-content:center; gap:8px; border-radius: 12px; padding: 10px 14px;
    background: color-mix(in oklab, var(--accent) 88%, black 8%);
    color:#0b0e14; font-weight:700; text-decoration:none; border:1px solid color-mix(in oklab, var(--accent) 50%, black 45%);
    box-shadow: 0 8px 24px color-mix(in oklab, var(--accent) 35%, transparent);
    cursor: pointer;
    flex-shrink: 0;
    min-height: 44px;
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
  .btn--warning {{
    background: #ea580c;
    border-color: #fb923c;
    color: #fff7ed;
    box-shadow: 0 8px 24px rgba(234,88,12,.4);
  }}
  .btn--warning:hover {{
    filter: brightness(1.05);
    transform: translateY(-1px);
  }}
  .btn--war {{
    background: #ff1f2d;
    border-color: rgba(252,165,165,.8);
    color: #fff9f5;
    letter-spacing: .3em;
    text-transform: uppercase;
    box-shadow: 0 0 35px rgba(255,31,45,.65);
    filter: drop-shadow(0 0 12px rgba(255,31,45,.4));
    backdrop-filter: blur(2px);
  }}
  .btn--war:hover {{
    filter: drop-shadow(0 0 18px rgba(255,31,45,.6));
    transform: translateY(-1px);
  }}
  .btn--admin {{
    padding: 12px 16px;
    min-width: 150px;
  }}
  .btn--alice {{
    background: linear-gradient(135deg, #1a9a6f, #0f7a56);
    border-color: rgba(26, 154, 111, .7);
    color: #04160c;
    box-shadow: 0 10px 28px rgba(15, 122, 86, .32);
    text-transform: none;
    letter-spacing: .2px;
  }}
  .btn--alice:hover {{
    filter: brightness(1.04);
    transform: translateY(-1px);
    box-shadow: 0 14px 36px rgba(15, 122, 86, .48);
    backdrop-filter: blur(2.5px);
  }}
  .muted {{ color: var(--muted) }}
  .field {{ display:flex; gap:12px; align-items:center; margin-top:10px; flex-wrap: wrap }}
  .account-actions {{
    flex-direction: column;
    align-items: stretch;
    margin-top: 16px;
    width: 100%;
  }}
  .account-actions .btn {{ width: 100%; justify-content: center; }}
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
  .flash {{
    margin-top: 20px;
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,.12);
    background: rgba(12,18,30,.82);
    font-size: 14px;
    font-weight: 600;
  }}
  .flash--success {{ border-color: rgba(34,197,94,.4); color: #bbf7d0; background: rgba(34,197,94,.12); }}
  .flash--error {{ border-color: rgba(248,113,113,.45); color: #fecaca; background: rgba(248,113,113,.12); }}
  .flash--warn {{ border-color: rgba(251,191,36,.45); color: #fde68a; background: rgba(251,191,36,.12); }}
  .flash--info {{ border-color: rgba(59,130,246,.35); color: #bfdbfe; background: rgba(59,130,246,.12); }}
  .card--servers {{ grid-column: 1 / -1; }}
  .card--diagnostics {{ min-width: 260px; }}
  .fact-grid {{ display:grid; gap:16px; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); margin-top:16px; }}
  .admin-team-cta {{
    margin-top:20px;
    padding:18px;
    border-radius:16px;
    border:1px solid rgba(255,255,255,.08);
    background: rgba(12,18,30,.72);
    display:flex;
    flex-wrap:wrap;
    gap:12px;
    align-items:center;
    justify-content:space-between;
  }}
  .admin-team-cta .cta-copy {{ flex:1; min-width:200px; }}
  .admin-team-cta .cta-title {{ font-size:15px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:#cbd5f5; }}
  .admin-team-cta .cta-text {{ margin-top:4px; font-size:13px; color:rgba(226,232,240,.8); }}
  .fact {{ border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:16px; background:rgba(12,18,30,.72); display:flex; flex-direction:column; gap:8px; min-height:120px; box-shadow: inset 0 1px 0 rgba(255,255,255,.03); }}
  .fact-label {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:600; }}
  .fact-value {{ font-size:20px; font-weight:700; color:var(--text); line-height:1.2; }}
  .fact-hint {{ font-size:12px; color:var(--muted); line-height:1.45; }}
  .fact-health {{ display:flex; flex-direction:column; gap:8px; }}
  .health-note {{ font-size:13px; color:var(--muted); line-height:1.45; }}
  .status-chip {{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .5px;
    text-transform: uppercase;
    border: 1px solid rgba(255,255,255,.18);
    background: rgba(12,18,30,.85);
    width: max-content;
  }}
  .status-chip--active {{ border-color: rgba(34,197,94,.4); color: #86efac; }}
  .status-chip--in-dock {{ border-color: rgba(56,189,248,.4); color: #bae6fd; }}
  .status-chip--lost {{ border-color: rgba(248,113,113,.4); color: #fecaca; }}
  .status-chip--retrofit {{ border-color: rgba(251,191,36,.4); color: #fde68a; }}
  .status-chip--alert {{ border-color: rgba(249,115,22,.4); color: #fed7aa; }}
  .card--health .health-form {{ display:grid; gap:12px; margin-top:10px; }}
  .health-grid {{ display:grid; gap:10px; }}
  .health-option {{
    display:flex;
    align-items:center;
    gap:12px;
    padding:10px 12px;
    border-radius:12px;
    border:1px solid rgba(255,255,255,.12);
    background: rgba(12,18,30,.7);
  }}
  .health-option input {{ width:16px; height:16px; margin:0; accent-color: var(--accent); }}
  .health-option-note {{ font-size:12px; color:var(--muted); }}
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
  .owner-greeting {{ display:flex; flex-direction:column; gap:6px; margin-bottom:12px; }}
  .owner-greeting__title {{ font-size:18px; font-weight:800; letter-spacing:.2px; }}
  .owner-greeting__meta {{ font-size:13px; color:var(--muted); display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  .owner-lede {{ margin: 4px 0 10px; color: var(--muted); line-height: 1.45; }}
  .owner-broadcast-meta {{ margin: 8px 0 12px; }}
  .owner-version {{ margin-top:8px; font-size:16px; font-weight:600; }}
  .owner-update {{
    margin-top:8px;
    padding:12px 14px;
    border-radius:12px;
    border:1px solid rgba(255,255,255,.08);
    background: rgba(12,18,30,.72);
    font-size:13px;
    line-height:1.5;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 220px;
    overflow: auto;
  }}
  .owner-update--standard {{ border-color: rgba(255,255,255,.08); }}
  .owner-update--high-priority {{ border-color: rgba(251,191,36,.45); box-shadow: 0 0 0 1px rgba(251,191,36,.18); }}
  .owner-update--emergency {{ border-color: rgba(248,113,113,.65); box-shadow: 0 0 0 1px rgba(248,113,113,.2); }}
  .status-chip--broadcast {{
    background: rgba(12,18,30,.78);
    box-shadow: 0 0 0 1px rgba(255,255,255,.06), 0 0 12px rgba(148,163,184,.2);
    backdrop-filter: blur(2px);
  }}
  .status-chip--broadcast.status-chip--standard {{
    border-color: rgba(255,255,255,.14);
    color: rgba(226,232,240,.82);
    box-shadow: 0 0 0 1px rgba(255,255,255,.12), 0 0 14px rgba(226,232,240,.22);
  }}
  .status-chip--broadcast.status-chip--high-priority {{
    border-color: rgba(251,191,36,.55);
    color: #fde68a;
    box-shadow: 0 0 0 1px rgba(251,191,36,.28), 0 0 18px rgba(251,191,36,.35);
  }}
  .status-chip--broadcast.status-chip--emergency {{
    border-color: rgba(248,113,113,.65);
    color: #fecaca;
    box-shadow: 0 0 0 1px rgba(248,113,113,.32), 0 0 18px rgba(248,113,113,.42);
  }}
  .card--maintenance {{
    border-color: rgba(249,115,22,.35);
    background: linear-gradient(180deg, rgba(249,115,22,.12), rgba(249,115,22,.02));
  }}
  .maintenance-note {{
    margin: 12px 0 0;
    font-size: 14px;
    line-height: 1.5;
    color: #fed7aa;
  }}
  .maintenance-meta {{
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 12px;
    color: #fef3c7;
  }}
  .maintenance-form {{
    margin-top: 16px;
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

  {FLASH_BLOCK}

  <div class=\"row\">
    {SYSTEM_CARD}

      {OWNER_CARD}

      {FLEET_CARD}

      {BRANDING_CARD}

      <div class=\"card\">
        <h3>Account</h3>
        {ACCOUNT_BLOCK}
      </div>

      {WAR_CARD}

      {CURL_CARD}

      {HEALTH_CARD}

      {DIAGNOSTICS_CARD}
    </div>

    <div class=\"row\">
      <div class=\"card\">
        <h3>Ship tech specs</h3>
        <div class=\"muted\">Look inside the fleet manifest files and review each vessel's FDD tech specs.</div>
        <div class=\"field\" style=\"margin-top:14px;\">
          <a class=\"btn\" href=\"/fdd/tech-specs\">View Tech Specs</a>
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
        <div class=\"admin-team-cta\">
          <div class=\"cta-copy\">
            <div class=\"cta-title\">Meet the admin team</div>
            <div class=\"cta-text\">See who's keeping the archive online and reach out if you need support.</div>
          </div>
          <a class=\"btn\" href=\"/admin-team\">View profiles</a>
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
    return templates.TemplateResponse("pyro_war_outcome.html", context)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    war_state = load_pyro_war_state()
    user_id = str(user.get("id")) if user and user.get("id") else None
    can_manage_owner_portal = can_manage_portal(user_id, owner_settings.managers)
    show_owner_admin_features = bool(can_manage_owner_portal)
    is_owner_viewer = _session_user_is_owner(request)
    is_admin_viewer = _session_user_is_admin(request)
    account_block = _render_account_block(user)
    owner_card = _render_owner_card(
        owner_settings, can_manage_owner_portal, is_owner=is_owner_viewer
    )
    war_card = _render_war_card_block(war_state, is_admin=is_admin_viewer)
    diagnostics_card = ""
    system_card = ""
    curl_card = ""
    fleet_card = ""
    bot_facts_block = await _render_bot_facts_block(user, request)
    flash_block = _render_panel_flash_block(_pop_panel_flash(request))

    action_links = []
    if is_owner_viewer:
        action_links.append("<a class=\"btn\" href=\"/director\">Director console</a>")
    if show_owner_admin_features:
        action_links.append("<a class=\"btn btn--ghost\" href=\"/admin\">Enter admin mode</a>")
    action_block = '<div class="actions">' + "".join(action_links) + "</div>" if action_links else ""

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
        FLASH_BLOCK=flash_block,
        HEALTH_CARD="",
        WAR_CARD=war_card,
    )


@app.get("/admin-team", include_in_schema=False)
async def admin_team(request: Request):
    user, _guilds = await _load_user_context(request)
    owner_settings, _etag = load_owner_settings()
    current_user_id = str(user.get("id")) if user and user.get("id") else None
    is_admin_viewer = can_manage_portal(current_user_id, owner_settings.managers)
    bios = load_admin_bios()
    roster_ids: list[str] = []
    seen: set[str] = set()
    for candidate in [OWNER_USER_KEY, *owner_settings.managers]:
        cleaned = _clean_discord_id(candidate)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            roster_ids.append(cleaned)
    roster = await _build_admin_roster_entries(roster_ids, bios, current_user_id)
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

    return templates.TemplateResponse(
        "admin_team.html",
        _inject_wallpaper(
            {
                "request": request,
                "brand": BRAND,
                "accent": ACCENT,
                "roster": roster,
                "panel_flash": panel_flash,
                "is_admin_viewer": is_admin_viewer,
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
    definition_manifest = _definition_manifest()
    brand_image_url = _brand_image_url(definition_manifest)
    owner_card = _render_owner_card(
        owner_settings, True, is_owner=_session_user_is_owner(request)
    )
    war_state = load_pyro_war_state()
    war_card = _render_war_card_block(war_state, is_admin=True)
    diagnostics_card = _render_ui_diagnostics_card(request)
    bot_facts_block = await _render_bot_facts_block(user, request)
    panel_flash = _render_panel_flash_block(_pop_panel_flash(request))
    health_state = get_system_health_state()
    health_card = _render_health_card(health_state)
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

    system_card = f"""
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

    branding_card = """
      <div class=\"card\">
        <h3>Definition images</h3>
        <div class=\"muted\">Upload small images that replace shorthand labels like HQ or Spectre across the UI.</div>
        <div class=\"field\" style=\"margin-top:14px;\">
          <a class=\"btn\" href=\"/admin/definitions\">Manage library</a>
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
        BRAND_IMAGE_URL=brand_image_url or "",
        ACCOUNT_BLOCK=account_block,
        OWNER_CARD=owner_card,
        CURL_CARD=curl_card,
        SYSTEM_CARD=system_card,
        FLEET_CARD=fleet_card,
        BRANDING_CARD=branding_card,
        ACTION_BLOCK=action_block,
        BOT_FACTS=bot_facts_block,
        DIAGNOSTICS_CARD=diagnostics_card,
        DEFAULT_PAYLOAD=DEFAULT_PAYLOAD,
        FLASH_BLOCK=panel_flash,
        HEALTH_CARD=health_card,
        WAR_CARD=war_card,
    )


@app.post("/admin/maintenance", include_in_schema=False)
async def update_maintenance_mode(request: Request):
    user, redirect = await _require_director(request)
    if redirect:
        return redirect

    form = await request.form()
    mode = str(form.get("mode") or "").strip().lower()
    actor = _format_actor(user)

    if mode == "enable":
        set_site_lock_state(True, actor=actor, message=SITE_LOCK_MESSAGE_DEFAULT)
        _push_panel_flash(
            request,
            "warn",
            "Maintenance mode enabled. Non-admins now see the warning screen.",
        )
    elif mode == "disable":
        set_site_lock_state(False, actor=actor)
        _push_panel_flash(request, "success", "Maintenance mode disabled.")
    else:
        _push_panel_flash(request, "error", "Unsupported maintenance action.")

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


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


@app.get("/director", include_in_schema=False)
async def director_console(request: Request):
    """Placeholder console reserved for the configured owner."""

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
    }

    return templates.TemplateResponse(
        "director.html",
        _inject_wallpaper(context, "director"),
    )


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
    }

    return templates.TemplateResponse(
        "director_archives.html",
        _inject_wallpaper(context, "director-archives"),
    )


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

    if raw_priority not in BROADCAST_PRIORITIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Unknown broadcast priority."
        )
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Broadcast message is required.")

    actor = _format_actor(user)
    entry = record_broadcast(message, priority=priority, actor=actor)
    set_operations_broadcast(message, priority=priority, actor=actor)
    return JSONResponse({"status": "ok", "broadcast": entry.to_payload(), "priority": priority})


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
        set_site_lock_state(True, actor=actor, message=SITE_LOCK_MESSAGE_DEFAULT)
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
    roots = _archive_root_prefixes(guild_id)
    sources: list[dict[str, object]] = []

    summary = get_instance_summary()
    summary_map: dict[tuple[str, str | None], Mapping[str, object]] = {}
    for entry in summary.get("archives", []) if isinstance(summary, Mapping) else []:
        if not isinstance(entry, Mapping):
            continue
        key = (str(entry.get("root_prefix") or "").strip("/"), str(entry.get("guild_id") or "") or None)
        summary_map[key] = entry

    total_files = 0
    total_categories = 0

    local_root = normalise_root_prefix(settings.get("ROOT_PREFIX")) if isinstance(settings, Mapping) else None

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

        key = (cleaned_root, str(guild_id) if guild_id is not None else None)
        source_summary = summary_map.get(key, {}) if isinstance(summary_map, dict) else {}
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
async def personnel_board(request: Request):
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
    return templates.TemplateResponse("personnel_board.html", context)


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
        "alice.html",
        {
            "request": request,
            "brand": BRAND,
            "accent": "#5dffb4",
            "operator_name": _discord_display_name(user),
            **_chat_access_prompt_context(request),
        },
    )


@app.get("/alice/chat", include_in_schema=False)
async def alice_chat_page(request: Request):
    user = request.session.get("user")
    token = request.session.get("discord_token")

    if not user or not token:
        target = str(request.url.path)
        if request.url.query:
            target = f"{target}?{request.url.query}"

        request.session["post_auth_redirect"] = _clean_redirect_target(target, "/alice/chat")
        qp = httpx.QueryParams({"next": target})
        return RedirectResponse(url=f"/login?{qp}")

    settings, _etag = load_owner_settings()
    user_id = _clean_discord_id(user.get("id"))
    has_chat_access = can_access_chat(user_id, settings.managers, settings.chat_access)
    pending_request = False
    if user_id:
        pending_request = any(
            entry.get("user_id") == user_id
            for entry in _load_chat_access_requests()[0]
        )
    chat_flash = _pop_chat_access_flash(request)
    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    operator_display = _chat_operator_name(user, is_moderator=is_moderator)
    private_recipients = _private_message_recipients(settings)

    if templates is None:
        return JSONResponse(
            {
                "status": "alice-chat",
                "brand": BRAND,
                "has_chat_access": has_chat_access,
                "pending_request": pending_request,
                "flash": chat_flash,
                "operator_name": operator_display,
                "private_recipients": private_recipients,
            }
        )

    return templates.TemplateResponse(
        "alice_chat.html",
        {
            "request": request,
            "brand": BRAND,
            "accent": "#5dffb4",
            "operator_name": operator_display,
            "is_moderator": is_moderator,
            "has_chat_access": has_chat_access,
            "pending_request": pending_request,
            "chat_flash": chat_flash,
            "private_recipients": private_recipients,
            **_chat_access_prompt_context(request),
        },
    )


@app.post("/alice/chat/request", include_in_schema=False)
async def request_alice_chat_access(request: Request):
    user = request.session.get("user")
    if not user:
        request.session["post_auth_redirect"] = "/alice/chat"
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    settings, _etag = load_owner_settings()
    user_id = _clean_discord_id(user.get("id"))
    if can_access_chat(user_id, settings.managers, settings.chat_access):
        _push_chat_access_flash(request, "success", "You already have chat access.")
    elif _register_chat_access_request(user):
        _push_chat_access_flash(
            request,
            "success",
            "Request sent. A moderator will review your access shortly.",
        )
    else:
        _push_chat_access_flash(
            request,
            "error",
            "Unable to submit your request. It may already be pending.",
        )

    return RedirectResponse(url="/alice/chat", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/api/alice/command")
async def alice_command(
    request: Request,
    payload: dict[str, str] = Body(...),
    _: bool = Depends(require_auth),
):
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Command message is required")

    try:
        reply = await run_blocking(llm_client.run_assistant, message)
    except Exception as exc:  # pragma: no cover - best-effort logging for live LLM calls
        logger.exception("A.L.I.C.E command failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Failed to process command")

    return JSONResponse({"reply": reply})


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
                        f"Approved A.L.I.C.E. chat for {target}",
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
        chat_log.get("messages", []), is_moderator=is_moderator
    )
    return JSONResponse({"messages": messages}, headers=headers)


@app.post("/api/alice/chat")
async def alice_chat_message(
    request: Request,
    payload: dict[str, str] = Body(...),
    _: bool = Depends(require_chat_access),
):
    message = payload.get("message") or ""
    entry = _append_chat_message(request=request, message=message)
    chat_log, _ = _load_alice_chat()
    is_moderator = _session_user_is_admin(request) or _session_user_is_owner(request)
    messages = chat_log.get("messages", [])
    return JSONResponse(
        {
            "message": _render_chat_entry(entry, is_moderator=is_moderator),
            "messages": _render_chat_entries(
                messages, is_moderator=is_moderator
            ),
        }
    )


@app.delete("/api/alice/chat/{message_id}")
async def delete_chat_message(
    request: Request,
    message_id: str,
    _: bool = Depends(require_chat_access),
):
    if not (_session_user_is_admin(request) or _session_user_is_owner(request)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only moderators can manage chat messages",
        )

    chat_log = _delete_chat_message(message_id=message_id)
    return JSONResponse(chat_log)


@app.post("/api/alice/chat/private")
async def send_private_message(
    request: Request,
    payload: dict[str, str] = Body(...),
    _: bool = Depends(require_chat_access),
):
    message = payload.get("message") or ""
    recipient_id = payload.get("recipient_id") or payload.get("recipient")
    entry = _queue_private_message(
        request=request, message=message, recipient_id=recipient_id
    )
    return JSONResponse({"message": entry})


@app.get("/api/alice/chat/private")
async def receive_private_message(
    request: Request, _: bool = Depends(require_auth)
):
    user = request.session.get("user") or {}
    user_id = _clean_discord_id(user.get("id"))
    messages = _pop_private_messages_for_user(
        user_id, recipients=_private_message_recipients()
    )
    return JSONResponse({"messages": messages})


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
            "helldivers_placeholder.html",
            _inject_wallpaper(context, "helldivers-placeholder"),
        )

    summary, summary_error = await _collect_hd2_summary()
    context.update({"summary": summary, "summary_error": summary_error})
    return templates.TemplateResponse(
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
    }
    return templates.TemplateResponse(
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
    protocols_clean = _normalise_protocol_settings(copied_settings.get("protocols"))
    if protocols_clean:
        copied_settings["protocols"] = protocols_clean
    else:
        copied_settings.pop("protocols", None)
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

    protocols_clean = _normalise_protocol_settings(settings.get("protocols"))
    if protocols_clean:
        settings["protocols"] = protocols_clean
        payload["protocols"] = protocols_clean
    else:
        settings.pop("protocols", None)
        payload.pop("protocols", None)

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

    try:
        request_deploy(gid_int, reason="dashboard")
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to queue local deploy trigger for guild %s", guild_id)

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
