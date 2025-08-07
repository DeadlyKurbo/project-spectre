import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class DummyResponse:
    def __init__(self):
        self.kwargs = None

    async def defer(self, *args, **kwargs):
        self.kwargs = kwargs


class DummyFollowup:
    def __init__(self):
        self.kwargs = None

    async def send(self, *args, **kwargs):
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
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "root")
    monkeypatch.chdir(tmp_path)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "id1", "name": "Foo"},
            {"id": "id2", "name": "Bar"},
        ]
    }
    monkeypatch.setattr(main, "get_drive_service", lambda: service)
    inter = DummyInteraction()
    asyncio.run(main.refresh_cmd(inter))
    data = json.loads(Path("folder_map.json").read_text())
    assert data == {"foo": "id1", "bar": "id2"}
    assert inter.response.kwargs == {"ephemeral": True}
    assert "Folder map updated" in inter.followup.kwargs["content"]
    loop.close()
