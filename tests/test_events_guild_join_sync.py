import asyncio
import types

from spectre.events import register


class DummyLoop:
    def __init__(self):
        self.running = False

    def is_running(self):
        return self.running

    def start(self):
        self.running = True


class DummyBot:
    def __init__(self):
        self._handlers = {}
        self.guilds = []
        self.synced = []
        self.views = []
        self.user = types.SimpleNamespace(id=99)

    def event(self, fn):
        self._handlers[fn.__name__] = fn
        return fn

    def add_listener(self, *_args, **_kwargs):
        return None

    def add_view(self, view):
        self.views.append(view)

    async def sync_application_commands(self, guild_id=None):
        self.synced.append(guild_id)

    def get_cog(self, _name):
        return None

    def get_guild(self, gid):
        for guild in self.guilds:
            if guild.id == gid:
                return guild
        return None


def test_on_guild_join_syncs_commands_and_tracks_guild(monkeypatch):
    bot = DummyBot()
    logger = types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None, warning=lambda *a, **k: None)
    context = types.SimpleNamespace(
        bot=bot,
        backup_loop=None,
        guild_ids=[],
        logger=logger,
        lazarus_ai=types.SimpleNamespace(start=lambda: None),
        log_action=lambda *a, **k: asyncio.sleep(0),
        commands_synced=False,
    )

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())
    monkeypatch.setattr("spectre.events.get_server_config", lambda _gid: {"ROOT_PREFIX": "test-root"})
    ensured = []
    monkeypatch.setattr("spectre.events.ensure_dir", lambda path: ensured.append(path))

    register(context)

    guild = types.SimpleNamespace(id=321)
    asyncio.run(bot._handlers["on_guild_join"](guild))

    assert context.guild_ids == [321]
    assert bot.synced == [321]
    assert any(path.endswith("missions") for path in ensured)
