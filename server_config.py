from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from constants import (
    TOKEN,
    GUILD_ID,
    MENU_CHANNEL_ID,
    STATUS_CHANNEL_ID,
    ROSTER_CHANNEL_ID,
    ROOT_PREFIX,
    CATEGORY_ORDER,
    CATEGORY_STYLES,
    ARCHIVE_COLOR,
    SECTION_ZERO_CATEGORIES,
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
    SECTION_ZERO_CHANNEL_ID,
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
    "ROSTER_CHANNEL_ID": ROSTER_CHANNEL_ID,
    "ROOT_PREFIX": ROOT_PREFIX,
    "CATEGORY_ORDER": CATEGORY_ORDER,
    "CATEGORY_STYLES": CATEGORY_STYLES,
    "ARCHIVE_COLOR": ARCHIVE_COLOR,
    "SECTION_ZERO_CATEGORIES": SECTION_ZERO_CATEGORIES,
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
    "SECTION_ZERO_CHANNEL_ID": SECTION_ZERO_CHANNEL_ID,
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
    Missing files result in a mapping containing only the default configuration
    keyed by the default ``GUILD_ID``.
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        return {GUILD_ID: ServerConfig(dict(DEFAULT_CONFIG))}

    data = json.loads(cfg_path.read_text())
    configs: Dict[int, ServerConfig] = {}
    for guild_id_str, cfg in data.items():
        try:
            gid = int(guild_id_str)
        except ValueError:
            continue
        merged = _merge_config(DEFAULT_CONFIG, cfg)
        configs[gid] = ServerConfig(merged)

    if GUILD_ID not in configs:
        configs[GUILD_ID] = ServerConfig(dict(DEFAULT_CONFIG))
    return configs


SERVER_CONFIGS = load_server_configs()


def get_server_config(guild_id: int) -> ServerConfig:
    """Retrieve the configuration for a guild, falling back to defaults."""
    return SERVER_CONFIGS.get(guild_id, ServerConfig(dict(DEFAULT_CONFIG)))
