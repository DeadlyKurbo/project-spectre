import logging
import os
import re
from typing import Any

from storage_spaces import read_json, write_json

# Discord Tokens & Channels


def _clean_env(value: str | None) -> str | None:
    """Return ``value`` stripped of whitespace or ``None`` when empty."""

    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _env_int(name: str) -> int:
    """Return an integer environment variable or ``0`` when unset/invalid."""

    raw = _clean_env(os.getenv(name))
    if raw is None:
        return 0
    try:
        return int(raw, 10)
    except ValueError:
        logging.getLogger("spectre").warning(
            "Environment variable %s=%r is not a valid integer; using 0", name, raw
        )
        return 0


def _load_discord_token() -> str | None:
    """Return the Discord bot token from the current environment."""

    direct = _clean_env(os.getenv("DISCORD_TOKEN"))
    if direct:
        return direct

    fallback = _clean_env(os.getenv("DISCORD_BOT_TOKEN"))
    if fallback:
        logging.getLogger("spectre").warning(
            "DISCORD_TOKEN is not set; using DISCORD_BOT_TOKEN fallback. "
            "Please update the environment to use DISCORD_TOKEN."
        )
    return fallback


TOKEN = _load_discord_token()
GUILD_ID = _env_int("GUILD_ID")
# Optional second guild for multi-server deployments
GUILD_ID_SECOND = _env_int("GUILD_ID_SECOND")
# Public archive menu channel
MENU_CHANNEL_ID = _env_int("MENU_CHANNEL_ID")
# Optional archive menu channel for the second guild
MENU_CHANNEL_ID_SECOND = _env_int("MENU_CHANNEL_ID_SECOND")
# Channel for archive system status messages
STATUS_CHANNEL_ID = _env_int("STATUS_CHANNEL_ID")

# S3/Storage
ROOT_PREFIX = (os.getenv("S3_ROOT_PREFIX") or "dossiers").strip().strip("/")
_DEFAULT_MANIFEST = f"{ROOT_PREFIX}/config/categories.json" if ROOT_PREFIX else "config/categories.json"
CATEGORY_MANIFEST_PATH = (os.getenv("CATEGORY_MANIFEST_PATH") or _DEFAULT_MANIFEST).strip()

_DEFAULT_CATEGORY_ORDER = [
    ("high_command_directives", "High Command Directives"),
    ("personnel", "Personnel"),
    ("fleet", "Fleet"),
    ("missions", "Missions"),
    ("intelligence", "Intelligence"),
    ("active_efforts", "Active Efforts"),
    ("tech_equipment", "Tech & Equipment"),
    ("protocols_contingencies", "Protocols & Contingencies"),
]
if "CATEGORY_ORDER" in globals():
    CATEGORY_ORDER[:] = _DEFAULT_CATEGORY_ORDER
else:
    CATEGORY_ORDER = list(_DEFAULT_CATEGORY_ORDER)

# Visual identifiers for dossier categories. Each entry maps the category
# slug to a tuple of (emoji, color).  These are used by the archive menu to
# provide quick at-a-glance recognition of sections.

# Global styling for the archive root interface so it can appear with
# consistent branding alongside specific dossier categories.
ARCHIVE_EMOJI = ""
ARCHIVE_COLOR = 0x00FFCC

_DEFAULT_CATEGORY_STYLES = {
    # Each dossier category is assigned a unique emoji and embed color so the
    # UI can convey an immediate "emotional" context similar to the existing
    # Personnel and Missions sections.  Keeping these definitions centralized
    # makes it easy to tweak the look and feel without touching the rendering
    # code spread throughout the project.
    "high_command_directives": ("📜", 0xE74C3C),
    # "" (saluting face) caused API errors on some Discord clients; use a
    # widely supported fallback emoji to ensure the menu renders reliably.
    "personnel": ("👥", 0x3498DB),
    "fleet": ("🚀", 0x1ABC9C),
    "missions": ("🎯", 0x2ECC71),
    "intelligence": ("🕵️", 0x9B59B6),
    "active_efforts": ("📌", 0xE67E22),
    "tech_equipment": ("💻", 0xF1C40F),
    "protocols_contingencies": ("⚠️", 0x34495E),
    # Root archive interface
    "archive": (ARCHIVE_EMOJI, ARCHIVE_COLOR),
}
if "CATEGORY_STYLES" in globals():
    CATEGORY_STYLES.clear()
    CATEGORY_STYLES.update(_DEFAULT_CATEGORY_STYLES)
