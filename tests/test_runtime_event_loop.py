"""The bot runtime must drive the event loop nextcord bound the client to."""

from __future__ import annotations

import asyncio
import types

import spectre.runtime as runtime_mod


def test_run_drives_the_loop_the_bot_was_created_on():
    # Nextcord stores the loop that was current when the client was built and
    # schedules gateway heartbeats on it. Running the bot on any other loop
    # leaves those heartbeats queued forever ("heartbeat blocked").
    bot_loop = asyncio.new_event_loop()
    seen: dict[str, asyncio.AbstractEventLoop] = {}

    rt = runtime_mod.SpectreRuntime.__new__(runtime_mod.SpectreRuntime)
    rt.app = types.SimpleNamespace(
        token="token",
        bot=types.SimpleNamespace(loop=bot_loop),
        logger=types.SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )

    async def fake_run_bot():
        seen["loop"] = asyncio.get_running_loop()

    rt._run_bot = fake_run_bot
    rt.run()

    assert seen["loop"] is bot_loop
    assert bot_loop.is_closed()
