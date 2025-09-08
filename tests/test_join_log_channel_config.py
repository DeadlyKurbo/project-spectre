import json

import config


def test_join_log_channel_roundtrip(tmp_path):
    cfg = tmp_path / "join_log.json"
    config.CONFIG_FILE = str(cfg)
    assert config.get_join_log_channel() is None
    config.set_join_log_channel(987654321)
    assert config.get_join_log_channel() == 987654321
    assert json.loads(cfg.read_text()) == {"join_log_channel_id": 987654321}
