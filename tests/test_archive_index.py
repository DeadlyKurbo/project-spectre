import base64
import importlib
import json
import sys

import itsdangerous
import pytest
from fastapi.testclient import TestClient

import archive_index
import dossier
import storage_spaces

GUILD_ID = 77
CONFIG = {"ROOT_PREFIX": "arch-root"}
FILES = {
    "fleet/alpha.json": {"subject": "Alpha", "status": "Active"},
    "fleet/sub/bravo.txt": "bravo body",
    "Tech & Equipment/rifle.txt": "rifle",
    "intel-extra/charlie.txt": "charlie",
    "_archived/missions/old-op.txt": "old",
    "acl/clearance.json": {"Fleet": {"ALPHA": [555]}},
    "fleet/notes.md": "not a dossier",
}


@pytest.fixture
def archive_root(monkeypatch, tmp_path):
    if not hasattr(storage_spaces, "set_local_root"):
        pytest.skip("requires the local storage backend")
    monkeypatch.setattr(storage_spaces, "_LOCAL_ROOT_OVERRIDE", str(tmp_path))
    monkeypatch.setattr(dossier, "get_server_config", lambda gid: CONFIG)
    monkeypatch.setattr(archive_index.acl, "get_server_config", lambda gid: CONFIG)
    monkeypatch.setattr(
        archive_index.server_config,
        "get_roles_for_level",
        lambda level, gid=None: [555] if level == 3 else [],
    )
    monkeypatch.setattr(
        archive_index.server_config,
        "get_clearance_levels",
        lambda gid=None: {3: {"name": "Secret", "roles": [555]}},
    )
    archive_index.invalidate()
    base = tmp_path / "arch-root"
    for rel, body in FILES.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body) if isinstance(body, dict) else body, encoding="utf-8")
    yield base
    archive_index.invalidate()


def _signature(entry):
    return (entry["key"], entry["category"], entry["name"], entry["ext"], bool(entry["archived"]))


def test_index_matches_dossier_enumeration(archive_root):
    expected = {_signature(entry) for entry in dossier.enumerate_dossier_files(GUILD_ID)}

    index = archive_index.build_index(GUILD_ID)

    assert {_signature(entry) for entry in index.entries} == expected
    assert ("arch-root/Tech & Equipment/rifle.txt", "tech_equipment", "rifle", ".txt", False) in expected
    assert ("arch-root/_archived/missions/old-op.txt", "missions", "old-op", ".txt", True) in expected
    assert all(not entry["key"].startswith("arch-root/acl/") for entry in index.entries)
    assert index.category_labels["tech_equipment"] == "Tech & Equipment"
    alpha = index.find("arch-root/fleet/alpha.json")
    assert alpha["size"] > 0 and alpha["updated_at"]


def test_index_prefers_json_over_txt_for_same_item(archive_root):
    (archive_root / "fleet" / "alpha.txt").write_text("duplicate", encoding="utf-8")

    index = archive_index.build_index(GUILD_ID)

    alphas = [entry for entry in index.entries if entry["category"] == "fleet" and entry["name"] == "alpha"]
    assert [entry["ext"] for entry in alphas] == [".json"]


def test_index_is_cached_until_forced_or_invalidated(archive_root, monkeypatch):
    calls = []
    real_list_tree = storage_spaces.list_tree

    def counting_list_tree(prefix, limit=20000):
        calls.append(prefix)
        return real_list_tree(prefix, limit)

    monkeypatch.setattr(storage_spaces, "list_tree", counting_list_tree)

    first = archive_index.get_index(GUILD_ID)
    assert archive_index.get_index(GUILD_ID) is first
    assert len(calls) == 1

    archive_index.get_index(GUILD_ID, force=True)
    assert len(calls) == 2

    archive_index.invalidate(GUILD_ID)
    archive_index.get_index(GUILD_ID)
    assert len(calls) == 3


