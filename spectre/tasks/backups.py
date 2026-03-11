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
def backup_all(root_prefix: str = ROOT_PREFIX) -> tuple[datetime, str]:
    """Create a full archive backup under ``backups/`` and return timestamp and path."""

    with SpooledTemporaryFile(max_size=1_000_000) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8") as tmp:
            tmp.write("{")
            first = True

            def _recurse(pref: str) -> None:
                nonlocal first
                dirs, files = list_dir(pref, limit=10000)
                for fname, _ in files:
                    path = f"{pref}/{fname}" if pref else fname
                    try:
                        content = read_text(path)
                    except Exception:
                        continue
                    if not first:
                        tmp.write(",")
                    first = False
                    tmp.write(json.dumps(path))
                    tmp.write(":")
                    tmp.write(json.dumps(content))
                for directory in dirs:
                    _recurse(f"{pref}/{directory.strip('/')}")

            _recurse(root_prefix)
            tmp.write("}")
            tmp.flush()
            raw.seek(0)

            ts = datetime.now(UTC)
            ensure_dir("backups")
            name = random.choice(GREEK_LETTERS)
            stamp = ts.strftime("%Y%m%dT%H%M%S")
            fname = f"backups/Backup protocol {name}-{stamp}.json"
            save_text(fname, raw, "application/json; charset=utf-8")
    return ts, fname


def restore_backup(path: str, root_prefix: str = ROOT_PREFIX) -> None:
    """Load a full archive backup from ``path`` and replace existing files."""

    data = read_json(path)
    existing: list[str] = []

    def _collect(pref: str) -> None:
        dirs, files = list_dir(pref, limit=10000)
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


def purge_archive_and_backups(root_prefix: str = ROOT_PREFIX) -> None:
    """Remove all files from the archive and backup storage."""

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
    _purge("backups")


async def _perform_backup(context: SpectreContext) -> bool:
    """Run a full backup. Returns True on success, False on failure."""
    try:
        ts, fname = await run_blocking(backup_all)
    except Exception as exc:
        _logger.exception("Backup failed: %s", exc)
        try:
            await context.log_action(
                f" Backup failed: {exc!s}",
                broadcast=False,
            )
        except Exception:
            pass
        return False
    try:
        context.lazarus_ai.note_backup(ts)
    except Exception:  # pragma: no cover - defensive logging
        context.logger.exception("Failed to record backup time with LazarusAI")
    try:
        await context.log_action(f" Backup saved to `{fname}`.", broadcast=False)
    except Exception:
        pass
    try:
        _dirs, files = list_dir("backups", limit=1000)
        names = sorted(f for f, _ in files)
        while len(names) > 4:
            old = names.pop(0)
            try:
                delete_file(f"backups/{old}")
            except Exception:
                pass
    except Exception:
        pass
    return True


def create_backup_loop(context: SpectreContext) -> tasks.Loop:
    """Create the scheduled task that performs full backups."""

    interval = max(0.25, float(context.settings.backup_interval_hours or 0.5))

    @tasks.loop(hours=interval)
    async def backup_loop() -> None:
        try:
            await _perform_backup(context)
        except Exception as exc:
            _logger.exception("Backup loop error: %s", exc)
            try:
                await context.log_action(
                    f" Backup task error: {exc!s}",
                    broadcast=False,
                )
            except Exception:
                pass

    @backup_loop.before_loop
    async def _run_initial_backup() -> None:
        """Run one backup shortly after startup instead of waiting a full interval."""
        import asyncio

        await context.bot.wait_until_ready()
        await asyncio.sleep(60)
        try:
            await _perform_backup(context)
        except Exception as exc:
            _logger.exception("Initial backup failed: %s", exc)

    return backup_loop


async def backup_action(context: SpectreContext) -> None:
    """Public coroutine wrapper around the backup routine."""

    await _perform_backup(context)


__all__ = [
    "backup_all",
    "create_backup_loop",
    "backup_action",
    "purge_archive_and_backups",
    "restore_backup",
    "GREEK_LETTERS",
]
