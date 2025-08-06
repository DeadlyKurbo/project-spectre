import os
import importlib
import config


def test_config_uses_log_channel_json(tmp_path, monkeypatch):
    # Ensure default CONFIG_FILE points to log_channel.json
    monkeypatch.delenv("SPECTRE_DATA_DIR", raising=False)
    cfg = importlib.reload(config)
    expected = os.path.join(os.path.dirname(cfg.__file__), 'log_channel.json')
    assert cfg.CONFIG_FILE == expected

    # Use temporary directory to avoid touching real file
    fake = tmp_path / 'log_channel.json'
    monkeypatch.setattr(cfg, 'CONFIG_FILE', str(fake))
    cfg.set_log_channel(42)
    assert fake.exists()
    assert cfg.get_log_channel() == 42
    importlib.reload(config)


def test_config_respects_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRE_DATA_DIR", str(tmp_path))
    cfg = importlib.reload(config)
    expected = tmp_path / 'log_channel.json'
    assert cfg.CONFIG_FILE == str(expected)
    cfg.set_log_channel(99)
    assert expected.exists()
    assert cfg.get_log_channel() == 99
    # Clean up for other tests
    monkeypatch.delenv("SPECTRE_DATA_DIR", raising=False)
    importlib.reload(config)
