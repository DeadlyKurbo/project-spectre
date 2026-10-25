"""Backup and restoration helpers used by scheduled tasks and commands."""

from __future__ import annotations

import io
import json
import logging
import random
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile

from nextcord.ext import tasks

from storage_spaces import delete_file, ensure_dir, list_dir, read_json, read_text, save_text

from async_utils import run_blocking
from constants import ROOT_PREFIX
from ..context import SpectreContext

_logger = logging.getLogger(__name__)

MAX_BACKUPS_PER_SERVER = 3

GREEK_LETTERS: tuple[str, ...] = (
    "Alpha",
    "Beta",
    "Gamma",
    "Delta",
    "Epsilon",
    "Zeta",
    "Eta",
    "Theta",
    "Iota",
    "Kappa",
    "Lambda",
    "Mu",
    "Nu",
    "Xi",
    "Omicron",
    "Pi",
    "Rho",
    "Sigma",
    "Tau",
    "Upsilon",
    "Phi",
    "Chi",
    "Psi",
    "Omega",
)


def _backup_prefix_for_guild(guild_id: int | None) -> str:
    """Return the backups subfolder for a guild (per-server backup limit)."""
    return f"backups/{guild_id or 'global'}"


def get_latest_backup_path(guild_id: int | None) -> str | None:
    """Return the path to the most recent backup for a guild, or None if none exist."""
    backup_prefix = _backup_prefix_for_guild(guild_id)
    try:
        _dirs, files = list_dir(backup_prefix, limit=1000)
    except Exception:
        return None
    names = [f for f, _ in files if f.endswith(".json") and f.startswith("Backup protocol ")]
    if not names:
        return None
    names.sort(reverse=True)
    return f"{backup_prefix}/{names[0]}"


def backup_all(
    root_prefix: str = ROOT_PREFIX,
    guild_id: int | None = None,
) -> tuple[datetime, str]:
    """Create a full backup (archive + clearance + guild config) under ``backups/{guild_id}/``."""

    def _add_entry(tmp: io.TextIOWrapper, first: list[bool], path: str, content: str) -> None:
        if not first[0]:
            tmp.write(",")
        first[0] = False
        tmp.write(json.dumps(path))
        tmp.write(":")
        tmp.write(json.dumps(content))

    with SpooledTemporaryFile(max_size=5_000_000) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8") as tmp:
            tmp.write("{")
            first = [True]

            def _recurse(pref: str) -> None:
                dirs, files = list_dir(pref, limit=10000)
                for fname, _ in files:
                    path = f"{pref}/{fname}" if pref else fname
                    try:
                        content = read_text(path)
                    except Exception:
                        continue
                    _add_entry(tmp, first, path, content)
                for directory in dirs:
                    _recurse(f"{pref}/{directory.strip('/')}")

            _recurse(root_prefix)

            # Include guild config (channels, roles, clearance levels, etc.)
            if guild_id is not None:
                config_path = f"guild-configs/{guild_id}.json"
                try:
                    doc, _ = read_json(config_path, with_etag=True)
                    if doc is not None:
                        _add_entry(
                            tmp,
                            first,
                            config_path,
                            json.dumps(doc, ensure_ascii=False, indent=2),
                        )
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    _logger.warning("Could not include guild config in backup: %s", exc)

            tmp.write("}")
            tmp.flush()
            raw.seek(0)

            ts = datetime.now(UTC)
            backup_prefix = _backup_prefix_for_guild(guild_id)
            ensure_dir(backup_prefix)
            name = random.choice(GREEK_LETTERS)
            stamp = ts.strftime("%Y%m%dT%H%M%S")
            fname = f"{backup_prefix}/Backup protocol {name}-{stamp}.json"
            save_text(fname, raw, "application/json; charset=utf-8")
    return ts, fname


def restore_backup(
    path: str,
    root_prefix: str | None = None,
    guild_id: int | None = None,
) -> None:
    """Load a full archive backup from ``path`` and replace existing files."""

    if root_prefix is None:
        root_prefix = _get_root_prefix_for_guild(guild_id)

    data = read_json(path)
    existing: list[str] = []

    def _collect(pref: str) -> None:
        try:
            dirs, files = list_dir(pref, limit=10000)
        except Exception:
            return
        for fname, _ in files:
            existing.append(f"{pref}/{fname}" if pref else fname)
        for directory in dirs:
            _collect(f"{pref}/{directory.strip('/')}")

    _collect(root_prefix)

    for fname in set(existing) - set(data.keys()):
        try:
            delete_file(fname)
        except Exception:
            pass

    for fname, content in data.items():
        save_text(fname, content)


