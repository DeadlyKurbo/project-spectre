import config_app


def _reset_env(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)


def test_bot_token_available_uses_existing_token(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setattr(config_app, "BOT_TOKEN", "abc123")
    assert config_app.bot_token_available() is True


def test_bot_token_available_checks_discord_bot_token(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setattr(config_app, "BOT_TOKEN", "")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "xyz")
    assert config_app.bot_token_available() is True


def test_bot_token_available_checks_discord_token(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setattr(config_app, "BOT_TOKEN", None)
    monkeypatch.setenv("DISCORD_TOKEN", "from_discord_token")
    assert config_app.bot_token_available() is True


def test_bot_token_available_handles_empty_values(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setattr(config_app, "BOT_TOKEN", None)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "   ")
    monkeypatch.setenv("DISCORD_TOKEN", "\n\t")
    assert config_app.bot_token_available() is False
