#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared deploy-queue handling for archive and mission report menus."""

from __future__ import annotations

import asyncio
import logging

import nextcord

from archivist import refresh_menus
from mission_reports import is_mission_reports_enabled, refresh_mission_reports_menu
from storage_spaces import delete_file, list_dir, read_json, save_json

log = logging.getLogger("spectre.deploy_queue")

# DeployWatcher and RemoteConfigWatcher both poll the queue; only one may work
# through it at a time or the same queued deploy is posted twice.
_QUEUE_LOCK = asyncio.Lock()


async def consume_deploy_queue(bot: nextcord.Client) -> None:
    """Process pending deploy-queue/*.json entries for connected guilds."""

    if _QUEUE_LOCK.locked():
        return
    async with _QUEUE_LOCK:
        await _consume_deploy_queue(bot)


async def _consume_deploy_queue(bot: nextcord.Client) -> None:
    _dirs, files = list_dir("deploy-queue", limit=500)
    if not files:
        return

    for fname, _size in files:
        if not fname.endswith(".json"):
            continue
        try:
            gid = int(fname.split(".json", 1)[0])
        except ValueError:
            continue

        guild = bot.get_guild(gid)
        if not guild:
            log.warning(
                "Deploy queued for guild %s but it is not cached yet; will retry",
                gid,
            )
            continue

        queue_path = f"deploy-queue/{fname}"
        payload: dict | None = None
        attempts = 0
        try:
            raw = read_json(queue_path)
            if isinstance(raw, dict):
                payload = raw
                attempts = int(raw.get("attempts", 0) or 0)
        except Exception:
            payload = None

        menu_override: int | None = None
        mr_menu_override: int | None = None
        deploy_target = "archive"
        if isinstance(payload, dict):
            try:
                menu_override = int(payload.get("menu_channel_id") or 0) or None
            except (TypeError, ValueError):
                menu_override = None
            try:
                mr_menu_override = int(payload.get("mission_reports_menu_channel_id") or 0) or None
            except (TypeError, ValueError):
                mr_menu_override = None
            raw_target = payload.get("deploy_target")
            if isinstance(raw_target, str) and raw_target.strip():
                deploy_target = raw_target.strip().lower()

        try:
            result_parts: list[str] = []
            if deploy_target in ("archive", "both", "all"):
                try:
                    if await refresh_menus(
                        guild, menu_channel_override=menu_override
                    ):
                        result_parts.append("archive menus refreshed")
                    else:
                        log.warning(
                            "Archive deploy produced no menu for guild %s", gid
                        )
                except Exception:
                    log.exception("Archive deploy failed for guild %s", gid)

            should_deploy_mission_reports = deploy_target in (
                "mission_reports",
                "both",
                "all",
            )
            if should_deploy_mission_reports and deploy_target == "all":
                should_deploy_mission_reports = is_mission_reports_enabled(gid)

            if should_deploy_mission_reports:
                try:
                    await refresh_mission_reports_menu(
                        guild, menu_channel_override=mr_menu_override
                    )
                    result_parts.append("mission reports menu refreshed")
                except ValueError as exc:
                    if deploy_target == "all":
                        log.info(
                            "Skipping mission reports deploy for guild %s: %s",
                            gid,
                            exc,
                        )
                    else:
                        log.warning(
                            "Mission reports deploy skipped for guild %s: %s",
                            gid,
                            exc,
                        )
                        raise
                except Exception:
                    log.exception("Mission reports deploy failed for guild %s", gid)
                    raise

            if not result_parts:
                raise RuntimeError(f"Deploy produced no results for guild {gid}")

            log.info("[queue] Deployed for %s: %s", gid, "; ".join(result_parts))
            delete_file(queue_path)
            continue
        except Exception:
            log.exception("Deploy failed for %s (attempt %s)", gid, attempts + 1)

        attempts += 1
        if attempts >= 3:
            log.warning(
                "Giving up on queued deploy for %s after %s failed attempt(s)",
                gid,
                attempts,
            )
            try:
                delete_file(queue_path)
            except Exception:
                pass
            continue

        updated_payload = payload if isinstance(payload, dict) else {}
        updated_payload["attempts"] = attempts
        try:
            save_json(queue_path, updated_payload)
        except Exception:
            log.exception("Failed to update deploy queue item for guild %s", gid)
