import asyncio
import types

import guild_blacklist
from spectre.context import SpectreContext
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


def _make_context(bot, logger, guild_ids):
    context = types.SimpleNamespace(
        bot=bot,
        backup_loop=None,
        guild_ids=guild_ids,
        logger=logger,
        lazarus_ai=types.SimpleNamespace(start=lambda: None),
        log_action=lambda *a, **k: asyncio.sleep(0),
        commands_synced=False,
    )
    context.refresh_guild_blacklist = types.MethodType(SpectreContext.refresh_guild_blacklist, context)
    return context


def test_on_ready_refreshes_archive_menus(monkeypatch):
    bot = DummyBot()
    guild = types.SimpleNamespace(id=404)
    bot.guilds = [guild]

    logs: list[str] = []
    logger = types.SimpleNamespace(
        info=lambda *a, **k: logs.append(str(a[0]) if a else ""),
        exception=lambda *a, **k: logs.append(str(a[0]) if a else ""),
        warning=lambda *a, **k: logs.append(str(a[0]) if a else ""),
    )
    context = _make_context(bot, logger, [404])

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())
    monkeypatch.setattr("spectre.events.get_server_config", lambda _gid: {"ROOT_PREFIX": "test-root"})
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr("spectre.events.update_status_message", lambda _bot: asyncio.sleep(0))

    refreshed: list[int] = []

    async def _refresh(g):
        refreshed.append(g.id)

    monkeypatch.setattr("spectre.events.refresh_menus", _refresh)

    register(context)

    async def _run_ready():
        await bot._handlers["on_ready"]()
        await asyncio.sleep(0)

    asyncio.run(_run_ready())

    assert refreshed == [404]


def test_on_guild_join_syncs_commands_and_tracks_guild(monkeypatch):
    bot = DummyBot()
    logger = types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None, warning=lambda *a, **k: None)
    context = _make_context(bot, logger, [])

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
    context = _make_context(bot, logger, [808])

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())

    def _failing_get_server_config(_gid):
        raise RuntimeError("remote config unavailable")

    monkeypatch.setattr("spectre.events.get_server_config", _failing_get_server_config)
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr("spectre.events.update_status_message", lambda _bot: asyncio.sleep(0))
    monkeypatch.setattr("spectre.events.refresh_menus", lambda _guild: asyncio.sleep(0))

    register(context)

    async def _run_ready():
        await bot._handlers["on_ready"]()

    asyncio.run(_run_ready())

    assert len(bot.views) == 1


def test_on_ready_does_not_duplicate_root_views(monkeypatch):
    bot = DummyBot()
    guild = types.SimpleNamespace(id=909)
    bot.guilds = [guild]

    logger = types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None, warning=lambda *a, **k: None)
    context = _make_context(bot, logger, [909])

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())
    monkeypatch.setattr("spectre.events.get_server_config", lambda _gid: {"ROOT_PREFIX": "test-root"})
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr("spectre.events.update_status_message", lambda _bot: asyncio.sleep(0))
    monkeypatch.setattr("spectre.events.refresh_menus", lambda _guild: asyncio.sleep(0))

    register(context)

    async def _run_twice():
        await bot._handlers["on_ready"]()
        await bot._handlers["on_ready"]()

    asyncio.run(_run_twice())

    assert len(bot.views) == 1


def _quiet_logger():
    return types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None, warning=lambda *a, **k: None)


def test_on_guild_join_reads_the_blacklist_and_still_syncs_commands(monkeypatch):
    bot = DummyBot()
    context = _make_context(bot, _quiet_logger(), [])

    monkeypatch.setattr("spectre.events.create_backup_loop", lambda _context: DummyLoop())
    monkeypatch.setattr("spectre.events.get_server_config", lambda _gid: {"ROOT_PREFIX": "test-root"})
    monkeypatch.setattr("spectre.events.ensure_dir", lambda _path: None)
    monkeypatch.setattr(guild_blacklist, "_bot_blacklist", frozenset())
    monkeypatch.setattr(guild_blacklist, "blacklisted_guild_ids", lambda: {321})

    register(context)
    asyncio.run(bot._handlers["on_guild_join"](types.SimpleNamespace(id=321)))

    # The gate refuses its interactions straight away, and members still see
    # the commands so they get the ban notice.
    assert guild_blacklist.is_guild_blacklisted(321)
    assert bot.synced == [321]


def test_blacklist_read_failure_keeps_the_last_known_list(monkeypatch):
    context = _make_context(DummyBot(), _quiet_logger(), [])
    monkeypatch.setattr(guild_blacklist, "_bot_blacklist", frozenset({321}))

    def _storage_down():
        raise RuntimeError("storage down")

    monkeypatch.setattr(guild_blacklist, "blacklisted_guild_ids", _storage_down)
    asyncio.run(context.refresh_guild_blacklist())

    assert guild_blacklist.is_guild_blacklisted(321)
