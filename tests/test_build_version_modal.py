import asyncio

import config


def test_build_version_modal_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "log_channel.json"))
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    config.set_build_version("v9.9.9")
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        from archivist import BuildVersionModal

        async def create_modal():
            return BuildVersionModal()

        modal = loop.run_until_complete(create_modal())
        assert modal.children[0].default_value == "v9.9.9"
    finally:
        asyncio.set_event_loop(None)
        loop.close()
