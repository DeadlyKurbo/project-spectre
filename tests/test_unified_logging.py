import asyncio
import types

import moderation
import main


class DummyBot:
    pass


async def run_and_capture(coro):
    logs = []

    async def fake_log(msg, *, broadcast=True):
        logs.append(msg)

    main.log_action = fake_log
    await coro
    return logs


def test_message_delete_logs():
    bot = DummyBot()
    cog = moderation.Moderation(bot)
    message = types.SimpleNamespace(
        guild=object(),
        content="hello",
        author=types.SimpleNamespace(mention="<@1>"),
        channel=types.SimpleNamespace(mention="#general"),
    )
    logs = asyncio.run(run_and_capture(cog.on_message_delete(message)))
    assert logs and "deleted" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_message_edit_logs():
    bot = DummyBot()
    cog = moderation.Moderation(bot)
    before = types.SimpleNamespace(
        guild=object(),
        content="old",
        author=types.SimpleNamespace(mention="<@1>"),
        channel=types.SimpleNamespace(mention="#general"),
    )
    after = types.SimpleNamespace(
        guild=object(),
        content="new",
        author=before.author,
        channel=before.channel,
    )
    logs = asyncio.run(run_and_capture(cog.on_message_edit(before, after)))
    assert logs and "edited" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_avatar_change_logs():
    bot = DummyBot()
    cog = moderation.Moderation(bot)
    before = types.SimpleNamespace(
        display_avatar=types.SimpleNamespace(url="a"),
        mention="<@1>",
    )
    after = types.SimpleNamespace(
        display_avatar=types.SimpleNamespace(url="b"),
        mention="<@1>",
    )
    logs = asyncio.run(run_and_capture(cog.on_member_update(before, after)))
    assert logs and "changed profile picture" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_invite_create_logs():
    bot = DummyBot()
    cog = moderation.Moderation(bot)
    invite = types.SimpleNamespace(
        code="xyz",
        inviter=types.SimpleNamespace(mention="<@1>"),
        channel=types.SimpleNamespace(mention="#general"),
    )
    logs = asyncio.run(run_and_capture(cog.on_invite_create(invite)))
    assert logs and "Invite" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_guild_update_logs():
    bot = DummyBot()
    cog = moderation.Moderation(bot)
    before = types.SimpleNamespace(name="Old", icon=None)
    after = types.SimpleNamespace(name="New", icon=None)
    logs = asyncio.run(run_and_capture(cog.on_guild_update(before, after)))
    assert logs and "Guild updated" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_raw_message_delete_logs():
    bot = types.SimpleNamespace(
        get_channel=lambda cid: types.SimpleNamespace(mention="#general")
    )
    cog = moderation.Moderation(bot)
    payload = types.SimpleNamespace(guild_id=1, channel_id=1, message_id=2)
    logs = asyncio.run(run_and_capture(cog.on_raw_message_delete(payload)))
    assert logs and "deleted" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_raw_bulk_message_delete_logs():
    bot = types.SimpleNamespace(
        get_channel=lambda cid: types.SimpleNamespace(mention="#general")
    )
    cog = moderation.Moderation(bot)
    payload = types.SimpleNamespace(guild_id=1, channel_id=1, message_ids=[1, 2])
    logs = asyncio.run(run_and_capture(cog.on_raw_bulk_message_delete(payload)))
    assert logs and "bulk deleted" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_raw_message_edit_logs():
    class DummyChannel:
        mention = "#general"

        async def fetch_message(self, mid):
            return types.SimpleNamespace(
                content="new", author=types.SimpleNamespace(mention="<@1>")
            )

    bot = types.SimpleNamespace(get_channel=lambda cid: DummyChannel())
    cog = moderation.Moderation(bot)
    payload = types.SimpleNamespace(guild_id=1, channel_id=1, message_id=2)
    logs = asyncio.run(run_and_capture(cog.on_raw_message_edit(payload)))
    assert logs and "edited" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_member_remove_logs():
    bot = DummyBot()
    cog = moderation.Moderation(bot)
    member = types.SimpleNamespace(mention="<@1>")
    logs = asyncio.run(run_and_capture(cog.on_member_remove(member)))
    assert logs and "left" in logs[0]
    asyncio.set_event_loop(asyncio.new_event_loop())
