import importlib
import asyncio


def test_category_select_builds_options(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))
    monkeypatch.setattr(
        main, "load_folder_map", lambda: {"intel": "id1", "reports": "id2"}
    )

    select = main.CategorySelect()
    labels = [opt.label for opt in select.options]
    values = [opt.value for opt in select.options]

    assert labels == ["Intel", "Reports"]
    assert values == ["intel", "reports"]
    loop.close()
