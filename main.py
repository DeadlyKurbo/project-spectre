"""Entrypoint and compatibility layer for the Spectre Discord bot."""

from __future__ import annotations

import os

import nextcord

from acl import get_required_roles, grant_file_clearance, revoke_file_clearance
import archivist as _archivist_module
import constants as _constants_module
from archivist import handle_upload, list_items_recursive
from async_utils import run_blocking
from keepalive import start_keepalive as _start_keepalive
from constants import (
    HIGH_COMMAND_DESC,
    HIGH_COMMAND_TITLE,
    INTRO_DESC,
    INTRO_TITLE,
    LAZARUS_CHANNEL_ID,
    LEAD_ARCHIVIST_DESC,
    LEAD_ARCHIVIST_TITLE,
    ROOT_PREFIX,
    TRAINEE_ARCHIVIST_DESC,
    TRAINEE_ARCHIVIST_TITLE,
    UPLOAD_CHANNEL_ID,
)
from dossier import attach_dossier_image
from registration import start_registration
from utils import DOSSIERS_DIR, list_categories
from views import CategorySelect, RootView

from spectre.application import SpectreApplication
from spectre.commands.archivist import (
    maybe_simulate_hiccup as _maybe_simulate_hiccup,
    open_archivist_console as _open_archivist_console,
)
from spectre.commands.operators import (
    create_id_command as _create_id_command,
    show_id_command as _show_id_command,
)
from spectre.commands import protocols as _protocols_module
from spectre.commands.protocols import (
    apply_protocol_epsilon as _apply_protocol_epsilon,
    omega_directive_command as _omega_directive_command,
    protocol_epsilon_command as _protocol_epsilon_command,
)
from spectre.interactions import build_link_view, guild_id_from_interaction
from spectre.runtime import run
from spectre.tasks import backups as _backups_module
from spectre.tasks.backups import (
    GREEK_LETTERS,
    backup_action as _backup_action_impl,
    backup_all as _backup_all,
    purge_archive_and_backups,
    restore_backup,
)
from spectre.version import ensure_nextcord_version as _ensure_nextcord_version_impl


def _env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return int(raw.strip(), 10)
    except ValueError:
        return fallback


def _load_role_constant(name: str) -> int:
    value = _env_int(name, getattr(_constants_module, name, 0))
    setattr(_constants_module, name, value)
    return value


ARCHIVIST_ROLE_ID = _load_role_constant("ARCHIVIST_ROLE_ID")
LEAD_ARCHIVIST_ROLE_ID = _load_role_constant("LEAD_ARCHIVIST_ROLE_ID")
HIGH_COMMAND_ROLE_ID = _load_role_constant("HIGH_COMMAND_ROLE_ID")
TRAINEE_ROLE_ID = _load_role_constant("TRAINEE_ROLE_ID")
CLASSIFIED_ROLE_ID = _load_role_constant("CLASSIFIED_ROLE_ID")
OWNER_ROLE_ID = _load_role_constant("OWNER_ROLE_ID")
XO_ROLE_ID = _load_role_constant("XO_ROLE_ID")
FLEET_ADMIRAL_ROLE_ID = _load_role_constant("FLEET_ADMIRAL_ROLE_ID")

APPLICATION = SpectreApplication()

bot = APPLICATION.bot
logger = APPLICATION.logger
lazarus_ai = APPLICATION.context.lazarus_ai
TOKEN = APPLICATION.token
GUILD_IDS = APPLICATION.context.guild_ids
settings = APPLICATION.settings

backup_loop = APPLICATION.context.backup_loop


async def log_action(message: str, *, broadcast: bool = True) -> None:
    await APPLICATION.context.log_action(message, broadcast=broadcast)


async def maybe_simulate_hiccup(interaction: nextcord.Interaction) -> bool:
    return await _maybe_simulate_hiccup(APPLICATION.context, interaction)


async def show_id(interaction: nextcord.Interaction) -> None:
    await _show_id_command(APPLICATION.context, interaction)


async def create_id(interaction: nextcord.Interaction) -> None:
    await _create_id_command(APPLICATION.context, interaction)


async def execute_epsilon_actions(guild: nextcord.Guild | None, classified_role: nextcord.Role | None) -> None:
    _sync_protocol_constants()
    await apply_protocol_epsilon(guild, classified_role)
    await run_blocking(purge_archive_and_backups)
    await log_action(" Protocol EPSILON purge executed.")


async def execute_omega_actions(guild: nextcord.Guild | None) -> None:
    _sync_protocol_constants()
    try:
        await run_blocking(restore_backup, _constants_module.OMEGA_BACKUP_PATH)
        await log_action(" Omega Directive restoration executed.")
    except Exception as exc:
        await log_action(f" Omega restore error: {exc}")


async def protocol_epsilon(interaction: nextcord.Interaction) -> None:
    _sync_archivist_constants()
    _sync_protocol_constants()
    await _protocol_epsilon_command(APPLICATION.context, interaction)


async def omega_directive(interaction: nextcord.Interaction) -> None:
    _sync_archivist_constants()
    _sync_protocol_constants()
    await _omega_directive_command(APPLICATION.context, interaction)


