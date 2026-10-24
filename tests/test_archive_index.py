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


@pytest.fixture
def archive_client(archive_root, monkeypatch):
    mod = _load_app(monkeypatch)
    member_roles: set[int] = set()

    async def fake_member_roles(_guild_id, _user_id):
        return set(member_roles)

    monkeypatch.setattr(mod, "_fetch_member_role_ids", fake_member_roles)
    monkeypatch.setattr(mod, "get_server_config", lambda gid: CONFIG)
    monkeypatch.setattr(mod, "get_instance_summary", lambda: {})
    monkeypatch.setattr(mod, "check_temp_clearance", lambda *args, **kwargs: False)

    client = TestClient(mod.app)
    session = {
        "discord_token": {"access_token": "token"},
        "user": {"id": "42", "username": "operator", "global_name": "Operator Kilo"},
        "guilds": [{"id": str(GUILD_ID), "name": "Section Zero", "owner": False, "permissions": "0"}],
    }
    client.cookies.set(mod.SESSION_COOKIE_NAME, _session_cookie(mod, session))
    return client, member_roles


def test_archive_index_endpoint_returns_everything_in_one_call(archive_client):
    client, _roles = archive_client

    resp = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})

    assert resp.status_code == 200
    data = resp.json()
    by_name = {item["name"]: item for item in data["items"]}
    assert set(by_name) == {"alpha", "sub/bravo", "rifle", "charlie", "old-op"}
    assert by_name["alpha"]["allowed"] is False
    assert by_name["alpha"]["clearance_level"] == 3
    assert by_name["alpha"]["clearance_label"] == "Secret"
    assert by_name["rifle"]["category_label"] == "Tech & Equipment"
    assert by_name["old-op"]["archived"] is True
    assert data["stats"]["total_files"] == 5
    assert data["stats"]["restricted_files"] == 1
    assert data["stats"]["archived_files"] == 1
    assert data["profile"]["display_name"] == "Operator Kilo"
    assert data["profile"]["guild_role"] == "Member"
    assert data["sources"][0]["root_prefix"] == "arch-root"
    assert data["sources"][0]["file_count"] == 5
    assert data["clearance_levels"] == [{"level": 3, "label": "Secret"}]
    fleet = next(cat for cat in data["categories"] if cat["name"] == "fleet")
    assert fleet["total"] == 2 and fleet["allowed"] == 1


def test_archive_index_requires_login(archive_root, monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    resp = client.get("/api/spectre/archive/index", params={"guild_id": GUILD_ID})

    assert resp.status_code == 401


def test_archive_dossier_enforces_clearance(archive_client):
    client, member_roles = archive_client

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

    member_roles.add(555)
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
    assert resp.json()["stats"]["total_files"] == 5