def test_find_entry_rebuilds_once_for_new_files(archive_root, monkeypatch):
    archive_index.get_index(GUILD_ID)
    (archive_root / "fleet" / "delta.txt").write_text("d", encoding="utf-8")
    monkeypatch.setattr(archive_index, "MISS_REBUILD_MIN_AGE_SECONDS", 0)

    assert archive_index.find_entry(GUILD_ID, "arch-root/fleet/delta.txt")["name"] == "delta"
    assert archive_index.find_entry(GUILD_ID, "arch-root/../secrets.txt") is None


def test_access_resolver_matches_acl_lookup(archive_root):
    resolver = archive_index.build_access_resolver(GUILD_ID)

    assert resolver.required_roles("fleet", "alpha") == {555}
    assert resolver.required_roles("fleet", "sub/bravo") == set()
    assert resolver.required_roles("fleet", "alpha") == archive_index.acl.get_required_roles(
        "fleet", "alpha", guild_id=GUILD_ID
    )
    assert resolver.level_for({555}) == 3
    assert resolver.level_label(3) == "Secret"
    assert resolver.level_label(None) == ""


# --- HTTP endpoints -------------------------------------------------------


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _session_cookie(mod, data):
    signer = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


class FakeDiscord:
    """What the bot would read from Discord for the signed-in member."""

    def __init__(self):
        self.member = True
        self.roles: set[int] = set()
        self.owner_id = "1"
        self.role_permissions: dict[int, int] = {}
        self.error: Exception | None = None
        self.locked = False
        self.member_lookups = 0

    async def fetch_member(self, api, token, guild_id, user_id, *, force=False):
        self.member_lookups += 1
        if self.error:
            raise self.error
        if not self.member:
            return None
        return {"user": {"id": user_id}, "roles": [str(role) for role in self.roles]}

    async def fetch_guild(self, api, token, guild_id, *, force=False):
        if self.error:
            raise self.error
        roles = [{"id": str(guild_id), "permissions": "0"}]
        roles += [{"id": str(rid), "permissions": str(perms)} for rid, perms in self.role_permissions.items()]
        return {"id": str(guild_id), "owner_id": self.owner_id, "roles": roles}


@pytest.fixture
def archive_client(archive_root, monkeypatch):
    import archive_access
    import archive_lock

    mod = _load_app(monkeypatch)
    discord = FakeDiscord()
    monkeypatch.setattr(archive_access, "fetch_member", discord.fetch_member)
    monkeypatch.setattr(archive_access, "fetch_guild", discord.fetch_guild)
    monkeypatch.setattr(archive_access.server_config, "get_server_config", lambda gid: {**CONFIG, "HIGH_COMMAND_ROLE_ID": "900"})
    monkeypatch.setattr(archive_lock, "is_locked", lambda gid: discord.locked)
    monkeypatch.setattr(mod, "_live_bot_token", lambda: "bot-token")
    monkeypatch.setattr(mod, "get_server_config", lambda gid: CONFIG)
    monkeypatch.setattr(mod, "get_instance_summary", lambda: {})
    monkeypatch.setattr(mod, "check_temp_clearance", lambda *args, **kwargs: False)

    client = TestClient(mod.app)
    # permissions "0": an ordinary member, not someone who manages the server.
    session = {
        "discord_token": {"access_token": "token"},
        "user": {"id": "42", "username": "operator", "global_name": "Operator Kilo"},
        "guilds": [],
    }
    client.cookies.set(mod.SESSION_COOKIE_NAME, _session_cookie(mod, session))
    client.app_module = mod
    return client, discord


