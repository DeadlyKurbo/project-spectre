from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

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


@dataclass
class ServerConfig:
    """Container for per-guild configuration."""

    settings: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any | None = None) -> Any:
        return self.settings.get(key, default)


def _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged


def load_server_configs(path: str = "server_configs.json") -> Dict[int, ServerConfig]:
    """Load per-guild configs from a JSON file.

    The file should map guild IDs to dicts of overriding configuration values.
    Missing files result in a mapping containing default configurations for
    ``GUILD_ID`` and ``GUILD_ID_SECOND`` (if provided).
    """
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parent / cfg_path
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


def get_server_config(guild_id: int) -> ServerConfig:
    """Retrieve the configuration for a guild, falling back to defaults."""
    return SERVER_CONFIGS.get(guild_id, ServerConfig(dict(DEFAULT_CONFIG)))
