import asyncio
import importlib
import json
from pathlib import Path

import pytest


class DummyResponse:
    def __init__(self):
        self.kwargs = None

    async def defer(self, *args, **kwargs):
        self.kwargs = kwargs


class DummyFollowup:
    def __init__(self):
        self.args = None
        self.kwargs = None

    async def send(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.user = type("User", (), {})()
        self.guild = type("Guild", (), {})()


def test_refresh_command(monkeypatch, tmp_path):
    pytest.importorskip("googleapiclient.discovery")
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.chdir(tmp_path)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))

    def fake_refresh_folder_map():
        data = {"foo": "id1", "bar": "id2"}
        Path("folder_map.json").write_text(json.dumps(data))
        return data

    monkeypatch.setattr(main, "refresh_folder_map", fake_refresh_folder_map)

    inter = DummyInteraction()
    cog = main.bot.get_cog("Refresh")
    asyncio.run(cog.refresh(inter))
    data = json.loads(Path("folder_map.json").read_text())
    assert data == {"foo": "id1", "bar": "id2"}
    assert inter.response.kwargs == {"ephemeral": True}
    message = inter.followup.kwargs.get("content") or inter.followup.args[0]
    assert "Folder map updated" in message
    loop.close()
