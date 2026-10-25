import asyncio
import importlib
import sys

import pytest

import website_users


@pytest.fixture
def store(monkeypatch):
    data: dict[str, dict] = {}

    def fake_read(key):
        if key not in data:
            raise FileNotFoundError(key)
        return dict(data[key])

    def fake_save(key, payload):
        data[key] = dict(payload)

    monkeypatch.setattr(website_users, "read_json", fake_read)
    monkeypatch.setattr(website_users, "save_json", fake_save)
    return data


def test_registry_starts_empty(store):
    assert website_users.list_website_users() == []


def test_sign_ins_are_recorded_and_refreshed(store, monkeypatch):
    first = website_users.record_website_user({"id": "1059522006602752150", "username": "dk", "global_name": "  DK  ", "avatar": "a_1"})
    assert (first["username"], first["global_name"], first["avatar"]) == ("dk", "DK", "a_1")
    assert first["first_seen_at"] == first["last_seen_at"]
    assert website_users.record_website_user({"id": "42", "username": "ada"}) is None  # too short for a Discord ID
    website_users.record_website_user({"id": "4200000", "username": "ada"})

    users = store[website_users.WEBSITE_USERS_KEY]["users"]
    users["1059522006602752150"].update(first_seen_at="2020-01-01T00:00:00+00:00", last_seen_at="2020-01-01T00:00:00+00:00")
    users["4200000"]["last_seen_at"] = "2026-01-01T00:00:00+00:00"
    assert [user["id"] for user in website_users.list_website_users()] == ["4200000", "1059522006602752150"]

    again = website_users.record_website_user({"id": "1059522006602752150", "username": "dk2"})
    assert again["first_seen_at"] == "2020-01-01T00:00:00+00:00" and again["username"] == "dk2"
    assert again["global_name"] is None
    assert website_users.list_website_users()[0]["id"] == "1059522006602752150"


def test_invalid_accounts_are_ignored(store):
    for user in (None, {}, {"id": "abc"}, {"id": "123"}, "1059522006602752150"):
        assert website_users.record_website_user(user) is None
    assert store == {}


def test_registry_keeps_the_most_recently_seen(store, monkeypatch):
    monkeypatch.setattr(website_users, "WEBSITE_USERS_LIMIT", 2)
    for index in range(3):
        website_users.record_website_user({"id": f"1000{index}", "username": f"user{index}"})
        store[website_users.WEBSITE_USERS_KEY]["users"][f"1000{index}"]["last_seen_at"] = f"2026-10-0{index + 1}T00:00:00+00:00"
    website_users.record_website_user({"id": "10003", "username": "user3"})
    assert {user["id"] for user in website_users.list_website_users()} == {"10002", "10003"}


def test_the_site_records_each_signed_in_account_once_per_process(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    recorded = []
    monkeypatch.setattr(mod, "record_website_user", recorded.append)

    user = {"id": "1059522006602752150", "username": "dk"}
    asyncio.run(mod._remember_website_user(user))
    asyncio.run(mod._remember_website_user(user))
    assert recorded == [user]
    asyncio.run(mod._remember_website_user(user, refresh=True))  # a fresh sign-in
    asyncio.run(mod._remember_website_user({"username": "no id"}))
    assert recorded == [user, user]

    def broken(_user):
        raise OSError("storage down")

    monkeypatch.setattr(mod, "record_website_user", broken)
    asyncio.run(mod._remember_website_user({"id": "4200000"}))  # logged, not raised
    assert "4200000" not in mod._REMEMBERED_WEBSITE_USERS
