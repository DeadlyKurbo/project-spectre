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
    assert cog.compute_status(datetime.now(UTC)) is None
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


def test_generate_response_uses_llm(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    monkeypatch.setattr(lazarus.llm_client, "run_assistant", lambda prompt: "pong")
    assert cog.generate_response("Hello") == "pong"
    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)


def test_on_message_only_replies_in_channel(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = _make_bot()
    cog = LazarusAI(bot, channel_id=1, backup_interval_hours=1, status_interval_minutes=1)
    monkeypatch.setattr(lazarus.llm_client, "run_assistant", lambda prompt: "pong")

    class DummyChannel:
        def __init__(self, id):
            self.id = id
            self.sent: list[str] = []

        async def send(self, msg: str) -> None:
            self.sent.append(msg)

    class DummyAuthor:
        bot = False

    msg1 = type(
        "Msg",
        (),
        {
            "author": DummyAuthor(),
            "content": "hello",
            "channel": DummyChannel(2),
        },
    )
    loop.run_until_complete(cog.on_message(msg1))
    assert msg1.channel.sent == []

    msg2 = type(
        "Msg",
        (),
        {
            "author": DummyAuthor(),
            "content": "anything",
            "channel": DummyChannel(1),
        },
    )
    loop.run_until_complete(cog.on_message(msg2))
    assert msg2.channel.sent == ["pong"]

    _cleanup_bot(bot, loop)
    asyncio.set_event_loop(None)