def test_archive_index_endpoint_returns_everything_in_one_call(archive_client):
    client, _roles = archive_client

    resp = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})

    assert resp.status_code == 200
    data = resp.json()
    by_name = {item["name"]: item for item in data["items"]}
    # A plain member does not see archived files (High Command only, as in Discord).
    assert set(by_name) == {"alpha", "sub/bravo", "rifle", "charlie"}
    assert by_name["alpha"]["allowed"] is False
    assert by_name["alpha"]["clearance_level"] == 3
    assert by_name["alpha"]["clearance_label"] == "Secret"
    assert by_name["rifle"]["category_label"] == "Tech & Equipment"
    assert data["stats"]["total_files"] == 4
    assert data["stats"]["restricted_files"] == 1
    assert data["stats"]["archived_files"] == 0
    assert data["profile"]["display_name"] == "Operator Kilo"
    assert data["profile"]["guild_role"] == "Member"
    assert data["sources"][0]["root_prefix"] == "arch-root"
    assert data["sources"][0]["file_count"] == 4
    assert data["clearance_levels"] == [{"level": 3, "label": "Secret"}]
    fleet = next(cat for cat in data["categories"] if cat["name"] == "fleet")
    assert fleet["total"] == 2 and fleet["allowed"] == 1


def test_archive_index_requires_login(archive_root, monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    resp = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})

    assert resp.status_code == 401


def test_archive_dossier_enforces_clearance(archive_client):
    client, discord = archive_client

    open_resp = client.get(
        "/api/spectre/archive/dossier",
        params={"guild_id": GUILD_ID, "key": "arch-root/fleet/sub/bravo.txt"},
    )
    assert open_resp.status_code == 200
    assert open_resp.json()["content"] == "bravo body"

    denied = client.get(
        "/api/spectre/archive/dossier",
        params={"guild_id": GUILD_ID, "key": "arch-root/fleet/alpha.json"},
    )
    assert denied.status_code == 403

    discord.roles.add(555)
    granted = client.get(
        "/api/spectre/archive/dossier",
        params={"guild_id": GUILD_ID, "key": "arch-root/fleet/alpha.json"},
    )
    assert granted.status_code == 200
    assert granted.json()["data"]["subject"] == "Alpha"


def test_archive_dossier_rejects_keys_outside_the_index(archive_client):
    client, _roles = archive_client

    resp = client.get(
        "/api/spectre/archive/dossier",
        params={"guild_id": GUILD_ID, "key": "arch-root/acl/clearance.json"},
    )

    assert resp.status_code == 404


def test_archive_browse_still_filters_and_paginates(archive_client):
    client, _roles = archive_client

    resp = client.get(
        "/api/spectre/archive/browse",
        params={"guild_id": GUILD_ID, "category": "fleet", "page_size": 1},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert [item["name"] for item in data["items"]] == ["sub/bravo"]
    assert data["pagination"]["total"] == 1


def test_archive_index_is_gzipped_when_accepted(archive_client):
    client, _roles = archive_client

    resp = client.get(
        "/api/spectre/archive/index",
        params={"guild_id": GUILD_ID},
        headers={"Accept-Encoding": "gzip"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in resp.headers["vary"]
    assert resp.json()["stats"]["total_files"] == 4


# --- Discord standing ------------------------------------------------------


def _open(client, key="arch-root/fleet/alpha.json"):
    return client.get("/api/spectre/archive/dossier", params={"guild_id": GUILD_ID, "key": key})


def test_ordinary_member_gets_clearance_from_discord_roles(archive_client):
    client, discord = archive_client
    discord.roles.add(555)

    data = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID}).json()

    alpha = next(item for item in data["items"] if item["name"] == "alpha")
    assert alpha["allowed"] is True
    assert data["profile"]["guild_role"] == "Member"
    assert data["profile"]["clearance_level"] == 3
    assert data["profile"]["clearance_label"] == "Secret"
    assert data["profile"]["roles_verified"] is True


def test_non_member_is_refused(archive_client):
    client, discord = archive_client
    discord.member = False

    index = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})
    dossier = _open(client, "arch-root/fleet/sub/bravo.txt")

    assert index.status_code == 403
    assert "not a member" in index.json()["detail"]
    assert dossier.status_code == 403


def test_discord_outage_fails_closed(archive_client):
    import archive_access

    client, discord = archive_client
    discord.error = archive_access.DiscordLookupError("timeout")

    resp = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})

    assert resp.status_code == 502


