import pytest

import guild_blacklist

SERVER_A = "1059522006602752150"
SERVER_B = "1189034578123456789"


@pytest.fixture
def store(monkeypatch):
    data: dict[str, dict] = {}

    def fake_read(key):
        if key not in data:
            raise FileNotFoundError(key)
        return dict(data[key])

    def fake_save(key, payload):
        data[key] = dict(payload)

    monkeypatch.setattr(guild_blacklist, "read_json", fake_read)
    monkeypatch.setattr(guild_blacklist, "save_json", fake_save)
    return data


def test_blacklist_starts_empty(store):
    assert guild_blacklist.list_blacklisted_guilds() == []
    assert guild_blacklist.blacklisted_guild_ids() == set()


def test_blacklist_and_lift_a_server(store):
    entry = guild_blacklist.blacklist_guild(
        f"  {SERVER_A} ", reason="  Distributing   illegal content ", actor="Ada (42)", name="Bad Place"
    )
    assert entry["guild_id"] == SERVER_A
    assert entry["reason"] == "Distributing illegal content"
    assert entry["banned_at"]

    guild_blacklist.blacklist_guild(SERVER_B, reason="Fraud", actor="Ada (42)")
    assert guild_blacklist.blacklisted_guild_ids() == {int(SERVER_A), int(SERVER_B)}
    listed = guild_blacklist.list_blacklisted_guilds()
    assert {item["guild_id"] for item in listed} == {SERVER_A, SERVER_B}
    assert next(item for item in listed if item["guild_id"] == SERVER_A)["name"] == "Bad Place"

    assert guild_blacklist.unblacklist_guild(SERVER_A) is True
    assert guild_blacklist.unblacklist_guild(SERVER_A) is False
    assert guild_blacklist.blacklisted_guild_ids() == {int(SERVER_B)}


def test_reblacklisting_keeps_the_known_server_name(store):
    guild_blacklist.blacklist_guild(SERVER_A, reason="First", actor="Ada (42)", name="Bad Place")
    guild_blacklist.blacklist_guild(SERVER_A, reason="Second", actor="Grace (43)")
    [entry] = guild_blacklist.list_blacklisted_guilds()
    assert entry["name"] == "Bad Place"
    assert entry["reason"] == "Second"
    assert entry["actor"] == "Grace (43)"


@pytest.mark.parametrize("guild_id", ["", "abc", "7", "12345678901234567890123456", None])
def test_blacklist_rejects_invalid_server_ids(store, guild_id):
    with pytest.raises(ValueError):
        guild_blacklist.blacklist_guild(guild_id, reason="Fraud", actor="Ada (42)")
    assert store == {}


def test_blacklist_requires_a_reason(store):
    with pytest.raises(ValueError):
        guild_blacklist.blacklist_guild(SERVER_A, reason="   ", actor="Ada (42)")


def test_malformed_entries_are_ignored(store):
    store[guild_blacklist.GUILD_BLACKLIST_KEY] = {
        "guilds": {SERVER_A: {"reason": "Fraud"}, "not-an-id": {"reason": "x"}, SERVER_B: "broken"}
    }
    assert guild_blacklist.blacklisted_guild_ids() == {int(SERVER_A)}


def test_bot_copy_follows_refreshes(store, monkeypatch):
    monkeypatch.setattr(guild_blacklist, "_bot_blacklist", frozenset())
    guild_blacklist.blacklist_guild(SERVER_A, reason="Fraud", actor="Ada (42)")
    assert not guild_blacklist.is_guild_blacklisted(SERVER_A)

    guild_blacklist.refresh_bot_blacklist()
    assert guild_blacklist.is_guild_blacklisted(SERVER_A)
    assert guild_blacklist.is_guild_blacklisted(int(SERVER_A))
    assert not guild_blacklist.is_guild_blacklisted(SERVER_B)
    assert not guild_blacklist.is_guild_blacklisted(None)

    guild_blacklist.unblacklist_guild(SERVER_A)
    guild_blacklist.refresh_bot_blacklist()
    assert not guild_blacklist.is_guild_blacklisted(SERVER_A)
