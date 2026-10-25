import asyncio
import importlib
from types import SimpleNamespace


def test_edit_raw_modal_handles_multiple_pages(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    const = importlib.reload(importlib.import_module("constants"))
    arch = importlib.reload(importlib.import_module("archivist"))

    existing = const.PAGE_SEPARATOR.join(["a" * const.CONTENT_MAX_LENGTH, "b"])

    async def make_modal():
        return arch.EditRawModal(SimpleNamespace(limit_edits=False), existing)

    modal = asyncio.run(make_modal())
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert modal.content.default_value == existing
    assert modal.content.max_length == len(existing)
    assert const.PAGE_SEPARATOR in modal.content.default_value

