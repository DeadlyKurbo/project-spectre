import os
import config


def test_config_uses_log_channel_json(tmp_path, monkeypatch):
    # Ensure default CONFIG_FILE points to log_channel.json
    expected = os.path.join(os.path.dirname(config.__file__), 'log_channel.json')
    assert config.CONFIG_FILE == expected

    # Use temporary directory to avoid touching real file
    fake = tmp_path / 'log_channel.json'
    monkeypatch.setattr(config, 'CONFIG_FILE', str(fake))
    config.set_log_channel(42)
    assert fake.exists()
    assert config.get_log_channel() == 42
