from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, Iterable

from storage_spaces import read_json

from constants import (
    TOKEN,
    GUILD_ID,
    GUILD_ID_SECOND,
    MENU_CHANNEL_ID,
    MENU_CHANNEL_ID_SECOND,
    STATUS_CHANNEL_ID,
    ROOT_PREFIX,
    CATEGORY_ORDER,
    CATEGORY_STYLES,
    ARCHIVE_COLOR,
    INTRO_TITLE,
    INTRO_DESC,
    REG_ARCHIVIST_TITLE,
    REG_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    LEAD_ARCHIVIST_DESC,
    HIGH_COMMAND_TITLE,
    HIGH_COMMAND_DESC,
    TRAINEE_ARCHIVIST_TITLE,
    TRAINEE_ARCHIVIST_DESC,
    EPSILON_LAUNCH_CODE,
    EPSILON_OWNER_CODE,
    EPSILON_XO_CODE,
    EPSILON_FLEET_CODE,
    OMEGA_KEY_FRAGMENT_1,
    OMEGA_KEY_FRAGMENT_2,
    OMEGA_BACKUP_PATH,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_ASSISTANT_ID,
    OWNER_ROLE_ID,
    XO_ROLE_ID,
    FLEET_ADMIRAL_ROLE_ID,
    UPLOAD_CHANNEL_ID,
    LAZARUS_CHANNEL_ID,
    CLEARANCE_REQUESTS_CHANNEL_ID,
    LEAD_NOTIFICATION_CHANNEL_ID,
    REPORT_REPLY_CHANNEL_ID,
    SECURITY_LOG_CHANNEL_ID,
    LEAD_ARCHIVIST_ROLE_ID,
    CLEARANCE_APPROVER_ROLE_ID,
    ARCHIVIST_ROLE_ID,
    TRAINEE_ROLE_ID,
    HIGH_COMMAND_ROLE_ID,
    LEVEL1_ROLE_ID,
    LEVEL2_ROLE_ID,
    LEVEL3_ROLE_ID,
    LEVEL4_ROLE_ID,
    LEVEL5_ROLE_ID,
    CLASSIFIED_ROLE_ID,
)


DEFAULT_CONFIG: Dict[str, Any] = {
    "TOKEN": TOKEN,
    "GUILD_ID": GUILD_ID,
    "MENU_CHANNEL_ID": MENU_CHANNEL_ID,
    "STATUS_CHANNEL_ID": STATUS_CHANNEL_ID,
    "ROOT_PREFIX": ROOT_PREFIX,
    "CATEGORY_ORDER": CATEGORY_ORDER,
    "CATEGORY_STYLES": CATEGORY_STYLES,
    "ARCHIVE_COLOR": ARCHIVE_COLOR,
    "INTRO_TITLE": INTRO_TITLE,
    "INTRO_DESC": INTRO_DESC,
    "ROOT_FOOTER": "SPECTRE Archive Console",
    "ROOT_THUMBNAIL": None,
    "ROOT_BUTTONS": {
        "enter": {"label": "Enter Archive", "style": "primary"},
        "refresh": {"label": "Refresh", "style": "primary"},
        "archivist": {"label": "Archivist Menu", "style": "secondary"},
        "help": {"label": "Help", "style": "danger"},
    },
    "EPSILON_LAUNCH_CODE": EPSILON_LAUNCH_CODE,
    "EPSILON_OWNER_CODE": EPSILON_OWNER_CODE,
    "EPSILON_XO_CODE": EPSILON_XO_CODE,
    "EPSILON_FLEET_CODE": EPSILON_FLEET_CODE,
    "OMEGA_KEY_FRAGMENT_1": OMEGA_KEY_FRAGMENT_1,
    "OMEGA_KEY_FRAGMENT_2": OMEGA_KEY_FRAGMENT_2,
    "OMEGA_BACKUP_PATH": OMEGA_BACKUP_PATH,
    "LLM_API_KEY": LLM_API_KEY,
    "LLM_MODEL": LLM_MODEL,
    "LLM_ASSISTANT_ID": LLM_ASSISTANT_ID,
    "OWNER_ROLE_ID": OWNER_ROLE_ID,
    "XO_ROLE_ID": XO_ROLE_ID,
    "FLEET_ADMIRAL_ROLE_ID": FLEET_ADMIRAL_ROLE_ID,
    "UPLOAD_CHANNEL_ID": UPLOAD_CHANNEL_ID,
    "LAZARUS_CHANNEL_ID": LAZARUS_CHANNEL_ID,
    "CLEARANCE_REQUESTS_CHANNEL_ID": CLEARANCE_REQUESTS_CHANNEL_ID,
    "LEAD_NOTIFICATION_CHANNEL_ID": LEAD_NOTIFICATION_CHANNEL_ID,
    "REPORT_REPLY_CHANNEL_ID": REPORT_REPLY_CHANNEL_ID,
    "SECURITY_LOG_CHANNEL_ID": SECURITY_LOG_CHANNEL_ID,
    "LEAD_ARCHIVIST_ROLE_ID": LEAD_ARCHIVIST_ROLE_ID,
    "CLEARANCE_APPROVER_ROLE_ID": CLEARANCE_APPROVER_ROLE_ID,
    "ARCHIVIST_ROLE_ID": ARCHIVIST_ROLE_ID,
    "TRAINEE_ROLE_ID": TRAINEE_ROLE_ID,
    "HIGH_COMMAND_ROLE_ID": HIGH_COMMAND_ROLE_ID,
}