def purge_archive_and_backups(
    root_prefix: str | None = None,
    guild_id: int | None = None,
) -> None:
    """Remove all files from the archive and backup storage.

    When guild_id is provided, purges only that guild's archive root and
    backups. Otherwise purges the default root and entire backups folder.
    """
    if root_prefix is None:
        root_prefix = _get_root_prefix_for_guild(guild_id)

    def _purge(prefix: str) -> None:
        try:
            dirs, files = list_dir(prefix, limit=10000)
        except Exception:
            return
        for fname, _ in files:
            try:
                delete_file(f"{prefix}/{fname}" if prefix else fname)
            except Exception:
                continue
        for directory in dirs:
            _purge(f"{prefix}/{directory.strip('/')}")

    _purge(root_prefix)
    if guild_id is not None:
        _purge(_backup_prefix_for_guild(guild_id))
    else:
        _purge("backups")


def _get_root_prefix_for_guild(guild_id: int | None) -> str:
    """Return the archive root prefix for a guild."""
    if guild_id is None:
        return ROOT_PREFIX
    from server_config import get_server_config
    cfg = get_server_config(guild_id)
    root = cfg.get("ROOT_PREFIX", ROOT_PREFIX) if isinstance(cfg, dict) else ROOT_PREFIX
    return root or ROOT_PREFIX


async def _perform_backup(
    context: SpectreContext,
    guild_id: int | None = None,
) -> bool:
    """Run a full backup for a guild. Returns True on success, False on failure."""
    root_prefix = _get_root_prefix_for_guild(guild_id)
    try:
        ts, fname = await run_blocking(backup_all, root_prefix, guild_id)
    except Exception as exc:
        _logger.exception("Backup failed: %s", exc)
        try:
            await context.log_action(
                f" Backup failed: {exc!s}",
                broadcast=False,
                guild_id=guild_id,
            )
        except Exception:
            pass
        return False
    try:
        context.lazarus_ai.note_backup(ts)
    except Exception:  # pragma: no cover - defensive logging
        context.logger.exception("Failed to record backup time with LazarusAI")
    try:
        await context.log_action(
            f" Backup saved to `{fname}`.", broadcast=False, guild_id=guild_id
        )
    except Exception:
        pass
    try:
        backup_prefix = _backup_prefix_for_guild(guild_id)
        _dirs, files = list_dir(backup_prefix, limit=1000)
        names = sorted(f for f, _ in files)
        while len(names) > MAX_BACKUPS_PER_SERVER:
            old = names.pop(0)
            try:
                delete_file(f"{backup_prefix}/{old}")
            except Exception:
                pass
    except Exception:
        pass
    return True


def create_backup_loop(context: SpectreContext) -> tasks.Loop:
    """Create the scheduled task that performs full backups."""

    interval = max(0.25, float(context.settings.backup_interval_hours or 0.5))

    def _guild_ids_to_backup() -> list[int]:
        guild_ids = list(context.guild_ids)
        if not guild_ids:
            guild_ids = [int(g.id) for g in context.bot.guilds]
        return guild_ids

    @tasks.loop(hours=interval)
    async def backup_loop() -> None:
        for gid in _guild_ids_to_backup():
            try:
                await _perform_backup(context, guild_id=gid)
            except Exception as exc:
                _logger.exception("Backup loop error for guild %s: %s", gid, exc)
                try:
                    await context.log_action(
                        f" Backup task error for guild {gid}: {exc!s}",
                        broadcast=False,
                        guild_id=gid,
                    )
                except Exception:
                    pass

    @backup_loop.before_loop
    async def _run_initial_backup() -> None:
        """Run one backup per guild shortly after startup."""
        import asyncio

        await context.bot.wait_until_ready()
        await asyncio.sleep(60)
        for gid in _guild_ids_to_backup():
            try:
                await _perform_backup(context, guild_id=gid)
            except Exception as exc:
                _logger.exception("Initial backup failed for guild %s: %s", gid, exc)

    return backup_loop


async def backup_action(context: SpectreContext, guild_id: int | None = None) -> None:
    """Public coroutine wrapper around the backup routine."""

    await _perform_backup(context, guild_id=guild_id)


__all__ = [
    "backup_all",
    "create_backup_loop",
    "backup_action",
    "purge_archive_and_backups",
    "restore_backup",
    "GREEK_LETTERS",
]
