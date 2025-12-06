#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Optional, Dict

import nextcord

from archivist import refresh_menus
from storage_spaces import (
    delete_file,
    list_dir,
    read_json,
    save_json,
)  # Spaces/S3 helpers
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
        # Fetch merged runtime to ensure it’s valid
        cfg = get_server_config(guild.id)
        ch_id = int(cfg.get("MENU_CHANNEL_ID") or 0)
        if not ch_id:
            log.info("Guild %s has no MENU_CHANNEL_ID set yet; skipping deploy.", guild.id)
            return

        if etag and self._last_etag.get(guild.id) == etag:
            # Configuration unchanged; only redeploy if the menu disappeared.
            if not await self._menu_missing(guild, ch_id):
                return
            log.info("Guild %s menu missing; redeploying with cached config.", guild.id)

        # Remember current etag (even if None) to avoid loops
        self._last_etag[guild.id] = etag or ""

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

            payload: dict | None = None
            attempts = 0
            queue_path = f"deploy-queue/{fname}"

            try:
                payload = read_json(queue_path)
                if isinstance(payload, dict):
                    attempts = int(payload.get("attempts", 0) or 0)
            except Exception:
                payload = None

            try:
                result = await self._deploy_archive_menu(guild)
                if result:
                    log.info("[queue] Deployed for %s: %s", gid, result)
                delete_file(queue_path)
                continue
            except Exception as e:
                log.exception("Deploy failed for %s: %s", gid, e)

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

    async def _menu_missing(self, guild: nextcord.Guild, channel_id: int) -> bool:
        """Return ``True`` when the configured menu message cannot be located."""

        channel = None
        getter = getattr(guild, "get_channel_or_thread", None)
        if callable(getter):
            channel = getter(channel_id)
        if channel is None:
            channel = guild.get_channel(channel_id)
        if channel is None:
            log.warning("Menu channel %s missing for guild %s", channel_id, guild.id)
            return True

        last_message_id = getattr(channel, "last_message_id", None)
        if last_message_id:
            fetch = getattr(channel, "fetch_message", None)
            if callable(fetch):
                try:
                    message = await fetch(last_message_id)
                except nextcord.NotFound:
                    message = None
                except nextcord.Forbidden:
                    log.warning(
                        "Missing permissions to inspect menu channel %s for guild %s",
                        channel_id,
                        guild.id,
                    )
                    return False
                except nextcord.HTTPException as exc:
                    log.debug(
                        "Failed to fetch last menu message for guild %s: %s",
                        guild.id,
                        exc,
                    )
                    message = None
                if message and message.author == self.bot.user:
                    if getattr(message, "components", None) or getattr(message, "embeds", None):
                        return False

        history = getattr(channel, "history", None)
        if callable(history):
            try:
                async for message in history(limit=5):
                    if message.author == self.bot.user:
                        if getattr(message, "components", None) or getattr(message, "embeds", None):
                            return False
            except nextcord.Forbidden:
                log.warning(
                    "Missing permissions to read history in menu channel %s for guild %s",
                    channel_id,
                    guild.id,
                )
                return False
            except nextcord.HTTPException as exc:
                log.debug(
                    "Failed reading menu history for guild %s: %s",
                    guild.id,
                    exc,
                )

        return True

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
