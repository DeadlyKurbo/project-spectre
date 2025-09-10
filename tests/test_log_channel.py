import json

import config


def test_log_channel_roundtrip(tmp_path):
    log_file = tmp_path / "log_channel.json"
    config.CONFIG_FILE = str(log_file)
    assert config.get_log_channel() is None
    config.set_log_channel(123456789)
    assert config.get_log_channel() == 123456789
    assert json.loads(log_file.read_text()) == {"log_channel_id": 123456789}
