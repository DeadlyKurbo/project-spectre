import importlib
import sys
import base64
import json

import itsdangerous
from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _session_cookie(mod, data):
    signer = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _seed_admin_session(client, mod, monkeypatch):
    cookie = _session_cookie(mod, {"user": {"username": "Admin", "id": "84"}})
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)


def test_wasp_map_state_get_sets_etag(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _seed_admin_session(client, mod, monkeypatch)

    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": [{"id": "u1"}]}, "etag-a") if with_etag else {"units": [{"id": "u1"}]},
    )

    response = client.get("/api/wasp-map/state")

    assert response.status_code == 200
    assert response.headers["etag"] == '"etag-a"'
    assert response.json() == {"units": [{"id": "u1"}]}


def test_wasp_map_state_get_returns_not_modified(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _seed_admin_session(client, mod, monkeypatch)

    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": []}, "same") if with_etag else {"units": []},
    )

    response = client.get("/api/wasp-map/state", headers={"If-None-Match": '"same"'})

    assert response.status_code == 304


def test_wasp_map_state_get_requires_authenticated_admin(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)

    response = client.get("/api/wasp-map/state")

    assert response.status_code == 401


def test_wasp_map_state_put_returns_conflict_payload(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _seed_admin_session(client, mod, monkeypatch)

    monkeypatch.setattr(mod, "save_wasp_map_state", lambda payload, etag=None: False)
    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": [{"id": "latest"}]}, "etag-latest") if with_etag else {"units": [{"id": "latest"}]},
    )

    response = client.put("/api/wasp-map/state", json={"units": []}, headers={"If-Match": '"stale"'})

    assert response.status_code == 409
    assert response.headers["etag"] == '"etag-latest"'
    assert response.json() == {"error": "State conflict", "state": {"units": [{"id": "latest"}]}}


def test_wasp_map_state_put_saves_and_returns_new_state(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _seed_admin_session(client, mod, monkeypatch)

    capture = {}

    def fake_save(payload, etag=None):
        capture["payload"] = payload
        capture["etag"] = etag
        return True

    monkeypatch.setattr(mod, "save_wasp_map_state", fake_save)
    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": [{"id": "u2"}]}, "etag-b") if with_etag else {"units": [{"id": "u2"}]},
    )

    response = client.put(
        "/api/wasp-map/state",
        json={"units": [{"id": "u2"}]},
        headers={"If-Match": '"etag-a"'},
    )

    assert response.status_code == 200
    assert capture == {"payload": {"units": [{"id": "u2"}]}, "etag": "etag-a"}
    assert response.headers["etag"] == '"etag-b"'
    assert response.json() == {"units": [{"id": "u2"}]}


def test_wasp_map_state_put_requires_owner_or_admin(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)

    response = client.put("/api/wasp-map/state", json={"units": []})

    assert response.status_code == 403


def test_wasp_map_state_put_allows_owner(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")
    cookie = _session_cookie(mod, {"user": {"username": "Owner", "id": "42"}})
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: True)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)
    monkeypatch.setattr(mod, "save_wasp_map_state", lambda payload, etag=None: True)
    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": [{"id": "u-owner"}]}, "etag-owner") if with_etag else {"units": [{"id": "u-owner"}]},
    )

    response = client.put("/api/wasp-map/state", json={"units": [{"id": "u-owner"}]})

    assert response.status_code == 200
    assert response.headers["etag"] == '"etag-owner"'


def test_wasp_map_state_put_allows_admin(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")
    cookie = _session_cookie(mod, {"user": {"username": "Admin", "id": "84"}})
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    monkeypatch.setattr(mod, "save_wasp_map_state", lambda payload, etag=None: True)
    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": [{"id": "u-admin"}]}, "etag-admin") if with_etag else {"units": [{"id": "u-admin"}]},
    )

    response = client.put("/api/wasp-map/state", json={"units": [{"id": "u-admin"}]})

    assert response.status_code == 200
    assert response.headers["etag"] == '"etag-admin"'


def test_wasp_map_simulation_start_requires_owner_or_admin(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)

    response = client.post("/api/wasp-map/simulation/start", json={"speed": 2})

    assert response.status_code == 403


def test_wasp_map_simulation_tick_updates_runner_tick(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: True)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)
    state = {
        "units": [{"id": "u1"}],
        "missions": [],
        "engagements": [],
        "events": [],
        "runner": {"status": "running", "tick": 3, "speed": 1, "startedBy": "Owner", "startedAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z", "seed": 1},
    }
    etag_holder = {"etag": "etag-1"}

    def fake_load(with_etag=False):
        if with_etag:
            return state, etag_holder["etag"]
        return state

    def fake_save(payload, etag=None):
        state.clear()
        state.update(payload)
        etag_holder["etag"] = "etag-2"
        return True

    monkeypatch.setattr(mod, "load_wasp_map_state", fake_load)
    monkeypatch.setattr(mod, "save_wasp_map_state", fake_save)

    response = client.post("/api/wasp-map/simulation/tick", json={"ticks": 4})

    assert response.status_code == 200
    assert response.json()["runner"]["tick"] == 7


def test_wasp_map_create_mission_appends_queued_mission(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    state = {
        "units": [{"id": "u1"}, {"id": "u2"}],
        "missions": [],
        "engagements": [],
        "events": [],
        "runner": {"status": "idle", "tick": 0, "speed": 1, "startedBy": "", "startedAt": None, "updatedAt": None, "seed": 1},
    }
    etag_holder = {"etag": "etag-a"}

    def fake_load(with_etag=False):
        if with_etag:
            return state, etag_holder["etag"]
        return state

    def fake_save(payload, etag=None):
        state.clear()
        state.update(payload)
        etag_holder["etag"] = "etag-b"
        return True

    monkeypatch.setattr(mod, "load_wasp_map_state", fake_load)
    monkeypatch.setattr(mod, "save_wasp_map_state", fake_save)

    response = client.post(
        "/api/wasp-map/missions",
        json={"attackerId": "u1", "targetId": "u2", "notes": "Alpha strike"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["missions"]) == 1
    assert payload["missions"][0]["status"] == "queued"
    assert payload["missions"][0]["attackerId"] == "u1"
    assert payload["missions"][0]["targetId"] == "u2"
