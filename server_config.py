from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

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
    ARCHIVIST_ROLE_ID,
    TRAINEE_ROLE_ID,
    HIGH_COMMAND_ROLE_ID,
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
    "ROOT_FOOTER": "Glacier Unit-7 Archive Terminal",
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
    "ARCHIVIST_ROLE_ID": ARCHIVIST_ROLE_ID,
    "TRAINEE_ROLE_ID": TRAINEE_ROLE_ID,
    "HIGH_COMMAND_ROLE_ID": HIGH_COMMAND_ROLE_ID,
}


# Location of the persistent configuration file.  Storing this as an absolute
# path simplifies reloading and avoids repeatedly resolving the module
# directory.
_CONFIG_PATH = Path(__file__).resolve().parent / "server_configs.json"
_CONFIG_MTIME = 0.0


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
    return merged


def load_server_configs(path: str | os.PathLike[str] = _CONFIG_PATH) -> Dict[int, ServerConfig]:
    """Load per-guild configs from a JSON file.

    The file should map guild IDs to dicts of overriding configuration values.
    Missing files result in a mapping containing default configurations for
    ``GUILD_ID`` and ``GUILD_ID_SECOND`` (if provided).
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        configs: Dict[int, ServerConfig] = {
            GUILD_ID: ServerConfig(dict(DEFAULT_CONFIG))
        }
        if GUILD_ID_SECOND:
            second_cfg = dict(DEFAULT_CONFIG)
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
        default_cfg = dict(DEFAULT_CONFIG)
        default_cfg["GUILD_ID"] = GUILD_ID
        configs[GUILD_ID] = ServerConfig(default_cfg)

    if GUILD_ID_SECOND and GUILD_ID_SECOND not in configs:
        second_cfg = dict(DEFAULT_CONFIG)
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


def get_server_config(guild_id: int) -> ServerConfig | dict:
    """Retrieve the configuration for a guild.

    When the legacy ``server_configs.json`` file is present the configuration
    is loaded from disk as before.  Otherwise the per-guild JSON is fetched
    from DigitalOcean Spaces and cached briefly.
    """

    if _CONFIG_PATH.exists():
        _maybe_reload()
        return SERVER_CONFIGS.get(guild_id, ServerConfig(dict(DEFAULT_CONFIG)))
    return _get_remote_config(guild_id)


# ===== Remote guild config retrieval =====
_CACHE: dict[str, dict] = {}
_TTL = 30  # seconds

def invalidate_config(guild_id: int | str | None = None):
    if guild_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(str(guild_id), None)


def _get_remote_config(guild_id: int | str) -> dict:
    gid = str(guild_id)
    now = time.time()
    cached = _CACHE.get(gid)
    if cached and now - cached["t"] < _TTL:
        return cached["data"]
    doc, _etag = read_json(f"guild-configs/{gid}.json", with_etag=True)
    raw = doc or {}
    remote_settings = dict(raw.get("settings", {}))
    archive_cfg = raw.get("archive")
    if isinstance(archive_cfg, dict):
        # Preserve the nested archive configuration for UI consumers while also
        # exposing ``ROOT_PREFIX`` to the runtime configuration used by the
        # bot.  The copy ensures we don't accidentally mutate the stored
        # document fetched from Spaces.
        remote_settings.setdefault("archive", dict(archive_cfg))
        if "ROOT_PREFIX" not in remote_settings:
            root_pref = _normalise_root_prefix(archive_cfg.get("root_prefix"))
            if root_pref is not None:
                remote_settings["ROOT_PREFIX"] = root_pref
    if "ROOT_PREFIX" not in remote_settings:
        root_pref = _normalise_root_prefix(raw.get("ROOT_PREFIX"))
        if root_pref is not None:
            remote_settings["ROOT_PREFIX"] = root_pref
    data = _merge_config(DEFAULT_CONFIG, remote_settings)
    data["GUILD_ID"] = int(gid)
    _CACHE[gid] = {"t": now, "data": data}
    return data
