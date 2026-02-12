from config_app import _normalise_access_sequence_settings, _normalise_admin_settings, _normalise_protocol_settings
from server_config import _apply_dashboard_overrides, DEFAULT_CONFIG


def test_protocol_settings_cleaned_and_trimmed():
    payload = {
        "epsilon": {
            "launch_code": "  LAUNCH-ALPHA  ",
            "owner_code": "",
            "xo_code": " xo- fragment  ",
            "fleet_code": "FLEET-" + "X" * 200,
        },
        "omega": {
            "fragment_one": "  omega-one  ",
            "fragment_two": None,
        },
    }

    cleaned = _normalise_protocol_settings(payload)

    assert cleaned["epsilon"]["launch_code"] == "LAUNCH-ALPHA"
    assert "owner_code" not in cleaned["epsilon"]
    assert cleaned["epsilon"]["xo_code"] == "xo- fragment"
    assert len(cleaned["epsilon"]["fleet_code"]) == 128
    assert cleaned["omega"]["fragment_one"] == "omega-one"
    assert "fragment_two" not in cleaned["omega"]


def test_protocol_settings_override_server_config_codes():
    base = dict(DEFAULT_CONFIG)
    override = {
        **base,
        "protocols": {
            "epsilon": {
                "launch_code": "EPSILON-001",
                "owner_code": "OWNER-001",
                "xo_code": "XO-001",
                "fleet_code": "FLEET-001",
            },
            "omega": {
                "fragment_one": "ALPHA-FRAG",
                "fragment_two": "BETA-FRAG",
            },
        },
    }

    derived = _apply_dashboard_overrides(override)

    assert derived["EPSILON_LAUNCH_CODE"] == "EPSILON-001"
    assert derived["EPSILON_OWNER_CODE"] == "OWNER-001"
    assert derived["EPSILON_XO_CODE"] == "XO-001"
    assert derived["EPSILON_FLEET_CODE"] == "FLEET-001"
    assert derived["OMEGA_KEY_FRAGMENT_1"] == "ALPHA-FRAG"
    assert derived["OMEGA_KEY_FRAGMENT_2"] == "BETA-FRAG"


def test_access_sequence_settings_cleaned_and_bounded():
    payload = {
        "enabled": True,
        "chance_percent": " 133.7 ",
    }

    cleaned = _normalise_access_sequence_settings(payload)

    assert cleaned == {"enabled": True, "chance_percent": 100.0}


def test_access_sequence_settings_override_server_config():
    base = dict(DEFAULT_CONFIG)
    override = {
        **base,
        "archive": {
            "access_sequence": {
                "enabled": False,
                "chance_percent": 7.5,
            }
        },
    }

    derived = _apply_dashboard_overrides(override)

    assert derived["ACCESS_SEQUENCE_ENABLED"] is False
    assert derived["ACCESS_SEQUENCE_CHANCE"] == 7.5


def test_admin_settings_cleaned_for_dashboard_payload():
    payload = {
        "log_channel": " 123456789012345678 ",
        "audit_events": {
            "file_access": True,
            "file_delete": False,
            "ignored": "yes",
        },
        "safeguards": {
            "mass_delete_protection": True,
            "suspicious_activity_alerts": False,
            "ignored": 1,
        },
    }

    cleaned = _normalise_admin_settings(payload)

    assert cleaned == {
        "log_channel": 123456789012345678,
        "audit_events": {"file_access": True, "file_delete": False},
        "safeguards": {
            "mass_delete_protection": True,
            "suspicious_activity_alerts": False,
        },
    }


def test_admin_settings_override_server_config():
    base = dict(DEFAULT_CONFIG)
    override = {
        **base,
        "admin": {
            "log_channel": 222333444555666777,
            "audit_events": {
                "file_access": True,
                "archivist_delete": True,
            },
            "safeguards": {
                "mass_delete_protection": True,
                "suspicious_activity_alerts": True,
            },
        },
    }

    derived = _apply_dashboard_overrides(override)

    assert derived["ADMIN_LOG_CHANNEL_ID"] == 222333444555666777
    assert derived["ADMIN_AUDIT_EVENTS"] == {"file_access": True, "archivist_delete": True}
    assert derived["ADMIN_SAFEGUARDS"] == {
        "mass_delete_protection": True,
        "suspicious_activity_alerts": True,
    }