def test_administrator_role_permission_opens_restricted_files(archive_client):
    client, discord = archive_client
    discord.roles.add(777)
    discord.role_permissions[777] = 0x8

    resp = _open(client)
    profile = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID}).json()["profile"]

    assert resp.status_code == 200
    assert profile["guild_role"] == "Administrator"


def test_guild_owner_opens_restricted_files(archive_client):
    client, discord = archive_client
    discord.owner_id = "42"

    assert _open(client).status_code == 200


def test_role_from_other_level_does_not_open_file(archive_client):
    client, discord = archive_client
    discord.roles.add(556)

    assert _open(client).status_code == 403


def test_one_time_clearance_opens_restricted_file(archive_client, monkeypatch):
    client, _discord = archive_client
    mod = client.app_module
    grants = {"alpha"}

    def one_time(user_id, category, item, guild_id=None):
        if item in grants:
            grants.discard(item)
            return True
        return False

    monkeypatch.setattr(mod, "check_temp_clearance", one_time)

    assert _open(client).status_code == 200
    assert _open(client).status_code == 403


def test_lockdown_admits_only_high_command(archive_client):
    client, discord = archive_client
    discord.locked = True

    locked_index = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})
    assert locked_index.status_code == 423
    assert _open(client, "arch-root/fleet/sub/bravo.txt").status_code == 423

    discord.roles.add(900)
    open_index = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})
    assert open_index.status_code == 200
    assert open_index.json()["locked"] is True
    assert open_index.json()["profile"]["guild_role"] == "High Command"


def test_resync_refetches_discord_roles(archive_client, monkeypatch):
    import archive_access

    client, discord = archive_client
    seen = []
    real = discord.fetch_member

    async def tracking(api, token, guild_id, user_id, *, force=False):
        seen.append(force)
        return await real(api, token, guild_id, user_id, force=force)

    monkeypatch.setattr(archive_access, "fetch_member", tracking)
    client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID, "refresh": "true"})

    assert seen == [True]


def test_without_bot_token_only_open_files_are_readable(archive_client, monkeypatch):
    client, _discord = archive_client
    mod = client.app_module
    monkeypatch.setattr(mod, "_live_bot_token", lambda: "")

    async def user_guilds(_token):
        return [{"id": str(GUILD_ID), "name": "Section Zero", "owner": False, "permissions": "0"}]

    monkeypatch.setattr(mod, "get_user_guilds", user_guilds)

    data = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID}).json()

    assert data["profile"]["roles_verified"] is False
    assert _open(client).status_code == 403
    assert _open(client, "arch-root/fleet/sub/bravo.txt").status_code == 200


def test_archive_server_picker_lists_member_guilds_with_the_bot(archive_client, monkeypatch):
    import asyncio

    client, _discord = archive_client
    mod = client.app_module

    async def user_guilds(_token):
        return [
            {"id": "77", "name": "Section Zero", "owner": False, "permissions": "0"},
            {"id": "88", "name": "No Bot Here", "owner": True, "permissions": "8"},
        ]

    async def bot_guild_ids():
        return {"77"}

    monkeypatch.setattr(mod, "get_user_guilds", user_guilds)
    monkeypatch.setattr(mod, "_cached_bot_guild_ids", bot_guild_ids)

    class _Request:
        session = {"discord_token": {"access_token": "token"}}

    options = asyncio.run(mod._archive_guild_options(_Request()))

    assert options == [{"id": "77", "name": "Section Zero"}]


def test_archived_files_are_for_high_command_only(archive_client):
    client, discord = archive_client
    archived_key = "arch-root/_archived/missions/old-op.txt"

    member_view = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID}).json()
    assert all(not item["archived"] for item in member_view["items"])
    assert _open(client, archived_key).status_code == 404

    discord.roles.add(900)
    command_view = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID}).json()
    assert command_view["stats"]["archived_files"] == 1
    assert command_view["stats"]["total_files"] == 5
    assert _open(client, archived_key).status_code == 200
