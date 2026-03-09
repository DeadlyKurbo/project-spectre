import importlib
import sys

from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def test_wasp_map_state_get_sets_etag(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

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

    monkeypatch.setattr(
        mod,
        "load_wasp_map_state",
        lambda with_etag=False: ({"units": []}, "same") if with_etag else {"units": []},
    )

    response = client.get("/api/wasp-map/state", headers={"If-None-Match": '"same"'})

    assert response.status_code == 304


def test_wasp_map_state_put_returns_conflict_payload(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

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
