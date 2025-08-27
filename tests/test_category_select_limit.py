import asyncio

import archivist
from nextcord.ui import Select


def test_category_select_limit(monkeypatch):
    monkeypatch.setattr(archivist, "list_categories", lambda: [f"cat{i}" for i in range(30)])

    async def build_view():
        return archivist.ArchiveFileView()

    loop = asyncio.new_event_loop()
    view = loop.run_until_complete(build_view())
    loop.close()
    assert isinstance(view.children[0], Select)
    assert len(view.children[0].options) == 25


def test_archived_category_select_limit(monkeypatch):
    monkeypatch.setattr(
        archivist, "list_archived_categories", lambda: [f"arch{i}" for i in range(30)]
    )

    async def build_archived_views():
        view = archivist.ViewArchivedFilesView()
        restore = archivist.RestoreArchivedFileView()
        return view, restore

    loop = asyncio.new_event_loop()
    view, restore_view = loop.run_until_complete(build_archived_views())
    loop.close()

    assert isinstance(view.children[0], Select)
    assert len(view.children[0].options) == 25

    assert isinstance(restore_view.children[0], Select)
    assert len(restore_view.children[0].options) == 25
