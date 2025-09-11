import importlib
import asyncio
import nextcord


def test_section_zero_autodeploy(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.setenv("SECTION_ZERO_CHANNEL_ID", "1")
    monkeypatch.setenv("ROSTER_CHANNEL_ID", "2")

    sz = importlib.reload(importlib.import_module("section_zero"))
    main = importlib.reload(importlib.import_module("main"))

    class Channel:
        def __init__(self):
            self.kwargs = None

        id = main.SECTION_ZERO_CHANNEL_ID
        type = nextcord.ChannelType.text

        async def send(self, *, embed=None, view=None):
            self.kwargs = {"embed": embed, "view": view}

    channel = Channel()

    def fake_get_channel(cid):
        if cid == main.SECTION_ZERO_CHANNEL_ID:
            return channel
        return None

    monkeypatch.setattr(main.bot, "add_view", lambda *a, **k: None)
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
    loop.run_until_complete(main.on_ready())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert isinstance(channel.kwargs["view"], sz.SectionZeroControlView)
    assert channel.kwargs["embed"].title.startswith("\u26ab SECTION ZERO")
    desc = channel.kwargs["embed"].description
    assert "Knowledge is Control" in desc
    assert "Obsidian Vault" in desc

