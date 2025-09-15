import importlib
import sys

from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def test_basic_auth_required(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    resp = client.get("/configs/123")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Basic"

    resp2 = client.get("/configs/123", auth=("user", "wrong"))
    assert resp2.status_code == 401
    assert resp2.headers.get("WWW-Authenticate") == "Basic"

    resp3 = client.get("/configs/123", auth=("user", "pass"))
    assert resp3.status_code == 200


def test_defaults_when_env_missing(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    client = TestClient(mod.app)

    resp = client.get("/configs/123", auth=("admin", "password"))
    assert resp.status_code == 200
