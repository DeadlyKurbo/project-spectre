import asyncio
import types

from cogs.archive import ArchiveCog


def test_resolve_menu_channel_id_prefers_legacy(monkeypatch):
    monkeypatch.setattr(
        "cogs.archive.get_config",
        lambda gid: {"archive_channel_id": "123456789012345678"},
    )
    monkeypatch.setattr("cogs.archive.get_server_config", lambda gid: {})
    monkeypatch.setattr("cogs.archive.extract_menu_channel_id", lambda cfg: 0)

    dummy = object()
    assert ArchiveCog._resolve_menu_channel_id(dummy, 42) == 123456789012345678


def test_resolve_menu_channel_id_uses_dashboard_when_legacy_missing(monkeypatch):
    monkeypatch.setattr("cogs.archive.get_config", lambda gid: {})
    sentinel_cfg = {"MENU_CHANNEL_ID": 9876543210}
    monkeypatch.setattr("cogs.archive.get_server_config", lambda gid: sentinel_cfg)
    monkeypatch.setattr(
        "cogs.archive.extract_menu_channel_id", lambda cfg: cfg["MENU_CHANNEL_ID"]
    )

    dummy = object()
    assert ArchiveCog._resolve_menu_channel_id(dummy, 7) == 9876543210


def test_deploy_for_guild_waits_until_ready_and_fetches_channel(monkeypatch):
    class DummyMessage:
        id = 2024

    class DummyChannel:
        id = 77

        async def send(self, **kwargs):
            return DummyMessage()

    class DummyGuild:
        id = 42

        def __init__(self):
            self._channel = DummyChannel()
            self.get_channel = lambda _channel_id: None
            self.get_channel_or_thread = self.get_channel

        async def fetch_channel(self, channel_id: int):
            if channel_id == self._channel.id:
                return self._channel
            raise RuntimeError("missing")

    waited = {"count": 0}
    bot = types.SimpleNamespace(wait_until_ready=None)

    async def wait_until_ready():
        waited["count"] += 1

    bot.wait_until_ready = wait_until_ready
    monkeypatch.setattr("cogs.archive.ArchiveView", lambda: object())
    cog = ArchiveCog(bot)

    monkeypatch.setattr(cog, "_resolve_menu_channel_id", lambda _gid: 77)
    monkeypatch.setattr("cogs.archive.archive_embed", lambda _gid: object())
    monkeypatch.setattr("cogs.archive.get_anchor", lambda _gid: None)

    anchored = {}
    monkeypatch.setattr(
        "cogs.archive.set_anchor",
        lambda gid, channel_id, message_id: anchored.update(
            {"gid": gid, "channel_id": channel_id, "message_id": message_id}
        ),
    )

    result = asyncio.run(cog.deploy_for_guild(DummyGuild()))

    assert "posted message" in result
    assert waited["count"] == 1
    assert anchored == {"gid": 42, "channel_id": 77, "message_id": 2024}
