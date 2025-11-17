import json

import config


def test_system_health_state_roundtrip(tmp_path):
    cfg = tmp_path / "health.json"
    config.CONFIG_FILE = str(cfg)

    state = config.get_system_health_state()
    assert state["status"] == "online"
    assert state["note"] == ""
    assert config.get_system_health().startswith("✅")

    config.set_system_health_state("maintenance", "Upgrades in progress")
    saved = json.loads(cfg.read_text())
    assert saved["system_health_state"] == {
        "status": "maintenance",
        "note": "Upgrades in progress",
    }
    assert "Maintenance" in saved["system_health"]

    refreshed = config.get_system_health_state()
    assert refreshed["status"] == "maintenance"
    assert refreshed["note"] == "Upgrades in progress"
    assert config.get_system_health().startswith("Maintenance")


def test_system_health_state_legacy_string(tmp_path):
    cfg = tmp_path / "legacy.json"
    config.CONFIG_FILE = str(cfg)
    legacy_value = "Legacy signal"
    cfg.write_text(json.dumps({"system_health": legacy_value}))

    state = config.get_system_health_state()
    assert state["status"] == "online"
    assert state["note"] == legacy_value
    assert config.get_system_health() == legacy_value


def test_site_lock_state_roundtrip(tmp_path):
    cfg = tmp_path / "lock.json"
    config.CONFIG_FILE = str(cfg)

    state = config.get_site_lock_state()
    assert state["enabled"] is False
    assert state["message"] == config.SITE_LOCK_MESSAGE_DEFAULT
    assert state["actor"] is None

    config.set_site_lock_state(True, actor="Operator", message="  Custom warning  ")
    saved = json.loads(cfg.read_text())
    assert saved["site_lock"]["enabled"] is True
    assert saved["site_lock"]["message"] == "Custom warning"
    assert "enabled_at" in saved["site_lock"] and saved["site_lock"]["enabled_at"]

    refreshed = config.get_site_lock_state()
    assert refreshed["enabled"] is True
    assert refreshed["actor"] == "Operator"
    assert refreshed["message"] == "Custom warning"

    config.set_site_lock_state(False)
    cleared = config.get_site_lock_state()
    assert cleared["enabled"] is False
    assert cleared["message"] == config.SITE_LOCK_MESSAGE_DEFAULT
