#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Optional, Dict

import nextcord

from archivist import refresh_menus
from storage_spaces import read_json, delete_file, list_dir  # Spaces/S3 helpers
from server_config import get_server_config                    # runtime merge
# We’ll read raw config etags directly from Spaces:
#   key: "guild-configs/{gid}.json"
# For “deploy now” triggers, website will write:
#   key: "deploy-queue/{gid}.json"

log = logging.getLogger("spectre.remote_cfg")

class RemoteConfigWatcher:
    def __init__(self, bot: nextcord.Client, interval_sec: int = 3):
        self.bot = bot
        self.interval = interval_sec
        self._task: Optional[asyncio.Task] = None
        self._last_etag: Dict[int, str] = {}   # guild_id -> etag

    def start(self):
        if self._task and not self._task.done():
            return
        self._task = self.bot.loop.create_task(self._run())

    async def _run(self):
        await self.bot.wait_until_ready()
        log.info("RemoteConfigWatcher started (interval=%ss).", self.interval)
        while not self.bot.is_closed():
            try:
                # 1) Handle explicit deploy requests
                await self._consume_deploy_queue()

                # 2) Detect config changes by ETag on Spaces
                for g in list(self.bot.guilds):
                    await self._maybe_redeploy_on_etag_change(g)
            except Exception as e:
                log.exception("Watcher loop error: %s", e)
            await asyncio.sleep(self.interval)

    async def _maybe_redeploy_on_etag_change(self, guild: nextcord.Guild):
        key = f"guild-configs/{guild.id}.json"
        _doc, etag = read_json(key, with_etag=True)
        if etag and self._last_etag.get(guild.id) == etag:
            return  # unchanged
        # Remember current etag (even if None) to avoid loops
        self._last_etag[guild.id] = etag or ""

        # Fetch merged runtime to ensure it’s valid
        cfg = get_server_config(guild.id)
        ch_id = int(cfg.get("MENU_CHANNEL_ID") or 0)
        if not ch_id:
            log.info("Guild %s has no MENU_CHANNEL_ID set yet; skipping deploy.", guild.id)
            return

        result = await self._deploy_archive_menu(guild)
        if result:
            log.info("[etag] Deployed for %s: %s", guild.id, result)

    async def _consume_deploy_queue(self):
        # Look for files in "deploy-queue/"
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
            guild = self.bot.get_guild(gid)
            if not guild:
                log.warning("Deploy requested for unknown guild %s", gid)
                delete_file(f"deploy-queue/{fname}")
                continue
            try:
                result = await self._deploy_archive_menu(guild)
                if result:
                    log.info("[queue] Deployed for %s: %s", gid, result)
            except Exception as e:
                log.exception("Deploy failed for %s: %s", gid, e)
            # Always remove the queue item (avoid infinite retries)
            try:
                delete_file(f"deploy-queue/{fname}")
            except Exception:
                pass

    async def _deploy_archive_menu(self, guild: nextcord.Guild) -> str | None:
        """Deploy or refresh archive menus for ``guild``.

        The configuration dashboard stores menu assignments in the
        ``MENU_CHANNEL_ID`` slot.  Refresh the modern archive interface via
        :func:`archivist.refresh_menus` and fall back to the legacy
        ``ArchiveCog`` deployment when available.  Returning a summary string
        keeps logging consistent with historical behaviour.
        """

        results: list[str] = []

        try:
            await refresh_menus(guild)
            results.append("menus refreshed")
        except Exception as exc:
            log.exception("Failed to refresh archive menus for %s: %s", guild.id, exc)

        cog = self.bot.get_cog("ArchiveCog")
        if cog and hasattr(cog, "deploy_for_guild"):
            try:
                legacy_result = await cog.deploy_for_guild(guild)  # type: ignore[attr-defined]
                if legacy_result:
                    results.append(str(legacy_result))
            except Exception as exc:
                log.exception("Legacy deploy failed for %s: %s", guild.id, exc)
        elif cog:
            log.warning("ArchiveCog missing deploy_for_guild for guild %s", guild.id)

        if results:
            return "; ".join(results)
        return None
