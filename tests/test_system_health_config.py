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
