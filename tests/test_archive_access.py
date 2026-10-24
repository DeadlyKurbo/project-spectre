import asyncio
import importlib
from types import SimpleNamespace

import pytest

import archive_access
import archive_lock
import storage_spaces


# --- standing from Discord data --------------------------------------------

GUILD = {
    "id": "77",
    "owner_id": "1",
    "roles": [
        {"id": "77", "permissions": "0"},
        {"id": "500", "permissions": str(0x8)},
        {"id": "600", "permissions": "1024"},
    ],
}


@pytest.fixture
def high_command_config(monkeypatch):
    monkeypatch.setattr(
        archive_access.server_config, "get_server_config", lambda gid: {"HIGH_COMMAND_ROLE_ID": "900"}
    )


def test_member_permissions_combine_everyone_and_member_roles():
    guild = {**GUILD, "roles": [{"id": "77", "permissions": "2048"}, {"id": "600", "permissions": "1024"}]}

    assert archive_access.member_permissions(guild, {600}) == 2048 | 1024
    assert archive_access.member_permissions(guild, set()) == 2048


def test_standing_for_plain_member(high_command_config):
    standing = archive_access.standing_from_discord(77, "42", {"roles": ["600"]}, GUILD)

    assert standing.roles == {600}
    assert not standing.is_owner and not standing.is_admin and not standing.is_high_command


def test_standing_admin_comes_from_role_permissions(high_command_config):
    standing = archive_access.standing_from_discord(77, "42", {"roles": ["500"]}, GUILD)

    assert standing.is_admin and standing.is_high_command and not standing.is_owner


def test_standing_owner_is_admin_and_high_command(high_command_config):
    standing = archive_access.standing_from_discord(77, "1", {"roles": []}, GUILD)

    assert standing.is_owner and standing.is_admin and standing.is_high_command


def test_standing_high_command_role(high_command_config):
    standing = archive_access.standing_from_discord(77, "42", {"roles": ["900"]}, GUILD)

    assert standing.is_high_command and not standing.is_admin


def test_member_lookup_is_cached_until_forced(monkeypatch):
    calls = []

    async def fake_get(api, token, path):
        calls.append(path)
        return {"roles": []}

    monkeypatch.setattr(archive_access, "_bot_get", fake_get)
    monkeypatch.setattr(archive_access, "_member_cache", {})

    async def run():
        await archive_access.fetch_member("api", "t", "77", "42")
        await archive_access.fetch_member("api", "t", "77", "42")
        await archive_access.fetch_member("api", "t", "77", "42", force=True)

    asyncio.run(run())
    assert calls == ["/guilds/77/members/42", "/guilds/77/members/42"]


# --- shared lockdown -------------------------------------------------------


@pytest.fixture
def lock_storage(monkeypatch, tmp_path):
    if not hasattr(storage_spaces, "set_local_root"):
        pytest.skip("requires the local storage backend")
    monkeypatch.setattr(storage_spaces, "_LOCAL_ROOT_OVERRIDE", str(tmp_path))
    monkeypatch.setattr(archive_lock, "_read_cache", {})
    return tmp_path


def test_lock_state_round_trips_through_storage(lock_storage):
    assert archive_lock.read_lock(77) is False

    archive_lock.write_lock(77, True, actor="Admiral")

    assert archive_lock.read_lock(77) is True
    assert archive_lock.is_locked(77) is True
    archive_lock.write_lock(77, False)
    assert archive_lock.is_locked(77) is False


def test_lock_read_failure_fails_closed(lock_storage, monkeypatch):
    def broken(_key):
        raise RuntimeError("storage down")

    monkeypatch.setattr(storage_spaces, "read_json", broken)

    assert archive_lock.is_locked(77) is True


def test_bot_lockdown_is_shared_and_survives_restart(lock_storage, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    arch = importlib.reload(importlib.import_module("archivist"))

    arch.lock_archive(77)
    assert archive_lock.read_lock(77) is True  # the website sees it

    # A restarted bot process starts with an empty in-memory map.
    arch = importlib.reload(arch)
    assert arch.is_archive_locked(77) is True

    assert arch.toggle_archive_lock(77) is False
    assert archive_lock.read_lock(77) is False


# --- Discord: approved one-time clearance actually opens the file ----------


def test_one_time_clearance_opens_file_in_discord(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    import utils

    (tmp_path / "intel").mkdir()
    (tmp_path / "intel" / "file1.txt").write_text("classified body")
    monkeypatch.setattr(utils, "DOSSIERS_DIR", str(tmp_path))
    main = importlib.reload(importlib.import_module("main"))
    import views

    grants = ["file1"]

    def one_time(user_id, category, item, guild_id=None):
        if item in grants:
            grants.remove(item)
            return True
        return False

    async def no_sequence(*_args, **_kwargs):
        return None

    async def no_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(views, "check_temp_clearance", one_time)
    monkeypatch.setattr(views, "run_access_sequence", no_sequence)
    monkeypatch.setattr(main, "get_required_roles", lambda *a, **k: {555})
    monkeypatch.setattr(main, "log_action", no_log)

    sent = {}

    class Response:
        async def send_message(self, *args, **kwargs):
            sent["args"], sent["kwargs"] = args, kwargs

        async def edit_message(self, *args, **kwargs):
            sent["args"], sent["kwargs"] = args, kwargs

    class Followup:
        async def send(self, *args, **kwargs):
            sent["args"], sent["kwargs"] = args, kwargs

    user = SimpleNamespace(
        id=42,
        mention="<@42>",
        roles=[SimpleNamespace(id=1)],
        guild_permissions=SimpleNamespace(administrator=False),
    )
    interaction = SimpleNamespace(
        user=user,
        guild=SimpleNamespace(id=1, owner_id=99, get_channel=lambda _cid: None),
        response=Response(),
        followup=Followup(),
    )

    select = main.CategorySelect()
    select.category = "intel"
    asyncio.run(select._show_with_sequence(interaction, "file1"))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert grants == []  # the one-time grant was used exactly once
    assert "Insufficient clearance" not in str(sent.get("args"))
    assert sent["kwargs"].get("embed") is not None
