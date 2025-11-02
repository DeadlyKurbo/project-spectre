"""Runtime helpers to start and manage the Spectre bot."""

from __future__ import annotations

import asyncio
import signal
import sys
from types import FrameType
from typing import Optional

from nextcord.errors import LoginFailure

from .application import SpectreApplication


class SpectreRuntime:
    """Manage application lifecycle and orchestrate the bot run loop."""

    def __init__(self) -> None:
        self.app = SpectreApplication()
        self._shutdown = False

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
                backoff = 1
                self.app.logger.warning(
                    "Bot stopped unexpectedly, restarting in %s seconds", backoff
                )
                await asyncio.sleep(backoff)

    def run(self) -> None:
        if not self.app.token:
            self.app.logger.error(
                "No Discord token found (DISCORD_TOKEN / DISCORD_BOT_TOKEN). Exiting."
            )
            sys.exit(1)

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
