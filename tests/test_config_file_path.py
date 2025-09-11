import config


def test_config_uses_storage_based_config(tmp_path, monkeypatch):
    # Default path should point inside the storage space
    assert config.CONFIG_FILE == "config/config.json"

    # Use temporary directory to avoid touching real storage during tests
    fake = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", str(fake))
    config.set_min_account_age_days(42)
    assert fake.exists()
    assert config.get_min_account_age_days() == 42