async def archivist_cmd(interaction: nextcord.Interaction) -> None:
    _sync_archivist_constants()
    await _open_archivist_console(APPLICATION.context, interaction)


backup_all = _backup_all  # re-export for tests expecting name in main
_backup_all = backup_all


async def _backup_action() -> None:
    original = _backups_module.backup_all
    _backups_module.backup_all = _backup_all
    try:
        await _backup_action_impl(APPLICATION.context)
    finally:
        _backups_module.backup_all = original


_restore_backup = restore_backup


async def set_file_image_item_autocomplete(
    interaction: nextcord.Interaction, item: str
) -> None:
    category = None
    options = interaction.data.get("options", []) if getattr(interaction, "data", None) else []
    for opt in options:
        if opt.get("name") == "category":
            category = opt.get("value")
            break
    choices = await run_blocking(_autocomplete_items, category, item)
    await interaction.response.send_autocomplete(choices)


def _autocomplete_items(
    category: str | None, partial: str, guild_id: int | None = None
) -> list[str]:
    if not category:
        return []
    try:
        try:
            items = list_items_recursive(category, max_items=25, guild_id=guild_id)
        except TypeError:
            items = list_items_recursive(category, max_items=25)
    except FileNotFoundError:
        return []
    partial = (partial or "").lower()
    return [item for item in items if item.lower().startswith(partial)][:25]


async def apply_protocol_epsilon(
    guild: nextcord.Guild, classified_role: nextcord.Role
) -> None:
    _sync_protocol_constants()
    if guild is None or classified_role is None:
        return
    await _apply_protocol_epsilon(guild, classified_role)


_ensure_nextcord_version = _ensure_nextcord_version_impl


def main() -> None:
    """Start the Spectre runtime when executed as a script."""

    logger.info("Starting keepalive HTTP endpoint")
    try:
        _start_keepalive()
    except Exception:
        logger.exception("Keepalive server failed to start")

    logger.info("Launching Spectre runtime")
    run()


if __name__ == "__main__":  # pragma: no cover - manual CLI execution
    main()


def _sync_archivist_constants() -> None:
    _archivist_module.ARCHIVIST_ROLE_ID = _constants_module.ARCHIVIST_ROLE_ID
    _archivist_module.LEAD_ARCHIVIST_ROLE_ID = _constants_module.LEAD_ARCHIVIST_ROLE_ID
    _archivist_module.HIGH_COMMAND_ROLE_ID = _constants_module.HIGH_COMMAND_ROLE_ID
    _archivist_module.TRAINEE_ROLE_ID = _constants_module.TRAINEE_ROLE_ID


def _sync_protocol_constants() -> None:
    _protocols_module.CLASSIFIED_ROLE_ID = _constants_module.CLASSIFIED_ROLE_ID
    _protocols_module.OWNER_ROLE_ID = _constants_module.OWNER_ROLE_ID
    _protocols_module.XO_ROLE_ID = _constants_module.XO_ROLE_ID
    _protocols_module.FLEET_ADMIRAL_ROLE_ID = _constants_module.FLEET_ADMIRAL_ROLE_ID


__all__ = [
    "APPLICATION",
    "TOKEN",
    "GUILD_IDS",
    "bot",
    "logger",
    "lazarus_ai",
    "settings",
    "backup_loop",
    "run",
    "log_action",
    "maybe_simulate_hiccup",
    "show_id",
    "create_id",
    "execute_epsilon_actions",
    "execute_omega_actions",
    "protocol_epsilon",
    "omega_directive",
    "archivist_cmd",
    "get_required_roles",
    "grant_file_clearance",
    "revoke_file_clearance",
    "attach_dossier_image",
    "handle_upload",
    "start_registration",
    "list_categories",
    "DOSSIERS_DIR",
    "list_items_recursive",
    "build_link_view",
    "guild_id_from_interaction",
    "restore_backup",
    "backup_all",
    "_backup_action",
    "_restore_backup",
    "_autocomplete_items",
    "set_file_image_item_autocomplete",
    "purge_archive_and_backups",
    "apply_protocol_epsilon",
    "_ensure_nextcord_version",
    "ROOT_PREFIX",
    "UPLOAD_CHANNEL_ID",
    "nextcord",
    "ARCHIVIST_ROLE_ID",
    "CLASSIFIED_ROLE_ID",
    "FLEET_ADMIRAL_ROLE_ID",
    "HIGH_COMMAND_ROLE_ID",
    "LEAD_ARCHIVIST_ROLE_ID",
    "OWNER_ROLE_ID",
    "XO_ROLE_ID",
    "HIGH_COMMAND_TITLE",
    "HIGH_COMMAND_DESC",
    "INTRO_TITLE",
    "INTRO_DESC",
    "LEAD_ARCHIVIST_TITLE",
    "LEAD_ARCHIVIST_DESC",
    "TRAINEE_ARCHIVIST_TITLE",
    "TRAINEE_ARCHIVIST_DESC",
    "LAZARUS_CHANNEL_ID",
    "TRAINEE_ROLE_ID",
    "GREEK_LETTERS",
    "CategorySelect",
    "RootView",
    "main",
]
