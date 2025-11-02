from __future__ import annotations

from owner_portal import (
    ModerationSettings,
    OwnerSettings,
    build_change_entry,
    _coerce_settings,  # type: ignore[attr-defined]
)


def test_owner_settings_copy_is_deep() -> None:
    original_entry = build_change_entry("Operator (1)", "Initial", "Baseline state")
    original = OwnerSettings(
        bot_version="1.0.0",
        latest_update="Launch",
        managers=["1"],
        bot_active=True,
        moderation=ModerationSettings(),
        change_log=[original_entry],
    )

    clone = original.copy()
    clone.managers.append("2")
    clone.moderation.auto_moderation = False
    clone.change_log[0].action = "Edited"

    assert original.managers == ["1"]
    assert original.moderation.auto_moderation is True
    assert original.change_log[0].action == "Initial"


def test_coerce_settings_applies_defaults_and_filters() -> None:
    data = {
        "bot_version": "2.1",
        "latest_update": "Patched",
        "managers": ["5", "not-a-number", "3", "5"],
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
    assert settings.managers == ["3", "5"]
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
