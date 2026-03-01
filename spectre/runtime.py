"""Runtime helpers to start and manage the Spectre bot."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from types import FrameType
from typing import Optional

from nextcord.errors import LoginFailure

from .application import SpectreApplication
from .restart_policy import (
    compute_next_restart,
    get_restart_schedule,
    write_restart_state,
)


class SpectreRuntime:
    """Manage application lifecycle and orchestrate the bot run loop."""

    def __init__(self) -> None:
        self.app = SpectreApplication()
        self._shutdown = False
        self._planned_restart = False

    async def _restart_watchdog(
        self,
        *,
        started_at: datetime,
    ) -> None:
        """Close the bot once the configured restart interval is reached."""

        schedule = get_restart_schedule()
        next_restart = compute_next_restart(started_at, schedule)
        write_restart_state(started_at=started_at, next_restart_at=next_restart)
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

    def request_shutdown(self) -> None:
        """Request runtime shutdown and close the bot if possible."""

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
            started_at = datetime.now(timezone.utc)
            self._planned_restart = False
            watchdog = asyncio.create_task(self._restart_watchdog(started_at=started_at))
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
                if self._planned_restart:
                    self.app.logger.info("Reinitialising application after planned restart")
                    self.app = SpectreApplication()
                    bot = self.app.bot
                    token = self.app.token
                    if not token:
                        self.app.logger.error(
                            "No Discord token found (DISCORD_TOKEN / DISCORD_BOT_TOKEN). Exiting."
                        )
                        return
                    continue
                backoff = 1
                self.app.logger.warning(
                    "Bot stopped unexpectedly, restarting in %s seconds", backoff
                )
                await asyncio.sleep(backoff)
            finally:
                watchdog.cancel()
                try:
                    await watchdog
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

    def create_background_task(self) -> asyncio.Task[None] | None:
        """Schedule the bot runtime on the active event loop.

        This is intended for ASGI startup hooks where an event loop is already
        running and ``asyncio.run`` would raise ``RuntimeError``.
        """

        if not self.app.token:
            self.app.logger.warning(
                "Skipping Discord bot startup because no token is configured"
            )
            return None

        loop = asyncio.get_running_loop()
        self.app.logger.info("Scheduling Discord bot runtime in background task")
        return loop.create_task(self._run_bot(), name="spectre-bot-runtime")


def run() -> None:
    runtime = SpectreRuntime()
    runtime.install_signal_handlers()
    runtime.run()


__all__ = ["run", "SpectreRuntime"]
