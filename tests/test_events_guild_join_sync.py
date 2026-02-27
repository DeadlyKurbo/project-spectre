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


def test_on_ready_refreshes_and_redeploys_archive_menus(monkeypatch):
    bot = DummyBot()
    guild = types.SimpleNamespace(id=404)
    bot.guilds = [guild]

    logs: list[str] = []
    logger = types.SimpleNamespace(
        info=lambda *a, **k: logs.append(str(a[0]) if a else ""),
        exception=lambda *a, **k: logs.append(str(a[0]) if a else ""),
        warning=lambda *a, **k: logs.append(str(a[0]) if a else ""),
    )
    context = types.SimpleNamespace(
        bot=bot,
        backup_loop=None,
        guild_ids=[404],
        logger=logger,
        lazarus_ai=types.SimpleNamespace(start=lambda: None),
        log_action=lambda *a, **k: asyncio.sleep(0),
        commands_synced=False,
    )

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())
    monkeypatch.setattr("spectre.events.get_server_config", lambda _gid: {"ROOT_PREFIX": "test-root"})
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr("spectre.events.update_status_message", lambda _bot: asyncio.sleep(0))

    refreshed: list[int] = []

    async def _refresh(g):
        refreshed.append(g.id)

    monkeypatch.setattr("spectre.events.refresh_menus", _refresh)

    class DummyArchiveCog:
        def __init__(self):
            self.deployed: list[int] = []

        async def deploy_for_guild(self, g):
            self.deployed.append(g.id)
            return "updated"

    dummy_cog = DummyArchiveCog()
    monkeypatch.setattr("spectre.events.ArchiveCog", DummyArchiveCog)
    monkeypatch.setattr(bot, "get_cog", lambda _name: dummy_cog)

    register(context)

    async def _run_ready():
        await bot._handlers["on_ready"]()
        await asyncio.sleep(0)

    asyncio.run(_run_ready())

    assert refreshed == [404]
    assert dummy_cog.deployed == [404]


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


def test_on_ready_registers_views_even_when_config_unavailable(monkeypatch):
    bot = DummyBot()
    guild = types.SimpleNamespace(id=808)
    bot.guilds = [guild]

    logger = types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None, warning=lambda *a, **k: None)
    context = types.SimpleNamespace(
        bot=bot,
        backup_loop=None,
        guild_ids=[808],
        logger=logger,
        lazarus_ai=types.SimpleNamespace(start=lambda: None),
        log_action=lambda *a, **k: asyncio.sleep(0),
        commands_synced=False,
    )

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())

    def _failing_get_server_config(_gid):
        raise RuntimeError("remote config unavailable")

    monkeypatch.setattr("spectre.events.get_server_config", _failing_get_server_config)
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr("spectre.events.update_status_message", lambda _bot: asyncio.sleep(0))
    monkeypatch.setattr("spectre.events.refresh_menus", lambda _guild: asyncio.sleep(0))
    monkeypatch.setattr("spectre.events.ArchiveCog", object)
    monkeypatch.setattr(bot, "get_cog", lambda _name: None)

    register(context)

    async def _run_ready():
        await bot._handlers["on_ready"]()

    asyncio.run(_run_ready())

    assert len(bot.views) == 1


def test_on_ready_skips_legacy_deploy_when_modern_menu_configured(monkeypatch):
    bot = DummyBot()
    guild = types.SimpleNamespace(id=909)
    bot.guilds = [guild]

    logger = types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None, warning=lambda *a, **k: None)
    context = types.SimpleNamespace(
        bot=bot,
        backup_loop=None,
        guild_ids=[909],
        logger=logger,
        lazarus_ai=types.SimpleNamespace(start=lambda: None),
        log_action=lambda *a, **k: asyncio.sleep(0),
        commands_synced=False,
    )

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())
    monkeypatch.setattr("spectre.events.get_server_config", lambda _gid: {"ROOT_PREFIX": "test-root", "MENU_CHANNEL_ID": 1001})
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr("spectre.events.update_status_message", lambda _bot: asyncio.sleep(0))
    monkeypatch.setattr("spectre.events.refresh_menus", lambda _guild: asyncio.sleep(0))

    class DummyArchiveCog:
        def __init__(self):
            self.deployed: list[int] = []

        async def deploy_for_guild(self, g):
            self.deployed.append(g.id)
            return "updated"

    dummy_cog = DummyArchiveCog()
    monkeypatch.setattr("spectre.events.ArchiveCog", DummyArchiveCog)
    monkeypatch.setattr(bot, "get_cog", lambda _name: dummy_cog)

    register(context)

    async def _run_ready():
        await bot._handlers["on_ready"]()
        await asyncio.sleep(0)

    asyncio.run(_run_ready())

    assert dummy_cog.deployed == []
