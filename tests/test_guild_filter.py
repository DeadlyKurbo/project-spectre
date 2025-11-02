import config_app

from config_app import MANAGE_GUILD, ADMIN


def test_filter_common_guilds():
    original_checker = config_app.bot_token_available
    config_app.bot_token_available = lambda: True
    try:
        user_guilds = [
            {"id": "1", "permissions": str(MANAGE_GUILD)},
            {"id": "2", "permissions": str(ADMIN)},
            {"id": "3", "permissions": "0"},
        ]
        bot_guilds = [
            {"id": "1"},
            {"id": "3"},
        ]
        filtered = config_app._filter_common_guilds(user_guilds, bot_guilds)
    finally:
        config_app.bot_token_available = original_checker
    assert [g["id"] for g in filtered] == ["1"]


def test_filter_common_guilds_without_bot_token():
    original_checker = config_app.bot_token_available
    config_app.bot_token_available = lambda: False
    user_guilds = [
        {"id": "1", "permissions": str(MANAGE_GUILD)},
        {"id": "2", "permissions": str(ADMIN)},
        {"id": "3", "permissions": "0"},
    ]
    bot_guilds: list[dict] = []
    try:
        filtered = config_app._filter_common_guilds(user_guilds, bot_guilds)
    finally:
        config_app.bot_token_available = original_checker
    assert [g["id"] for g in filtered] == ["1", "2"]
