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
