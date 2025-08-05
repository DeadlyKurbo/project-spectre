import json

import utils


def test_log_channel_roundtrip(tmp_path):
    log_file = tmp_path / "log_channel.json"
    utils.LOG_CHANNEL_FILE = str(log_file)
    assert utils.load_log_channel() is None
    utils.save_log_channel(123456789)
    assert utils.load_log_channel() == 123456789
    assert json.loads(log_file.read_text()) == {"channel_id": 123456789}