# Mapping of dashboard-defined logging channels to legacy configuration keys.
# Multiple legacy keys may map to a single dashboard field to maintain
# historical behaviour across subsystems that previously shared a channel.
_CHANNEL_KEY_TARGETS: dict[str, tuple[str, ...]] = {
    "status_log": ("STATUS_CHANNEL_ID",),
    "moderation_log": (
        "REPORT_REPLY_CHANNEL_ID",
        "CLEARANCE_REQUESTS_CHANNEL_ID",
    ),
    "admin_log": (
        "SECURITY_LOG_CHANNEL_ID",
        "LEAD_NOTIFICATION_CHANNEL_ID",
    ),
    "menu_home": ("MENU_CHANNEL_ID",),
    "status_updates": ("STATUS_CHANNEL_ID",),
    "upload": ("UPLOAD_CHANNEL_ID",),
    "lazarus": ("LAZARUS_CHANNEL_ID",),
    "clearance_requests": ("CLEARANCE_REQUESTS_CHANNEL_ID",),
    "lead_notifications": ("LEAD_NOTIFICATION_CHANNEL_ID",),
    "report_replies": ("REPORT_REPLY_CHANNEL_ID",),
    "security_log": ("SECURITY_LOG_CHANNEL_ID",),
}

_LOGGING_CHANNEL_KEYS = {"status_log", "moderation_log", "admin_log"}

_ROLE_KEY_TARGETS: dict[str, tuple[str, ...]] = {
    "owner": ("OWNER_ROLE_ID",),
    "xo": ("XO_ROLE_ID",),
    "fleet_admiral": ("FLEET_ADMIRAL_ROLE_ID",),
    "lead_archivist": ("LEAD_ARCHIVIST_ROLE_ID",),
    "clearance_approver": ("CLEARANCE_APPROVER_ROLE_ID",),
    "archivist": ("ARCHIVIST_ROLE_ID",),
    "trainee": ("TRAINEE_ROLE_ID",),
    "high_command": ("HIGH_COMMAND_ROLE_ID",),
}


_LEVEL_FALLBACKS: dict[int, int] = {
    level: role_id
    for level, role_id in {
        1: LEVEL1_ROLE_ID,
        2: LEVEL2_ROLE_ID,
        3: LEVEL3_ROLE_ID,
        4: LEVEL4_ROLE_ID,
        5: LEVEL5_ROLE_ID,
        6: CLASSIFIED_ROLE_ID,
    }.items()
    if role_id
}


