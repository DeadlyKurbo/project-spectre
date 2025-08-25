import asyncio
import importlib


class DummyChannel:
    def __init__(self, cid: int):
        self.id = cid
        self.sent = []
        self.purged = False
        self.guild = None

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    async def purge(self):
        self.purged = True
        self.sent.clear()


class DummyBot:
    def __init__(self, menu_ch: DummyChannel, roster_ch: DummyChannel):
        self._menu_ch = menu_ch
        self._roster_ch = roster_ch
        self.user = "bot"

    def add_view(self, view):
        pass

    def get_channel(self, cid: int):
        if cid == self._menu_ch.id:
            return self._menu_ch
        if cid == self._roster_ch.id:
            return self._roster_ch
        return None


class DummyLoop:
    def is_running(self):
        return False

    def start(self):
        pass


class DummyLazarus:
    def start(self):
        pass


def test_on_ready_purges_menu(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.setenv("ROSTER_CHANNEL_ID", "2")

    main = importlib.reload(importlib.import_module("main"))

    menu_ch = DummyChannel(1)
    roster_ch = DummyChannel(2)
    main.bot = DummyBot(menu_ch, roster_ch)
    main.heartbeat_loop = DummyLoop()
    main.backup_loop = DummyLoop()
    main.lazarus_ai = DummyLazarus()

    async def fake_send_roster(channel, guild):
        channel.purged = True

    monkeypatch.setattr(main, "send_roster", fake_send_roster)
    monkeypatch.setattr(main, "ensure_dir", lambda *_: None)

    asyncio.run(main.on_ready())

    assert menu_ch.purged
    assert menu_ch.sent[0][1]["embed"].title == "Project SPECTRE File Explorer"

