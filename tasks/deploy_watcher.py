#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Optional

import nextcord
from utils.guild_store import take_deploy_requests

log = logging.getLogger("spectre.deploy_watcher")

class DeployWatcher:
    def __init__(self, bot: nextcord.Client, interval_sec: int = 3):
        self.bot = bot
        self.interval = interval_sec
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if self._task and not self._task.done(): return
        self._task = self.bot.loop.create_task(self._run())

    async def _run(self):
        await self.bot.wait_until_ready()
        log.info("DeployWatcher started (interval=%ss).", self.interval)
        while not self.bot.is_closed():
            try:
                for gid in take_deploy_requests():
                    guild = self.bot.get_guild(gid)
                    if not guild:
                        log.warning("Deploy requested for unknown guild %s", gid)
                        continue
                    cog = self.bot.get_cog("ArchiveCog")
                    if not cog or not hasattr(cog, "deploy_for_guild"):
                        log.warning("ArchiveCog not ready for deploy")
                        continue
                    try:
                        result = await cog.deploy_for_guild(guild)  # type: ignore
                        log.info("Deployed for %s: %s", gid, result)
                    except Exception as e:
                        log.exception("Deploy failed for %s: %s", gid, e)
            except Exception as e:
                log.exception("Watcher loop error: %s", e)

            await asyncio.sleep(self.interval)
