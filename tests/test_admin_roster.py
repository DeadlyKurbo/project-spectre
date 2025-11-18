"""Tests for admin roster helpers."""
from __future__ import annotations

import pytest

import admin_roster
from admin_roster import ADMIN_BIOS_KEY, load_admin_bios, save_admin_bio


def test_load_admin_bios_filters_invalid_entries(monkeypatch):
    payload = {
        "abc": "ignored",
        "42": {"bio": "  hello  ", "updated_at": "2024-01-01T00:00:00"},
        "41": {"bio": "   "},
        "40": "Plain text",
    }

    monkeypatch.setattr(admin_roster, "read_json", lambda key: payload)
    bios = load_admin_bios()
    assert set(bios.keys()) == {"40", "42"}
    assert bios["42"].bio == "hello"
    assert bios["40"].bio == "Plain text"


def test_load_admin_bios_handles_missing_file(monkeypatch):
    def fake_read(key):
        raise FileNotFoundError(key)

    monkeypatch.setattr(admin_roster, "read_json", fake_read)
    assert load_admin_bios() == {}


def test_save_admin_bio_persists_and_normalises(monkeypatch):
    storage: dict[str, dict] = {}

    def fake_read(key):
        return storage.get(key, {})

    def fake_write(key, data):
        storage[key] = data

    monkeypatch.setattr(admin_roster, "read_json", fake_read)
    monkeypatch.setattr(admin_roster, "write_json", fake_write)

    result = save_admin_bio("42", "  multi\nline  ")
    assert "42" in result
    assert result["42"].bio == "multi\nline"
    assert storage[ADMIN_BIOS_KEY]["42"]["bio"] == "multi\nline"


def test_save_admin_bio_converts_html_breaks(monkeypatch):
    storage: dict[str, dict] = {}

    def fake_read(key):
        return storage.get(key, {})

    def fake_write(key, data):
        storage[key] = data

    monkeypatch.setattr(admin_roster, "read_json", fake_read)
    monkeypatch.setattr(admin_roster, "write_json", fake_write)

    save_admin_bio("99", "Line1<br>Line2<BR />Line3")

    assert storage[ADMIN_BIOS_KEY]["99"]["bio"] == "Line1\nLine2\nLine3"


def test_save_admin_bio_clears_when_empty(monkeypatch):
    storage = {ADMIN_BIOS_KEY: {"42": {"bio": "Keep"}}}

    def fake_read(key):
        return storage.get(key, {})

    def fake_write(key, data):
        storage[key] = data

    monkeypatch.setattr(admin_roster, "read_json", fake_read)
    monkeypatch.setattr(admin_roster, "write_json", fake_write)

    result = save_admin_bio("42", "   ")
    assert "42" not in result
    assert storage[ADMIN_BIOS_KEY] == {}


def test_save_admin_bio_requires_numeric_id():
    with pytest.raises(ValueError):
        save_admin_bio("abc", "hi")
