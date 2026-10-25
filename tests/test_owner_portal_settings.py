from __future__ import annotations

import json

import owner_portal as owner_portal_mod
from owner_portal import (
    ModerationSettings,
    OWNER_USER_ID,
    OwnerSettings,
    build_change_entry,
    can_manage_fleet,
    load_owner_settings,
    set_operations_broadcast,
    _coerce_settings,  # type: ignore[attr-defined]
)


def test_owner_settings_copy_is_deep() -> None:
    original_entry = build_change_entry("Operator (1)", "Initial", "Baseline state")
    original = OwnerSettings(
        bot_version="1.0.0",
        latest_update="Launch",
        latest_update_priority="high-priority",
        managers=["1"],
        fleet_managers=["9"],
        chat_access=["7"],
        bot_active=True,
        moderation=ModerationSettings(),
        change_log=[original_entry],
    )

    clone = original.copy()
    clone.managers.append("2")
    clone.fleet_managers.append("10")
    clone.chat_access.append("11")
    clone.moderation.auto_moderation = False
    clone.change_log[0].action = "Edited"

    assert original.managers == ["1"]
    assert original.fleet_managers == ["9"]
    assert original.chat_access == ["7"]
    assert original.moderation.auto_moderation is True
    assert original.change_log[0].action == "Initial"
    assert original.latest_update_priority == "high-priority"


def test_coerce_settings_applies_defaults_and_filters() -> None:
    data = {
        "bot_version": "2.1",
        "latest_update": "Patched",
        "managers": ["5", "not-a-number", "3", "5"],
        "fleet_managers": ["6", "6", "bad"],
        "chat_access": ["7", "bad-id"],
        "bot_active": False,
        "moderation": {"auto_moderation": False, "link_blocking": True},
        "change_log": [
            {
                "timestamp": "2023-01-01T00:00:00+00:00",
                "actor": "Tester",
                "action": "Migrated",
                "details": "Updated schema",
            },
            {"timestamp": "", "actor": "", "action": ""},
        ],
    }

    settings = _coerce_settings(data)

    assert settings.bot_version == "2.1"
    assert settings.latest_update == "Patched"
    assert settings.latest_update_priority == "standard"
    assert settings.managers == ["3", "5"]
    assert settings.fleet_managers == ["6"]
    assert settings.chat_access == ["7"]
    assert settings.bot_active is False
    assert settings.moderation.auto_moderation is False
    assert settings.moderation.link_blocking is True
    assert settings.moderation.new_member_lock is False
    assert len(settings.change_log) == 1
    assert settings.change_log[0].action == "Migrated"


def test_append_log_entry_enforces_limit() -> None:
    settings = OwnerSettings(
        bot_version="",
        latest_update="",
        managers=[],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=ModerationSettings(),
        change_log=[],
    )

    for idx in range(5):
        settings.append_log_entry(
            build_change_entry("actor", f"Event {idx}", None), limit=3
        )

    assert len(settings.change_log) == 3
    assert [entry.action for entry in settings.change_log] == [
        "Event 2",
        "Event 3",
        "Event 4",
    ]


def test_build_change_entry_trims_details() -> None:
    entry = build_change_entry("user", "Action", "  detail  ")
    assert entry.details == "detail"
    assert entry.timestamp.endswith("+00:00")


def test_load_owner_settings_defaults_when_storage_read_fails(monkeypatch) -> None:
    def corrupt_read(_path: str, *, with_etag: bool = False):
        raise json.JSONDecodeError("Expecting value", "x", 0)

    monkeypatch.setattr(owner_portal_mod, "read_json", corrupt_read)
    settings, etag = load_owner_settings()
    assert settings.managers == []
    assert settings.bot_version == ""
    assert etag is None

    settings_etag, etag_out = load_owner_settings(with_etag=True)
    assert settings_etag.managers == []
    assert etag_out is None


def test_can_manage_fleet_checks_owner_and_custom_roles() -> None:
    managers = ["123"]
    fleet_managers = ["456"]

    assert can_manage_fleet(OWNER_USER_ID, managers, fleet_managers) is True
    assert can_manage_fleet("123", managers, fleet_managers) is True
    assert can_manage_fleet("456", managers, fleet_managers) is True
    assert can_manage_fleet("789", managers, fleet_managers) is False


def test_load_owner_settings_falls_back_when_storage_errors(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr("owner_portal.read_json", _boom)

    settings, etag = load_owner_settings(with_etag=True)

    assert settings.bot_version == ""
    assert settings.latest_update == ""
    assert settings.managers == []
    assert settings.fleet_managers == []
    assert settings.chat_access == []
    assert settings.bot_active is True
    assert settings.change_log == []
    assert etag is None


def test_set_operations_broadcast_skips_duplicate_updates(monkeypatch) -> None:
    existing_entry = build_change_entry("Ops", "Existing entry", "prior note")
    settings = OwnerSettings(
        bot_version="",
        latest_update="All systems normal",
        latest_update_priority="standard",
        managers=[],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=ModerationSettings(),
        change_log=[existing_entry],
    )
    save_calls: list[tuple[OwnerSettings, str | None]] = []

    monkeypatch.setattr(
        owner_portal_mod,
        "load_owner_settings",
        lambda *, with_etag=False: (settings.copy(), "etag-1"),
    )
    monkeypatch.setattr(
        owner_portal_mod,
        "save_owner_settings",
        lambda updated, *, etag=None: save_calls.append((updated.copy(), etag)) or True,
    )

    result = set_operations_broadcast(
        "All systems normal", priority="standard", actor="Director"
    )

    assert result.latest_update == "All systems normal"
    assert result.latest_update_priority == "standard"
    assert len(result.change_log) == 1
    assert [entry.action for entry in result.change_log] == ["Existing entry"]
    assert save_calls == []


def test_set_operations_broadcast_appends_log_when_changed(monkeypatch) -> None:
    settings = OwnerSettings(
        bot_version="",
        latest_update="All systems normal",
        latest_update_priority="standard",
        managers=[],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=ModerationSettings(),
        change_log=[],
    )
    save_calls: list[tuple[OwnerSettings, str | None]] = []

    monkeypatch.setattr(
        owner_portal_mod,
        "load_owner_settings",
        lambda *, with_etag=False: (settings.copy(), "etag-2"),
    )
    monkeypatch.setattr(
        owner_portal_mod,
        "save_owner_settings",
        lambda updated, *, etag=None: save_calls.append((updated.copy(), etag)) or True,
    )

    result = set_operations_broadcast(
        "Incident ongoing", priority="high-priority", actor="Director"
    )

    assert result.latest_update == "Incident ongoing"
    assert result.latest_update_priority == "high-priority"
    assert len(result.change_log) == 1
    assert result.change_log[0].action == "Operations broadcast updated"
    assert result.change_log[0].details == "high priority broadcast"
    assert len(save_calls) == 1
