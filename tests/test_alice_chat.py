import base64
import importlib
import json
import sys

import itsdangerous
import pytest
from fastapi.testclient import TestClient


def _load_app(monkeypatch, tmp_path):
    monkeypatch.setenv("SPACES_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _session_cookie(mod, data):
    signer = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _authed_client(mod):
    client = TestClient(mod.app, base_url="https://testserver")
    cookie = _session_cookie(mod, {"user": {"username": "Delta"}})
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    return client


def test_alice_chat_round_trip(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    client = _authed_client(mod)

    response = client.get("/api/alice/chat")
    assert response.status_code == 200
    assert response.json() == {"messages": []}

    post = client.post("/api/alice/chat", json={"message": "Hey guys"})
    assert post.status_code == 200
    payload = post.json()
    assert payload["message"]["operator"] == "Operator D"
    assert payload["message"]["message"] == "Hey guys"

    history = client.get("/api/alice/chat")
    assert history.status_code == 200
    messages = history.json().get("messages", [])
    assert len(messages) == 1
    assert messages[0]["message"] == "Hey guys"


def test_alice_chat_rejects_empty(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    client = _authed_client(mod)

    response = client.post("/api/alice/chat", json={"message": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "Message cannot be empty"
