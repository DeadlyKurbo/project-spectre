"""Tests for mission report configuration and storage."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def test_normalise_mission_reports_settings():
    config_app = importlib.import_module("config_app")
    normalise = config_app._normalise_mission_reports_settings

    assert normalise(None) == {}
    assert normalise({"enabled": True}) == {"enabled": True}
    cleaned = normalise(
        {
            "enabled": True,
            "submitter_roles": ["123", 456, "bad"],
            "reviewer_roles": [789],
            "review_channel": "111",
            "menu_channel": "222",
            "archive_category": "missions",
            "default_clearance_role": "333",
            "menu": {"title": "Reports", "description": "Submit here"},
        }
    )
    assert cleaned["enabled"] is True
    assert cleaned["submitter_roles"] == [123, 456]
    assert cleaned["reviewer_roles"] == [789]
    assert cleaned["review_channel"] == 111
    assert cleaned["menu_channel"] == 222
    assert cleaned["archive_category"] == "missions"
    assert cleaned["default_clearance_role"] == 333
    assert cleaned["menu"]["title"] == "Reports"


def test_save_and_move_report(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("GUILD_ID", "1")

    storage: dict[str, bytes] = {}

    def fake_save_json(key, data):
        storage[key] = json.dumps(data).encode("utf-8")

    def fake_read_json(key):
        raw = storage.get(key)
        if raw is None:
            raise FileNotFoundError(key)
        return json.loads(raw.decode("utf-8"))

    def fake_delete_file(key):
        storage.pop(key, None)

    def fake_list_dir(prefix, limit=1000):
        names = sorted(
            path[len(prefix) + 1 :]
            for path in storage
            if path.startswith(prefix.rstrip("/") + "/") or path.startswith(prefix + "/")
        )
        files = []
        for name in names:
            if name.endswith(".json"):
                files.append((name.split("/")[-1], 10))
        return [], files

    import sys

    sys.modules.pop("mission_reports", None)
    mr = importlib.import_module("mission_reports")
    monkeypatch.setattr(mr, "save_json", fake_save_json)
    monkeypatch.setattr(mr, "ss_read_json", fake_read_json)
    monkeypatch.setattr(mr, "delete_file", fake_delete_file)
    monkeypatch.setattr(mr, "list_dir", fake_list_dir)
    monkeypatch.setattr(mr, "_generate_report_id", lambda _gid: "MR-Test-01")

    fields = {
        "mission_name": "Op Falcon",
        "date": "2026-05-18",
        "objectives": "Secure the zone",
        "outcome": "Success",
        "notes": "",
    }
    report_id = mr.save_report(99, 42, fields)
    assert report_id.startswith("MR-")

    pending = mr.load_report(99, report_id, "pending")
    assert pending["submitter_id"] == 42
    assert pending["fields"]["mission_name"] == "Op Falcon"

    moved = mr._move_report(99, report_id, "pending", "approved")
    assert moved["id"] == report_id
    with pytest.raises(Exception):
        mr.load_report(99, report_id, "pending")

    approved = mr.load_report(99, report_id, "approved")
    assert approved["fields"]["outcome"] == "Success"


def test_format_report_for_dossier():
    import sys

    sys.modules.pop("mission_reports", None)
    mr = importlib.import_module("mission_reports")
    body = mr.format_report_for_dossier(
        {
            "mission_name": "Test",
            "date": "Today",
            "objectives": "Do thing",
            "outcome": "Done",
            "notes": "None",
        },
        {"id": "MR-1", "submitted_at": "2026-01-01", "submitter_id": 7},
    )
    assert "MISSION REPORT" in body
    assert "Test" in body
    assert "<@7>" in body
