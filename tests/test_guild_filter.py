from config_app import _filter_common_guilds, MANAGE_GUILD, ADMIN


def test_filter_common_guilds():
    user_guilds = [
        {"id": "1", "permissions": str(MANAGE_GUILD)},
        {"id": "2", "permissions": str(ADMIN)},
        {"id": "3", "permissions": "0"},
    ]
    bot_guilds = [
        {"id": "1"},
        {"id": "3"},
    ]
    filtered = _filter_common_guilds(user_guilds, bot_guilds)
    assert [g["id"] for g in filtered] == ["1"]
