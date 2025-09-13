import asyncio
import importlib


def test_root_view_custom_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    views = importlib.reload(importlib.import_module("views"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def build_view():
        return views.RootView()

    rv = loop.run_until_complete(build_view())
    ids = {getattr(child, "custom_id", None) for child in rv.children}

    assert {"login_root", "refresh_root", "bypass_root", "archivist_root", "forgot_root"} <= ids

    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())
