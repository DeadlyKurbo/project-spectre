import json

import config


def test_min_account_age_roundtrip(tmp_path):
    cfg = tmp_path / "age.json"
    config.CONFIG_FILE = str(cfg)
    assert config.get_min_account_age_days() is None
    config.set_min_account_age_days(14)
    assert config.get_min_account_age_days() == 14
    assert json.loads(cfg.read_text()) == {"min_account_age_days": 14}
