"""Entrypoint for the Spectre Discord bot runtime."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable
from packaging.version import InvalidVersion, Version

import nextcord

from acl import get_required_roles
from archivist import handle_upload
from constants import (
    ARCHIVIST_ROLE_ID,
    CLASSIFIED_ROLE_ID,
    FLEET_ADMIRAL_ROLE_ID,
    HIGH_COMMAND_ROLE_ID,
    OWNER_ROLE_ID,
    ROOT_PREFIX,
    TRAINEE_ARCHIVIST_DESC,
    TRAINEE_ARCHIVIST_TITLE,
    TRAINEE_ROLE_ID,
    UPLOAD_CHANNEL_ID,
    XO_ROLE_ID,
)
import utils
from dossier import list_archived_categories, list_items_recursive
from keepalive import start_keepalive
from registration import start_registration
from spectre.commands import archivist as archivist_commands
from spectre.commands.archivist import dispatch_archivist_console
from spectre.commands.dossier_images import (
    _autocomplete_items,
    set_file_image_item_autocomplete,
)
from spectre.commands.protocols import (
    execute_epsilon_actions,
    protocol_epsilon_command,
)
from spectre.commands.operators import create_id_command, show_id_command
from spectre.runtime import run as run_spectre
from spectre.tasks.backups import GREEK_LETTERS, backup_all, restore_backup
from storage_spaces import delete_file, ensure_dir, list_dir
from views import CategorySelect


logger = logging.getLogger("spectre")

# Mirror the mutable storage directory so legacy tests can override it directly.
DOSSIERS_DIR = utils.DOSSIERS_DIR


_action_log_handler: Callable[[str, bool], Awaitable[None]] | None = None


def set_action_log_handler(
    handler: Callable[[str, bool], Awaitable[None]] | None,
) -> None:
    """Configure the runtime action logger used by legacy modules.

    Legacy modules still import ``main.log_action`` directly. During modern
    runtime startup we inject the richer ``SpectreContext.log_action`` handler
    so those modules publish into configured admin channels.
    """

    global _action_log_handler
    _action_log_handler = handler


async def log_action(message: str, *, broadcast: bool = True) -> None:
    """Lightweight logger hook used by unit tests.

    The full :class:`spectre.context.SpectreContext` implementation provides a
    richer logging pipeline. For the slim test harness we log to the standard
    logger so behavioural checks continue to work without the bot runtime.
    """

    if _action_log_handler is not None:
        await _action_log_handler(message, broadcast)
        return

    if broadcast:
        logger.info(message)
    else:
        logger.debug(message)


async def protocol_epsilon(interaction):
    """Delegate the protocol epsilon command using a stubbed context."""

    await protocol_epsilon_command(_ProtocolStubContext(), interaction)


def _ensure_nextcord_version() -> None:
    """Guard against running with an unsupported Nextcord release."""

    try:
        parsed = Version(nextcord.__version__)
    except InvalidVersion as exc:  # pragma: no cover - defensive
        raise RuntimeError("Unable to parse Nextcord version") from exc

    required = Version("2.6.0")
    if parsed < required:
        raise RuntimeError("Nextcord 2.6.0+ is required")


async def create_id(interaction):
    """Public shim that delegates to the operators command module."""

    await create_id_command(_ProtocolStubContext(), interaction)


async def show_id(interaction):
    """Display operator IDs using a lightweight context."""

    await show_id_command(_ProtocolStubContext(), interaction)


async def archivist_cmd(interaction):
    """Expose the archivist console command for legacy tests."""

    context = _ProtocolStubContext()

    async def _main_hiccup_proxy(inner_context, inner_interaction):
        return await maybe_simulate_hiccup(inner_interaction)

    original_hiccup = archivist_commands.maybe_simulate_hiccup
    try:
        archivist_commands.maybe_simulate_hiccup = _main_hiccup_proxy
        await archivist_commands.open_archivist_console(context, interaction)
    finally:
        archivist_commands.maybe_simulate_hiccup = original_hiccup


async def maybe_simulate_hiccup(interaction):
    """Compatibility shim for tests monkeypatching main.maybe_simulate_hiccup."""

    return await archivist_commands.maybe_simulate_hiccup(_ProtocolStubContext(), interaction)


async def _backup_action() -> None:
    """Perform a backup and prune old snapshots.

    This keeps the lightweight entrypoint behaviour in sync with the scheduled
    backup task logic used by the full bot runtime while remaining easy to
    monkeypatch in tests.
    """

    _backup_all()
    _prune_backups()


def _backup_all():
    return backup_all(ROOT_PREFIX)


def _restore_backup(path: str) -> None:
    restore_backup(path, ROOT_PREFIX)


def _start_keepalive() -> None:
    start_keepalive()


def _prune_backups(limit: int = 4) -> None:
    try:
        ensure_dir("backups")
        _dirs, files = list_dir("backups", limit=1000)
        names = sorted(f for f, _ in files)
    except Exception:
        return

    while len(names) > limit:
        old = names.pop(0)
        try:
            delete_file(f"backups/{old}")
        except Exception:
            continue


def run() -> None:
    run_spectre()


def main() -> None:
    """Start the keepalive server and launch the bot runtime."""

    _ensure_nextcord_version()
    try:
        _start_keepalive()
    except Exception:
        logger.info("Keepalive server failed to start", exc_info=True)
    run()


class _ProtocolStubContext:
    """Lightweight context used for protocol unit tests."""

    slash_guild_ids: tuple[int, ...] = ()

    async def log_action(self, message: str, *, broadcast: bool = True) -> None:
        await log_action(message, broadcast=broadcast)

    @property
    def settings(self):  # pragma: no cover - compatibility shim
        class _Dummy:
            backup_interval_hours = 1

        return _Dummy()

    @property
    def lazarus_ai(self):  # pragma: no cover - compatibility shim
        class _Dummy:
            def note_backup(self, *_args, **_kwargs):
                return None

        return _Dummy()


__all__ = [
    "_autocomplete_items",
    "_backup_action",
    "_backup_all",
    "_ensure_nextcord_version",
    "_restore_backup",
    "_start_keepalive",
    "CategorySelect",
    "DOSSIERS_DIR",
    "GREEK_LETTERS",
    "UPLOAD_CHANNEL_ID",
    "ARCHIVIST_ROLE_ID",
    "HIGH_COMMAND_ROLE_ID",
    "TRAINEE_ROLE_ID",
    "TRAINEE_ARCHIVIST_TITLE",
    "TRAINEE_ARCHIVIST_DESC",
    "ROOT_PREFIX",
    "list_items_recursive",
    "list_archived_categories",
    "set_file_image_item_autocomplete",
    "get_required_roles",
    "maybe_simulate_hiccup",
    "archivist_cmd",
    "handle_upload",
    "create_id",
    "show_id",
    "start_registration",
    "protocol_epsilon",
    "execute_epsilon_actions",
    "run",
    "set_action_log_handler",
    "main",
    "CLASSIFIED_ROLE_ID",
    "OWNER_ROLE_ID",
    "XO_ROLE_ID",
    "FLEET_ADMIRAL_ROLE_ID",
    "nextcord",
]


if __name__ == "__main__":
    main()
