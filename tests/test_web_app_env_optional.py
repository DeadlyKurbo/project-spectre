import importlib
import sys

from fastapi.testclient import TestClient


def test_web_app_missing_oauth_config(monkeypatch):
    for var in ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI", "DATABASE_URL"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SESSION_SECRET", "testing")
    sys.modules.pop("web_app", None)
    web_app = importlib.import_module("web_app")

    assert web_app.CLIENT_ID is None
    assert web_app.CLIENT_SECRET is None
    assert web_app.REDIRECT_URI is None

    client = TestClient(web_app.app)
    resp = client.get("/login")
    assert resp.status_code == 501