# Location of the persistent configuration file.  Storing this as an absolute
# path simplifies reloading and avoids repeatedly resolving the module
# directory.
_MODULE_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _MODULE_DIR / "server_configs.json"
_CONFIG_MTIME = 0.0

# Cache file used to persist remote dashboard configurations.  This allows the
# bot to recover the most recent settings when restarting in environments
# without immediate access to the remote storage bucket (for example, during
# transient network outages or while credentials are temporarily unavailable).
_REMOTE_CACHE_PATH = _MODULE_DIR / "server_configs.cache.json"


# The cached remote file mirrors the on-disk structure used by the
# configuration dashboard.  Keys are stored as strings for compatibility with
# JSON serialization but converted back to integers when read.
def _load_cached_remote_configs(path: Path | None = None) -> Dict[int, dict]:
    target = path or _REMOTE_CACHE_PATH
    try:
        data = json.loads(target.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:  # pragma: no cover - defensive against manual edits
        return {}

    cached: Dict[int, dict] = {}
    for guild_id_str, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        try:
            gid = int(guild_id_str)
        except (TypeError, ValueError):
            continue
        cached[gid] = cfg
    return cached


def _get_cached_remote_config(guild_id: int, path: Path | None = None) -> dict | None:
    cached = _load_cached_remote_configs(path)
    return cached.get(int(guild_id))


def _store_cached_remote_config(guild_id: int, data: dict, path: Path | None = None) -> None:
    target = path or _REMOTE_CACHE_PATH
    try:
        current = _load_cached_remote_configs(target)
        current[int(guild_id)] = data
        serialisable = {str(key): value for key, value in current.items()}
        target.write_text(json.dumps(serialisable, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to persist cached config for guild %s", guild_id)


logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Container for per-guild configuration."""

    settings: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any | None = None) -> Any:
        return self.settings.get(key, default)


def _normalise_root_prefix(value: Any) -> str | None:
    """Return ``value`` cleaned for use as ``ROOT_PREFIX``."""

    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return ""
    return cleaned.strip("/")


def normalise_root_prefix(value: Any) -> str | None:
    """Public wrapper for :func:`_normalise_root_prefix`."""

    return _normalise_root_prefix(value)


def _normalise_links(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code_value = entry.get("code")
        root_value = entry.get("root_prefix")
        code = str(code_value).strip().upper() if code_value is not None else ""
        root = _normalise_root_prefix(root_value)
        if not code or not root:
            continue
        guild_raw = entry.get("guild_id")
        guild_id = str(guild_raw).strip() if guild_raw is not None else ""
        key = (code, root, guild_id or None)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, Any] = {"code": code, "root_prefix": root}
        if guild_id:
            payload["guild_id"] = guild_id
        name_raw = entry.get("name")
        if isinstance(name_raw, str):
            name_clean = name_raw.strip()
            if name_clean:
                payload["name"] = name_clean
        cleaned.append(payload)
    return cleaned


def default_root_prefix_for(guild_id: int, base: Any | None = None) -> str:
    """Return a deterministic archive root prefix for ``guild_id``.

    The helper ensures every guild receives a dedicated storage prefix by
    appending the guild identifier to ``base`` (or the global
    :data:`ROOT_PREFIX` when ``base`` is not provided).  Existing suffixes are
    preserved to avoid duplicating identifiers in the final path.
    """

    try:
        gid_int = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("guild_id must be an integer") from exc

    candidate = _normalise_root_prefix(base)
    if candidate is None:
        candidate = _normalise_root_prefix(ROOT_PREFIX)

    if not candidate:
        candidate = "dossiers"

    parts = [segment for segment in str(candidate).split("/") if segment]
    gid_str = str(gid_int)
    if not parts or parts[-1] != gid_str:
        parts.append(gid_str)
    return "/".join(parts)


def _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    # Work on a shallow copy so callers retaining a reference to ``override``
    # are not surprised by in-place modifications.
    adjusted = dict(override)

    root_prefix = _normalise_root_prefix(adjusted.get("ROOT_PREFIX"))
    if root_prefix is None:
        archive_cfg = adjusted.get("archive")
        if isinstance(archive_cfg, dict):
            root_prefix = _normalise_root_prefix(archive_cfg.get("root_prefix"))
    if root_prefix is not None:
        adjusted["ROOT_PREFIX"] = root_prefix

    merged.update(adjusted)
    merged["CATEGORY_ORDER"] = list(CATEGORY_ORDER)
    merged["CATEGORY_STYLES"] = dict(CATEGORY_STYLES)
    return _apply_dashboard_overrides(merged)


def _coerce_int(value: Any) -> int | None:
    """Return ``value`` coerced to ``int`` when possible."""

    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        as_str = str(value).strip()
    except Exception:
        return None
    if not as_str:
        return None
    try:
        return int(as_str, 10)
    except ValueError:
        return None


def _coerce_str(value: Any, *, limit: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip()
    return cleaned


def _unique_int_sequence(values: Iterable[Any]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for candidate in values:
        coerced = _coerce_int(candidate)
        if coerced is None or coerced in seen:
            continue
        seen.add(coerced)
        ordered.append(coerced)
    return ordered


def _apply_dashboard_overrides(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Inject derived values sourced from the configuration dashboard."""

    derived = dict(settings)

    channels = derived.get("channels")
    logging_map: dict[str, int] = {}
    channel_assignments: dict[str, int] = {}
    if isinstance(channels, dict):
        for dashboard_key, legacy_keys in _CHANNEL_KEY_TARGETS.items():
            channel_id = _coerce_int(channels.get(dashboard_key))
            if channel_id is None:
                continue
            channel_assignments[dashboard_key] = channel_id
            if dashboard_key in _LOGGING_CHANNEL_KEYS:
                logging_map[dashboard_key] = channel_id
            for legacy_key in legacy_keys:
                derived[legacy_key] = channel_id
    if logging_map:
        derived["DASHBOARD_LOGGING_CHANNELS"] = logging_map
    if channel_assignments:
        derived["DASHBOARD_CHANNEL_ASSIGNMENTS"] = channel_assignments

    clearance = derived.get("clearance")
    levels_map: dict[int, dict[str, Any]] = {}
    if isinstance(clearance, dict):
        raw_levels = clearance.get("levels")
        if isinstance(raw_levels, dict):
            for level_key, entry in raw_levels.items():
                try:
                    level_int = int(level_key)
                except (TypeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                roles = entry.get("roles")
                cleaned_roles = _unique_int_sequence(roles or [])
                name = entry.get("name") if isinstance(entry.get("name"), str) else None
                if cleaned_roles or name:
                    levels_map[level_int] = {
                        "name": name,
                        "roles": cleaned_roles,
                    }
                if cleaned_roles and 1 <= level_int <= 5:
                    derived[f"LEVEL{level_int}_ROLE_ID"] = cleaned_roles[0]
                if cleaned_roles and level_int == 6:
                    derived["CLASSIFIED_ROLE_ID"] = cleaned_roles[0]
    if levels_map:
        derived["DASHBOARD_CLEARANCE_LEVELS"] = levels_map

        ordered_roles: list[int] = []
        for level in sorted(levels_map):
            ordered_roles.extend(levels_map[level].get("roles", []))
        if ordered_roles:
            derived["DASHBOARD_CLEARANCE_ROLE_ORDER"] = ordered_roles

        # Align historical single-role identifiers with the configured levels.
        level_primary = {
            5: "LEAD_ARCHIVIST_ROLE_ID",
            3: "ARCHIVIST_ROLE_ID",
            1: "TRAINEE_ROLE_ID",
        }
        for level, key in level_primary.items():
            roles = levels_map.get(level, {}).get("roles")
            if roles:
                derived[key] = roles[0]

    roles_cfg = derived.get("roles")
    role_assignments: dict[str, int] = {}
    if isinstance(roles_cfg, dict):
        for dashboard_key, legacy_keys in _ROLE_KEY_TARGETS.items():
            role_id = _coerce_int(roles_cfg.get(dashboard_key))
            if role_id is None:
                continue
            role_assignments[dashboard_key] = role_id
            for legacy_key in legacy_keys:
                derived[legacy_key] = role_id
    if role_assignments:
        derived["DASHBOARD_ROLE_ASSIGNMENTS"] = role_assignments

    archive_cfg = derived.get("archive")
    if isinstance(archive_cfg, dict):
        menu_cfg = archive_cfg.get("menu")
        if isinstance(menu_cfg, dict):
            title = _coerce_str(menu_cfg.get("title"), limit=256)
            desc = _coerce_str(menu_cfg.get("description"), limit=4000)
            footer = _coerce_str(menu_cfg.get("footer"), limit=512)
            thumb = _coerce_str(menu_cfg.get("thumbnail"), limit=512)
            if title:
                derived["INTRO_TITLE"] = title
            if desc:
                derived["INTRO_DESC"] = desc
            if footer:
                derived["ROOT_FOOTER"] = footer
            if thumb:
                derived["ROOT_THUMBNAIL"] = thumb
        consoles_cfg = archive_cfg.get("consoles")
        if isinstance(consoles_cfg, dict):
            def _apply_console_override(entry_key: str, title_key: str, desc_key: str) -> None:
                entry = consoles_cfg.get(entry_key)
                if not isinstance(entry, dict):
                    return
                title = _coerce_str(entry.get("title"), limit=256)
                desc = _coerce_str(entry.get("description"), limit=4000)
                if title:
                    derived[title_key] = title
                if desc:
                    derived[desc_key] = desc

            _apply_console_override("regular", "REG_ARCHIVIST_TITLE", "REG_ARCHIVIST_DESC")
            _apply_console_override("lead", "LEAD_ARCHIVIST_TITLE", "LEAD_ARCHIVIST_DESC")
            _apply_console_override("high_command", "HIGH_COMMAND_TITLE", "HIGH_COMMAND_DESC")
            _apply_console_override("trainee", "TRAINEE_ARCHIVIST_TITLE", "TRAINEE_ARCHIVIST_DESC")

        access_sequence_cfg = archive_cfg.get("access_sequence")
        if isinstance(access_sequence_cfg, dict):
            enabled = access_sequence_cfg.get("enabled")
            if isinstance(enabled, bool):
                derived["ACCESS_SEQUENCE_ENABLED"] = enabled

            chance = access_sequence_cfg.get("chance_percent")
            if isinstance(chance, str):
                chance = chance.strip()
            try:
                chance_value = float(chance)
            except (TypeError, ValueError):
                chance_value = None
            if chance_value is not None:
                derived["ACCESS_SEQUENCE_CHANCE"] = max(0.0, min(100.0, chance_value))

    admin_cfg = derived.get("admin")
    if isinstance(admin_cfg, dict):
        log_channel = _coerce_int(admin_cfg.get("log_channel"))
        if log_channel is not None:
            derived["ADMIN_LOG_CHANNEL_ID"] = log_channel

        audit_events_cfg = admin_cfg.get("audit_events")
        if isinstance(audit_events_cfg, dict):
            cleaned_audit_events = {
                key: value
                for key, value in audit_events_cfg.items()
                if isinstance(value, bool)
            }
            if cleaned_audit_events:
                derived["ADMIN_AUDIT_EVENTS"] = cleaned_audit_events

        safeguards_cfg = admin_cfg.get("safeguards")
        if isinstance(safeguards_cfg, dict):
            cleaned_safeguards = {
                key: value
                for key, value in safeguards_cfg.items()
                if isinstance(value, bool)
            }
            if cleaned_safeguards:
                derived["ADMIN_SAFEGUARDS"] = cleaned_safeguards

        safeguard_config_cfg = admin_cfg.get("safeguard_config")
        if isinstance(safeguard_config_cfg, dict):
            derived["ADMIN_SAFEGUARD_CONFIG"] = dict(safeguard_config_cfg)

    protocols_cfg = derived.get("protocols")
    if isinstance(protocols_cfg, dict):
        epsilon_cfg = protocols_cfg.get("epsilon")
        if isinstance(epsilon_cfg, dict):
            launch = _coerce_str(epsilon_cfg.get("launch_code"), limit=128)
            owner = _coerce_str(epsilon_cfg.get("owner_code"), limit=128)
            xo = _coerce_str(epsilon_cfg.get("xo_code"), limit=128)
            fleet = _coerce_str(epsilon_cfg.get("fleet_code"), limit=128)
            if launch:
                derived["EPSILON_LAUNCH_CODE"] = launch
            if owner:
                derived["EPSILON_OWNER_CODE"] = owner
            if xo:
                derived["EPSILON_XO_CODE"] = xo
            if fleet:
                derived["EPSILON_FLEET_CODE"] = fleet

        omega_cfg = protocols_cfg.get("omega")
        if isinstance(omega_cfg, dict):
            frag_one = _coerce_str(omega_cfg.get("fragment_one"), limit=128)
            frag_two = _coerce_str(omega_cfg.get("fragment_two"), limit=128)
            if frag_one:
                derived["OMEGA_KEY_FRAGMENT_1"] = frag_one
            if frag_two:
                derived["OMEGA_KEY_FRAGMENT_2"] = frag_two

    return derived


def load_server_configs(path: str | os.PathLike[str] = _CONFIG_PATH) -> Dict[int, ServerConfig]:
    """Load per-guild configs from a JSON file.

    The file should map guild IDs to dicts of overriding configuration values.
    Missing files result in a mapping containing default configurations for
    ``GUILD_ID`` and ``GUILD_ID_SECOND`` (if provided).
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        configs: Dict[int, ServerConfig] = {
            GUILD_ID: ServerConfig(_apply_dashboard_overrides(dict(DEFAULT_CONFIG)))
        }
        if GUILD_ID_SECOND:
            second_cfg = _apply_dashboard_overrides(dict(DEFAULT_CONFIG))
            second_cfg["GUILD_ID"] = GUILD_ID_SECOND
            second_cfg["MENU_CHANNEL_ID"] = MENU_CHANNEL_ID_SECOND
            configs[GUILD_ID_SECOND] = ServerConfig(second_cfg)
        return configs

    data = json.loads(cfg_path.read_text())
    configs: Dict[int, ServerConfig] = {}
    for guild_id_str, cfg in data.items():
        try:
            gid = int(guild_id_str)
        except ValueError:
            continue
        merged = _merge_config(DEFAULT_CONFIG, cfg)
        merged["GUILD_ID"] = gid
        configs[gid] = ServerConfig(merged)

    if GUILD_ID not in configs:
        default_cfg = _apply_dashboard_overrides(dict(DEFAULT_CONFIG))
        default_cfg["GUILD_ID"] = GUILD_ID
        configs[GUILD_ID] = ServerConfig(default_cfg)

    if GUILD_ID_SECOND and GUILD_ID_SECOND not in configs:
        second_cfg = _apply_dashboard_overrides(dict(DEFAULT_CONFIG))
        second_cfg["GUILD_ID"] = GUILD_ID_SECOND
        second_cfg["MENU_CHANNEL_ID"] = MENU_CHANNEL_ID_SECOND
        configs[GUILD_ID_SECOND] = ServerConfig(second_cfg)

    return configs

SERVER_CONFIGS = load_server_configs()
try:
    _CONFIG_MTIME = _CONFIG_PATH.stat().st_mtime
except FileNotFoundError:
    _CONFIG_MTIME = 0.0


def reload_server_configs() -> None:
    """Reload the global ``SERVER_CONFIGS`` mapping from disk.

    This function updates the internal modification timestamp so subsequent
    calls to :func:`get_server_config` can detect further changes.
    """

    global SERVER_CONFIGS, _CONFIG_MTIME
    SERVER_CONFIGS = load_server_configs()
    try:
        _CONFIG_MTIME = _CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        _CONFIG_MTIME = 0.0


def _maybe_reload() -> None:
    """Reload configurations if the backing file changed on disk."""

    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        mtime = 0.0
    if mtime != _CONFIG_MTIME:
        reload_server_configs()


def _default_config_for(guild_id: int) -> ServerConfig:
    base = _apply_dashboard_overrides(dict(DEFAULT_CONFIG))
    base["GUILD_ID"] = guild_id
    return ServerConfig(base)


def get_server_config(guild_id: int) -> ServerConfig | dict:
    """Retrieve the configuration for a guild.

    The remote dashboard is treated as the source of truth.  When a remote
    document is available it is preferred over any legacy ``server_configs``
    file that may still be present on disk.  Local files remain as a
    compatibility fallback so existing installations without the dashboard
    continue to function.
    """

    cached_remote = _get_cached_remote_config(guild_id)

    try:
        remote_cfg = _get_remote_config(guild_id)
    except FileNotFoundError:
        remote_cfg = None
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to load remote configuration for guild %s", guild_id)
        remote_cfg = None

    if remote_cfg is not None:
        _store_cached_remote_config(guild_id, remote_cfg)
        return remote_cfg

    if _CONFIG_PATH.exists():
        _maybe_reload()
        return SERVER_CONFIGS.get(guild_id, _default_config_for(guild_id))

    if cached_remote is not None:
        return cached_remote

    return _default_config_for(guild_id)


# ===== Remote guild config retrieval =====
_CACHE: dict[str, dict] = {}
_TTL = 30  # seconds

def invalidate_config(guild_id: int | str | None = None):
    if guild_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(str(guild_id), None)


def nuclear_keys_configured(guild_id: int | str) -> tuple[bool, bool]:
    """Return (epsilon_configured, omega_configured) for the guild.

    Commands should be disabled when keys are not explicitly set for security.
    """
    try:
        doc, _ = read_json(f"guild-configs/{str(guild_id)}.json", with_etag=True)
    except FileNotFoundError:
        return False, False
    if doc is None:
        return False, False
    settings = doc.get("settings") or {}
    protocols = settings.get("protocols") or {}
    epsilon = protocols.get("epsilon") or {}
    omega = protocols.get("omega") or {}
    eps_ok = bool(_coerce_str(epsilon.get("launch_code"), limit=128))
    omega_ok = bool(_coerce_str(omega.get("fragment_one"), limit=128)) and bool(
        _coerce_str(omega.get("fragment_two"), limit=128)
    )
    return eps_ok, omega_ok


def _get_remote_config(guild_id: int | str) -> dict:
    gid = str(guild_id)
    now = time.time()
    cached = _CACHE.get(gid)
    if cached and now - cached["t"] < _TTL:
        return cached["data"]
    doc, _etag = read_json(f"guild-configs/{gid}.json", with_etag=True)
    if doc is None:
        raise FileNotFoundError(f"guild-configs/{gid}.json")
    raw = doc or {}
    remote_settings = dict(raw.get("settings", {}))
    archive_cfg = raw.get("archive")
    archive_settings = remote_settings.get("archive") if isinstance(remote_settings.get("archive"), dict) else None
    archive_copy: dict[str, Any] = {}
    if isinstance(archive_cfg, dict):
        archive_copy.update(archive_cfg)
    if isinstance(archive_settings, dict):
        archive_copy.update(archive_settings)
    archive_copy["links"] = _normalise_links(archive_copy.get("links"))
    remote_settings["archive"] = archive_copy
    if "ROOT_PREFIX" not in remote_settings:
        root_pref = _normalise_root_prefix(archive_copy.get("root_prefix")) if archive_copy else None
        if root_pref is not None:
            remote_settings["ROOT_PREFIX"] = root_pref
    if "ROOT_PREFIX" not in remote_settings:
        root_pref = _normalise_root_prefix(raw.get("ROOT_PREFIX"))
        if root_pref is not None:
            remote_settings["ROOT_PREFIX"] = root_pref
    if "ROOT_PREFIX" not in remote_settings:
        try:
            remote_settings["ROOT_PREFIX"] = default_root_prefix_for(int(gid))
        except ValueError:
            remote_settings["ROOT_PREFIX"] = default_root_prefix_for(gid)
    data = _merge_config(DEFAULT_CONFIG, remote_settings)
    data["GUILD_ID"] = int(gid)
    _CACHE[gid] = {"t": now, "data": data}
    return data


def _coerce_config_mapping(config: ServerConfig | dict | None) -> Dict[str, Any]:
    if isinstance(config, ServerConfig):
        return dict(config.settings)
    if isinstance(config, dict):
        return dict(config)
    return {}


def _extract_clearance_levels(data: Dict[str, Any]) -> dict[int, dict[str, Any]]:
    levels: dict[int, dict[str, Any]] = {}
    raw = data.get("DASHBOARD_CLEARANCE_LEVELS")
    if isinstance(raw, dict):
        for level_key, entry in raw.items():
            try:
                level_int = int(level_key)
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            roles = _unique_int_sequence(entry.get("roles", []))
            name = entry.get("name") if isinstance(entry.get("name"), str) else None
            levels[level_int] = {"name": name, "roles": roles}
    return levels


def get_dashboard_logging_channels(guild_id: int | None = None) -> dict[str, int]:
    target = int(guild_id) if guild_id is not None else GUILD_ID
    cfg = _coerce_config_mapping(get_server_config(target))
    result: dict[str, int] = {}
    raw = cfg.get("DASHBOARD_LOGGING_CHANNELS")
    if isinstance(raw, dict):
        for key, value in raw.items():
            channel_id = _coerce_int(value)
            if channel_id is not None:
                result[str(key)] = channel_id
    return result


def get_clearance_levels(guild_id: int | None = None) -> dict[int, dict[str, Any]]:
    target = int(guild_id) if guild_id is not None else GUILD_ID
    cfg = _coerce_config_mapping(get_server_config(target))
    return _extract_clearance_levels(cfg)


def get_roles_for_level(level: int, guild_id: int | None = None) -> list[int]:
    try:
        level_int = int(level)
    except (TypeError, ValueError):
        return []
    roles = get_clearance_levels(guild_id).get(level_int, {}).get("roles") or []
    if roles:
        return list(roles)
    fallback = _LEVEL_FALLBACKS.get(level_int)
    return [fallback] if fallback else []


def get_min_clearance_level_for_roles(
    role_ids: set[int], guild_id: int | None = None
) -> int | None:
    """Return the minimum clearance level among the given role IDs.

    Used to display a clearance indicator for files (e.g. in select menus).
    Returns None if no role maps to a configured level.
    """
    if not role_ids:
        return None
    role_to_level: dict[int, int] = {}
    for level in (1, 2, 3, 4, 5, 6):
        for rid in get_roles_for_level(level, guild_id):
            if rid and rid not in role_to_level:
                role_to_level[rid] = level
    levels = [role_to_level[rid] for rid in role_ids if rid in role_to_level]
    return min(levels) if levels else None


def get_assignable_roles(guild_id: int | None = None) -> list[int]:
    levels = get_clearance_levels(guild_id)
    ordered: list[int] = []
    for _level, entry in sorted(levels.items()):
        for role_id in entry.get("roles", []):
            if role_id not in ordered:
                ordered.append(role_id)
    if ordered:
        return ordered
    return _unique_int_sequence(
        [
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
        ]
    )