else:
    CATEGORY_STYLES = dict(_DEFAULT_CATEGORY_STYLES)

_CATEGORY_LOGGER = logging.getLogger("spectre.categories")


def _normalize_slug(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or None


def _coerce_color(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            if cleaned.startswith("#"):
                cleaned = cleaned[1:]
            if cleaned.lower().startswith("0x"):
                cleaned = cleaned[2:]
            color = int(cleaned, 16)
        else:
            color = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= color <= 0xFFFFFF:
        return color
    return None


def _apply_category_manifest(manifest: dict[str, Any]) -> None:
    entries = manifest.get("categories") or manifest.get("order")
    parsed: list[tuple[str, str]] = []
    if isinstance(entries, list):
        for entry in entries:
            slug: str | None = None
            label: str | None = None
            if isinstance(entry, (list, tuple)) and entry:
                slug = _normalize_slug(entry[0])
                if len(entry) > 1 and isinstance(entry[1], str):
                    label = entry[1].strip() or None
            elif isinstance(entry, dict):
                slug = _normalize_slug(entry.get("slug"))
                label_val = entry.get("label") or entry.get("name")
                if isinstance(label_val, str):
                    label = label_val.strip() or None
            if slug:
                if label is None:
                    label = slug.replace("_", " ").title()
                parsed.append((slug, label))
    if parsed:
        CATEGORY_ORDER[:] = parsed

    styles = manifest.get("styles")
    if isinstance(styles, dict):
        for slug_raw, entry in styles.items():
            slug = _normalize_slug(slug_raw)
            if not slug:
                continue
            emoji = None
            color_value: Any = None
            if isinstance(entry, dict):
                emoji_val = entry.get("emoji")
                if isinstance(emoji_val, str):
                    emoji = emoji_val.strip() or None
                color_value = entry.get("color")
            elif isinstance(entry, (list, tuple)) and entry:
                emoji_val = entry[0]
                if isinstance(emoji_val, str):
                    emoji = emoji_val.strip() or None
                if len(entry) > 1:
                    color_value = entry[1]
            color = _coerce_color(color_value)
            if color is None:
                color = ARCHIVE_COLOR
            CATEGORY_STYLES[slug] = (emoji, color)


def reload_category_manifest() -> None:
    """Load category configuration from object storage when available."""

    if not CATEGORY_MANIFEST_PATH:
        return
    try:
        manifest = read_json(CATEGORY_MANIFEST_PATH)
    except FileNotFoundError:
        return
    except Exception:  # pragma: no cover - defensive logging
        _CATEGORY_LOGGER.exception(
            "Failed to read category manifest from %s", CATEGORY_MANIFEST_PATH
        )
        return
    if isinstance(manifest, dict):
        _apply_category_manifest(manifest)


def export_category_manifest() -> dict[str, Any]:
    categories = [
        {"slug": slug, "label": label}
        for slug, label in CATEGORY_ORDER
    ]
    styles = {
        slug: {"emoji": emoji, "color": color}
        for slug, (emoji, color) in CATEGORY_STYLES.items()
    }
    return {"categories": categories, "styles": styles}


def save_category_manifest() -> None:
    """Persist the current category manifest to object storage."""

    if not CATEGORY_MANIFEST_PATH:
        return
    payload = export_category_manifest()
    try:
        write_json(CATEGORY_MANIFEST_PATH, payload)
    except Exception:  # pragma: no cover - defensive logging
        _CATEGORY_LOGGER.exception(
            "Failed to persist category manifest to %s", CATEGORY_MANIFEST_PATH
        )

# Archive interface theming
ARCHIVE_INTERFACE_HEADER = "SPECTRE Archive Nexus"
ARCHIVE_FOOTER_BROWSING = "Archive channel active."
ARCHIVE_FOOTER_UPLOAD = "File integrity monitor active."
ARCHIVE_FOOTER_CLEARANCE = "Authorization event recorded."

# Security keys
EPSILON_LAUNCH_CODE = os.getenv(
    "EPSILON_LAUNCH_CODE", "EPSILON-NIGHTFALL-88XM-THETA"
)
EPSILON_OWNER_CODE = os.getenv(
    "EPSILON_OWNER_CODE", "EPSILON-DAWN-44QK-ALPHA"
)
EPSILON_XO_CODE = os.getenv(
    "EPSILON_XO_CODE", "EPSILON-MIDNIGHT-72LV-GAMMA"
)
EPSILON_FLEET_CODE = os.getenv(
    "EPSILON_FLEET_CODE", "EPSILON-DUSK-11AB-ZETA"
)
OMEGA_KEY_FRAGMENT_1 = os.getenv("OMEGA_KEY_FRAGMENT_1", "OMEGA-LAZARUS-77XI-PI")
OMEGA_KEY_FRAGMENT_2 = os.getenv(
    "OMEGA_KEY_FRAGMENT_2", "Sigma-Omega-Sigma-Code-Talon-68D"
)
OMEGA_BACKUP_PATH = os.getenv("OMEGA_BACKUP_PATH", "backups/.omega.json")

# OpenAI keys & models
LLM_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_ASSISTANT_ID = os.getenv("LLM_ASSISTANT_ID")  # <-- Belangrijk voor Assistants API

# Role IDs
LEVEL1_ROLE_ID = _env_int("LEVEL1_ROLE_ID")
LEVEL2_ROLE_ID = _env_int("LEVEL2_ROLE_ID")
LEVEL3_ROLE_ID = _env_int("LEVEL3_ROLE_ID")
LEVEL4_ROLE_ID = _env_int("LEVEL4_ROLE_ID")
LEVEL5_ROLE_ID = _env_int("LEVEL5_ROLE_ID")
CLASSIFIED_ROLE_ID = _env_int("CLASSIFIED_ROLE_ID")

OWNER_ROLE_ID = _env_int("OWNER_ROLE_ID")
XO_ROLE_ID = _env_int("XO_ROLE_ID")
FLEET_ADMIRAL_ROLE_ID = _env_int("FLEET_ADMIRAL_ROLE_ID")

ALLOWED_ASSIGN_ROLES = {
    role_id
    for role_id in (
        LEVEL1_ROLE_ID,
        LEVEL2_ROLE_ID,
        LEVEL3_ROLE_ID,
        LEVEL4_ROLE_ID,
        LEVEL5_ROLE_ID,
        CLASSIFIED_ROLE_ID,
    )
    if role_id
}

# Channels
UPLOAD_CHANNEL_ID = _env_int("UPLOAD_CHANNEL_ID")
LAZARUS_CHANNEL_ID = _env_int("LAZARUS_CHANNEL_ID")
CLEARANCE_REQUESTS_CHANNEL_ID = _env_int("CLEARANCE_REQUESTS_CHANNEL_ID")
LEAD_NOTIFICATION_CHANNEL_ID = _env_int("LEAD_NOTIFICATION_CHANNEL_ID")
REPORT_REPLY_CHANNEL_ID = _env_int("REPORT_REPLY_CHANNEL_ID")
SECURITY_LOG_CHANNEL_ID = _env_int("SECURITY_LOG_CHANNEL_ID")
# Roles
LEAD_ARCHIVIST_ROLE_ID = _env_int("LEAD_ARCHIVIST_ROLE_ID")
CLEARANCE_APPROVER_ROLE_ID = _env_int("CLEARANCE_APPROVER_ROLE_ID")
ARCHIVIST_ROLE_ID = _env_int("ARCHIVIST_ROLE_ID")
TRAINEE_ROLE_ID = _env_int("TRAINEE_ROLE_ID")
HIGH_COMMAND_ROLE_ID = _env_int("HIGH_COMMAND_ROLE_ID")

# Personnel rank roles
CAPTAIN_ROLE_ID = _env_int("CAPTAIN_ROLE_ID")
VETERAN_OFFICER_ROLE_ID = _env_int("VETERAN_OFFICER_ROLE_ID")
OFFICER_ROLE_ID = _env_int("OFFICER_ROLE_ID")
SPECIALIST_ROLE_ID = _env_int("SPECIALIST_ROLE_ID")
SEAMAN_ROLE_ID = _env_int("SEAMAN_ROLE_ID")
TRAINEE_RANK_ROLE_ID = _env_int("TRAINEE_RANK_ROLE_ID")

# Timeouts & Limits
ARCHIVIST_MENU_TIMEOUT = 5 * 60  # 5 min
CONTENT_MAX_LENGTH = 500
PAGE_SEPARATOR = "\f"

# UI Text
INTRO_TITLE = "SPECTRE Archive Console"
INTRO_DESC = (
    "Welcome, operator.\n"
    "Use the controls below to browse archived files and operational records. Actions are logged for accountability.\n\n"
    "**Archivist Console** (ephemeral): `/archivist`\n"
    "• Upload or remove files\n"
    "• Grant or revoke file clearances\n\n"
    "**Files**: `.json` or `.txt`"
)

REG_ARCHIVIST_TITLE = "SPECTRE // Archivist Console [Restricted]"
REG_ARCHIVIST_DESC = (
    '> "Operator authentication verified."\n'
    '> Mode: Restricted • Write-capable (scoped)\n\n'
    "You are connected to the archive with limited privileges.\n\n"
    "• Upload new dossiers to the repository\n"
    "• Remove outdated files with safety throttling\n"
    "• All actions are signed to your operator profile and audited\n\n"
    "Status\n"
    "• Deletes: Limited (hourly quota)\n"
    "• Edits: Limited (raw only, hourly quota)\n"
    "• Clearance tools: Locked (insufficient authority)"
)

LEAD_ARCHIVIST_TITLE = "SPECTRE // Lead Archivist Console (L5)"
LEAD_ARCHIVIST_DESC = (
    '> "Lead authority confirmed."\n'
    '> Clearance Tier: L5+ • Authority: Full Admin\n\n'
    "You hold administrative control over the archive.\n"
    "Actions executed here are authoritative and system-visible.\n\n"
    "Capabilities\n"
    "• Dossier lifecycle: upload • edit • remove\n"
    "• Access control: grant/revoke file-level clearances\n"
    "• Systems: integrity scan • backup/restore • build controls"
)

HIGH_COMMAND_TITLE = "SPECTRE // Command Terminal"
HIGH_COMMAND_DESC = (
    '> "Command override confirmed."\n'
    '> Clearance Tier: HC • Authority: Total\n\n'
    "You hold top-tier control over the archive.\n\n"
    "Capabilities\n"
    "• All Lead Archivist functions\n"
    "• Archive lockdown controls"
)

TRAINEE_ARCHIVIST_TITLE = "[Training Console: Review Mode]"
TRAINEE_ARCHIVIST_DESC = (
    "Welcome, Operator.\n"
    "All changes made here remain in *Pending* status until reviewed by a Lead Archivist.\n\n"
    "Capabilities\n"
    "• Perform real archive actions in a sandbox\n"
    "• Submit changes for Lead review\n"
    "• Receive feedback & resubmit if needed"
)

reload_category_manifest()
