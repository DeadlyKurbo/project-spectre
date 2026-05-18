#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Optional

import nextcord

from archivist import refresh_menus
from mission_reports import refresh_mission_reports_menu
from tasks.deploy_queue import consume_deploy_queue
from utils.guild_store import take_deploy_requests

log = logging.getLogger("spectre.deploy_watcher")


class DeployWatcher:
    def __init__(self, bot: nextcord.Client, interval_sec: int = 3):
        self.bot = bot
        self.interval = interval_sec
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if self._task and not self._task.done():
            return
        self._task = self.bot.loop.create_task(self._run())

    async def _run(self):
        await self.bot.wait_until_ready()
        log.info("DeployWatcher started (interval=%ss).", self.interval)
        while not self.bot.is_closed():
            try:
                await consume_deploy_queue(self.bot)

                for gid, payload in take_deploy_requests():
                    guild = self.bot.get_guild(gid)
                    if not guild:
                        log.warning("Deploy requested for unknown guild %s", gid)
                        continue

                    deploy_target = "archive"
                    if isinstance(payload, dict):
                        raw_target = payload.get("deploy_target")
                        if isinstance(raw_target, str) and raw_target.strip():
                            deploy_target = raw_target.strip().lower()

                    menu_override = None
                    mr_override = None
                    if isinstance(payload, dict):
                        try:
                            menu_override = int(payload.get("menu_channel_id") or 0) or None
                        except (TypeError, ValueError):
                            menu_override = None
                        try:
                            mr_override = (
                                int(payload.get("mission_reports_menu_channel_id") or 0)
                                or None
                            )
                        except (TypeError, ValueError):
                            mr_override = None

                    if deploy_target in ("archive", "both", "all"):
                        try:
                            await refresh_menus(
                                guild, menu_channel_override=menu_override
                            )
                            log.info(
                                "Deployed archive menu for guild %s (local trigger)",
                                gid,
                            )
                        except Exception as e:
                            log.exception("Archive deploy failed for %s: %s", gid, e)

                    if deploy_target in ("mission_reports", "both", "all"):
                        try:
                            await refresh_mission_reports_menu(
                                guild, menu_channel_override=mr_override
                            )
                            log.info(
                                "Deployed mission reports menu for guild %s (local trigger)",
                                gid,
                            )
                        except Exception as e:
                            log.exception(
                                "Mission reports deploy failed for %s: %s", gid, e
                            )
            except Exception as e:
                log.exception("Watcher loop error: %s", e)

            await asyncio.sleep(self.interval)
