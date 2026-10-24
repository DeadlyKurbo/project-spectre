"""Runtime helpers to start and manage the Spectre bot."""

from __future__ import annotations

import asyncio
import math
import signal
from datetime import datetime, timezone
from types import FrameType
from typing import Optional

from nextcord.errors import LoginFailure

from app_spectre.services.moderation_service import reset_moderation_service
from archivist import clear_archivist_runtime_cache, prune_archivist_runtime_cache
from async_utils import run_blocking
from bot_control import (
    BOT_CONTROL_POLL_SECONDS,
    BOT_STATUS_HEARTBEAT_SECONDS,
    get_bot_control,
    parse_timestamp,
    write_bot_status,
)
from tme_geo_provider import clear_cache as clear_tme_geo_cache

from .application import SpectreApplication
from .restart_policy import (
    compute_next_restart,
    get_restart_schedule,
)


class SpectreRuntime:
    """Manage application lifecycle and orchestrate the bot run loop."""

    def __init__(self) -> None:
        self.app = SpectreApplication()
        self._shutdown = False
        self._planned_restart = False
        self._control_stop = False

    async def _restart_watchdog(
        self,
        *,
        started_at: datetime,
    ) -> None:
        """Close the bot once the configured restart interval is reached."""

        schedule = get_restart_schedule()
        next_restart = compute_next_restart(started_at, schedule)
        if next_restart is None:
            self.app.logger.info("Automatic bot restarts are disabled")
            return

        wait_seconds = max(0.0, (next_restart - datetime.now(timezone.utc)).total_seconds())
        self.app.logger.info(
            "Automatic bot restart scheduled in %.0f seconds (interval %.2f days)",
            wait_seconds,
            schedule.interval_days if schedule else 0.0,
        )
        await asyncio.sleep(wait_seconds)
        if self._shutdown:
            return

        self._planned_restart = True
        self.app.logger.warning("Scheduled restart window reached; restarting bot session")
        await self.app.bot.close()

    async def _read_bot_control(self) -> dict | None:
        try:
            return await run_blocking(get_bot_control)
        except Exception:
            self.app.logger.exception("Failed to read bot control state")
            return None

    async def _report_status(self, state: str, *, session_started_at: datetime | None = None) -> None:
        bot = self.app.bot
        latency = getattr(bot, "latency", float("nan"))
        ready = state == "online"
        try:
            await run_blocking(
                write_bot_status,
                state,
                session_started_at=session_started_at,
                latency_ms=int(latency * 1000) if ready and math.isfinite(latency) else None,
                guild_count=len(bot.guilds) if ready else None,
                bot_user=str(bot.user) if ready and bot.user else None,
            )
        except Exception:
            self.app.logger.exception("Failed to publish bot status heartbeat")

    async def _control_watchdog(self, *, started_at: datetime) -> None:
        """Follow shutdown/restart requests from the director console and publish heartbeats."""

        reported_state: str | None = None
        reported_at = 0.0
        loop = asyncio.get_running_loop()
        while not self._shutdown:
            try:
                control = await self._read_bot_control()
                if control is not None:
                    if control["desired"] == "stopped":
                        self._control_stop = True
                        self.app.logger.warning("Shutdown requested from the director console; disconnecting")
                        await self.app.bot.close()
                        return
                    restart_at = parse_timestamp(control.get("restart_requested_at"))
                    if restart_at and restart_at > started_at:
                        self._planned_restart = True
                        self.app.logger.warning("Restart requested from the director console")
                        await self.app.bot.close()
                        return

                state = "online" if self.app.bot.is_ready() else "connecting"
                if state != reported_state or loop.time() - reported_at >= BOT_STATUS_HEARTBEAT_SECONDS:
                    await self._report_status(state, session_started_at=started_at)
                    reported_state = state
                    reported_at = loop.time()
            except Exception:
                self.app.logger.exception("Bot control watchdog iteration failed")
            await asyncio.sleep(BOT_CONTROL_POLL_SECONDS)

    async def _wait_while_stopped(self) -> bool:
        """Keep the bot offline while the director console has it shut down.

        Returns ``False`` when the process received a shutdown signal instead.
        """

        seen_stop = False
        reported_at: float | None = None
        loop = asyncio.get_running_loop()
        while not self._shutdown:
            control = await self._read_bot_control()
            if control is None:
                # Unreadable state: keep the last known decision rather than
                # flapping. On boot that means starting the bot.
                if not seen_stop:
                    return True
            elif control["desired"] != "stopped":
                if seen_stop:
                    self.app.logger.info("Start requested from the director console")
                return True
            elif not seen_stop:
                seen_stop = True
                self.app.logger.warning("Bot is shut down from the director console; waiting for a start request")

            if reported_at is None or loop.time() - reported_at >= BOT_STATUS_HEARTBEAT_SECONDS:
                await self._report_status("stopped")
                reported_at = loop.time()
            for _ in range(BOT_CONTROL_POLL_SECONDS):
                if self._shutdown:
                    return False
                await asyncio.sleep(1)
        return False

    async def _reinitialise(self) -> bool:
        """Rebuild the application so a fresh client can reconnect after a close."""

        prune_archivist_runtime_cache()
        clear_archivist_runtime_cache()
        clear_tme_geo_cache()
        await reset_moderation_service()
        self.app = SpectreApplication()
        if not self.app.token:
            self.app.logger.error(
                "No Discord token found (DISCORD_TOKEN / DISCORD_BOT_TOKEN). Exiting."
            )
            return False
        return True

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, sig: int, frame: Optional[FrameType]) -> None:
        signame = signal.Signals(sig).name if isinstance(sig, int) else str(sig)
        self.app.logger.warning("Got %s, shutting down", signame)
        self._shutdown = True
        try:
            self.app.bot.loop.create_task(self.app.bot.close())
        except Exception:
            pass

    async def _run_bot(self) -> None:
        bot = self.app.bot
        token = self.app.token
        if not token:
            self.app.logger.error(
                "No Discord token found (DISCORD_TOKEN / DISCORD_BOT_TOKEN). Exiting."
            )
            return

        loop = asyncio.get_running_loop()

        def _handle_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:
            exception = context.get("exception")
            if exception:
                self.app.logger.error("Unhandled exception in event loop", exc_info=exception)
            else:
                self.app.logger.error("Unhandled event loop error: %s", context)

        loop.set_exception_handler(_handle_exception)

        backoff = 1
        while True:
            if not await self._wait_while_stopped():
                self.app.logger.info("Shutdown signal received, exiting run loop")
                return
            started_at = datetime.now(timezone.utc)
            self._planned_restart = False
            self._control_stop = False
            watchdog = asyncio.create_task(self._restart_watchdog(started_at=started_at))
            control_watchdog = asyncio.create_task(self._control_watchdog(started_at=started_at))
            try:
                self.app.logger.info("Attempting to start Discord bot")
                await bot.start(token)
            except LoginFailure as exc:
                self.app.logger.error("Failed to authenticate with Discord: %s", exc)
                return
            except (KeyboardInterrupt, asyncio.CancelledError):
                self.app.logger.info("Shutdown requested, closing bot")
                await bot.close()
                return
            except Exception as exc:  # pragma: no cover - network/Discord issues
                self.app.logger.exception(
                    "Bot connection failed, retrying in %s seconds", backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                if self._shutdown:
                    self.app.logger.info("Shutdown signal received, exiting run loop")
                    return
                if self._planned_restart or self._control_stop:
                    self.app.logger.info("Reinitialising application after planned restart")
                    if not await self._reinitialise():
                        return
                    bot = self.app.bot
                    token = self.app.token
                    continue
                backoff = 1
                self.app.logger.warning(
                    "Bot stopped unexpectedly, restarting in %s seconds", backoff
                )
                await asyncio.sleep(backoff)
            finally:
                for task in (watchdog, control_watchdog):
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    def run(self) -> None:
        if not self.app.token:
            self.app.logger.error(
                "No Discord token found (DISCORD_TOKEN / DISCORD_BOT_TOKEN). Exiting."
            )
            # Treat a missing token as a configuration error but do not crash the
            # entire process.  Hosting platforms often start the keepalive web
            # server and the bot in the same container; returning here keeps the
            # web process online even when the Discord credentials are absent.
            return

        try:
            self.app.logger.info("Boot sequence initiated")
            asyncio.run(self._run_bot())
        except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover - manual shutdown
            self.app.logger.info("Shutdown requested, exiting")
        except Exception:
            self.app.logger.exception("Unhandled exception during bot startup")


def run() -> None:
    runtime = SpectreRuntime()
    runtime.install_signal_handlers()
    runtime.run()


__all__ = ["run", "SpectreRuntime"]
