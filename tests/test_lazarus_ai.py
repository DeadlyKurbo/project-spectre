import os
import asyncio
from datetime import datetime, UTC, timedelta

import nextcord
from nextcord.ext import commands

os.environ.setdefault("GUILD_ID", "1")
import lazarus
from lazarus import LazarusAI


def _make_bot():
    intents = nextcord.Intents.none()
    return commands.Bot(intents=intents)


def _cleanup_bot(bot, loop):
    try:
        loop.run_until_complete(bot.close())
    finally:
        loop.close()


def test_compute_status_ok():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    assert cog.compute_status(datetime.now(UTC)) == "System Check: OK"
    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)


def test_compute_status_backup_outdated():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    cog.last_backup_ts = datetime.now(UTC) - timedelta(hours=2)
    assert cog.compute_status(datetime.now(UTC)) == "Backup outdated"
    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)


def test_compute_status_heartbeat_stalled():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    cog.last_heartbeat = datetime.now(UTC) - timedelta(minutes=5)
    assert cog.compute_status(datetime.now(UTC)) == "Heartbeat stalled"
    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)


def test_generate_response_no_llm(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    monkeypatch.setattr(lazarus, "LLM_API_KEY", "")

    def fail_complete(prompt: str) -> str:
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(lazarus.llm_client, "complete", fail_complete)
    assert cog.generate_response("Hello") == "ACK: hello | MEMREF: none"
    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)


def test_generate_response_with_llm(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    monkeypatch.setattr(lazarus, "LLM_API_KEY", "key")
    monkeypatch.setattr(lazarus.llm_client, "complete", lambda prompt: "LLM output")
    assert cog.generate_response("hi") == "LLM output"
    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)

