import importlib
import asyncio


def test_section_zero_autodeploy(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.setenv("SECTION_ZERO_CHANNEL_ID", "1")
    monkeypatch.setenv("ROSTER_CHANNEL_ID", "2")
    monkeypatch.setenv("AUTO_POST_SECTION_ZERO", "1")

    sz = importlib.reload(importlib.import_module("section_zero"))
    main = importlib.reload(importlib.import_module("main"))

    class Message:
        def __init__(self, channel, embed, view):
            self.channel = channel
            self.author = type("Author", (), {"id": main.bot.user.id})()
            self.components = view is not None
            self.embed = embed
            self.view = view

        async def edit(self, *, embed=None, view=None):
            self.channel.kwargs = {"embed": embed, "view": view}
            self.channel.edits += 1
            self.embed = embed
            self.view = view

    class Channel:
        def __init__(self):
            self.kwargs = None
            self.calls = 0
            self.edits = 0
            self.messages = []

        id = main.SECTION_ZERO_CHANNEL_ID

        async def send(self, *, embed=None, view=None):
            self.kwargs = {"embed": embed, "view": view}
            self.calls += 1
            msg = Message(self, embed, view)
            self.messages.append(msg)
            return msg

        async def history(self, limit=25):
            for msg in reversed(self.messages[-limit:]):
                yield msg

    channel = Channel()

    def fake_get_channel(cid):
        if cid == main.SECTION_ZERO_CHANNEL_ID:
            return channel
        return None

    monkeypatch.setattr(main.bot, "add_view", lambda *a, **k: None)
    monkeypatch.setattr(
        main.bot,
        "_connection",
        type("Conn", (), {"user": type("User", (), {"id": 42})()})(),
    )
    monkeypatch.setattr(main.bot, "get_guild", lambda *a, **k: None)
    monkeypatch.setattr(main.bot, "get_channel", fake_get_channel)
    monkeypatch.setattr(main, "refresh_menus", lambda *a, **k: None)
    monkeypatch.setattr(main.lazarus_ai, "start", lambda: None)
    async def _no_log(*args, **kwargs):
        return None
    monkeypatch.setattr(main, "log_action", _no_log)
    monkeypatch.setattr(main, "ensure_dir", lambda *a, **k: None)
    monkeypatch.setattr(main.backup_loop, "is_running", lambda: True)
    monkeypatch.setattr(main.backup_loop, "start", lambda: None)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main.setup_hook())
    loop.run_until_complete(main.on_ready())
    loop.run_until_complete(main.on_ready())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert isinstance(channel.kwargs["view"], sz.SectionZeroControlView)
    assert channel.kwargs["embed"].title.startswith("\u26ab SECTION ZERO")
    desc = channel.kwargs["embed"].description
    assert "Knowledge is Control" in desc
    assert "Obsidian Vault" in desc
    assert channel.calls == 1

