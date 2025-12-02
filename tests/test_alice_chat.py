import base64
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone

import itsdangerous
import pytest
from fastapi.testclient import TestClient


def _load_app(monkeypatch, tmp_path):
    monkeypatch.setenv("SPACES_ROOT", str(tmp_path))
    monkeypatch.setenv("SPECTRE_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("storage_spaces", None)
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _session_cookie(mod, data):
    signer = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _grant_chat_access(mod, user_id: str) -> None:
    settings, etag = mod.load_owner_settings(with_etag=True)
    updated = settings.copy()
    if user_id not in updated.chat_access:
        updated.chat_access.append(user_id)
    mod.save_owner_settings(updated, etag=etag)


def _authed_client(mod, user_id: str = "123456789012345678"):
    client = TestClient(mod.app, base_url="https://testserver")
    cookie = _session_cookie(mod, {"user": {"username": "Delta", "id": user_id}})
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    return client


def test_alice_chat_round_trip(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    response = client.get("/api/alice/chat")
    assert response.status_code == 200
    assert response.json() == {"messages": []}

    post = client.post("/api/alice/chat", json={"message": "Hey guys"})
    assert post.status_code == 200
    payload = post.json()
    assert payload["message"]["operator"] == "Operator D"
    assert payload["message"]["operator_handle"] == "Operator D"
    assert payload["message"]["initial"] == "D"
    assert payload["message"]["message"] == "Hey guys"

    history = client.get("/api/alice/chat")
    assert history.status_code == 200
    messages = history.json().get("messages", [])
    assert len(messages) == 1
    assert messages[0]["message"] == "Hey guys"
    assert messages[0]["operator"] == "Operator D"
    assert messages[0]["operator_handle"] == "Operator D"
    assert messages[0]["initial"] == "D"


def test_alice_chat_rejects_empty(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    response = client.post("/api/alice/chat", json={"message": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "Message cannot be empty"


def test_alice_chat_purges_after_24_hours(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    expired = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    mod.write_json(
        mod._ALICE_CHAT_LOG_KEY,
        {"messages": [{"id": "old", "message": "stale", "operator": "Ghost", "created_at": expired}]},
    )

    response = client.get("/api/alice/chat")
    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_alice_chat_delete_requires_moderator(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    post = client.post("/api/alice/chat", json={"message": "One"})
    message_id = post.json()["message"]["id"]

    response = client.delete(f"/api/alice/chat/{message_id}")
    assert response.status_code == 403


def test_alice_chat_delete_as_moderator(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    post = client.post("/api/alice/chat", json={"message": "Keep"})
    message_id = post.json()["message"]["id"]

    response = client.delete(f"/api/alice/chat/{message_id}")
    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_alice_chat_shows_full_names_to_moderators(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    post = client.post("/api/alice/chat", json={"message": "Hey team"})
    assert post.status_code == 200
    payload = post.json()

    assert payload["message"]["operator"] == "Delta"
    assert payload["message"]["operator_handle"] == "Delta (123456789012345678)"
    assert payload["message"]["initial"] == "D"

    history = client.get("/api/alice/chat")
    assert history.status_code == 200
    messages = history.json().get("messages", [])
    assert messages[0]["operator"] == "Delta"
    assert messages[0]["operator_handle"] == "Delta (123456789012345678)"


def test_alice_chat_rejects_without_access(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    client = _authed_client(mod, "999999999999999999")

    response = client.get("/api/alice/chat")
    assert response.status_code == 403


def test_private_message_delivery(monkeypatch, tmp_path):
    recipient_id = "555555555555555555"
    sender_id = "123456789012345678"
    monkeypatch.setenv("ALICE_PRIVATE_MESSAGE_RECIPIENT_ID", recipient_id)
    mod = _load_app(monkeypatch, tmp_path)
    _grant_chat_access(mod, sender_id)
    _grant_chat_access(mod, recipient_id)

    client = _authed_client(mod, sender_id)
    post = client.post(
        "/api/alice/chat/private",
        json={"message": "Secure note", "recipient_id": recipient_id},
    )
    assert post.status_code == 200
    payload = post.json().get("message", {})
    assert payload.get("recipient_id") == recipient_id
    assert payload.get("sender_id") == sender_id

    stranger = _authed_client(mod, "999999999999999999")
    denied = stranger.get("/api/alice/chat/private")
    assert denied.status_code == 403

    recipient = _authed_client(mod, recipient_id)
    inbox = recipient.get("/api/alice/chat/private")
    assert inbox.status_code == 200
    messages = inbox.json().get("messages", [])
    assert len(messages) == 1
    assert messages[0]["message"] == "Secure note"
    assert messages[0]["sender_id"] == sender_id

    follow_up = recipient.get("/api/alice/chat/private")
    assert follow_up.status_code == 200
    assert follow_up.json().get("messages") == []


def test_private_message_rejects_unknown_recipient(monkeypatch, tmp_path):
    sender_id = "123456789012345678"
    mod = _load_app(monkeypatch, tmp_path)
    _grant_chat_access(mod, sender_id)

    client = _authed_client(mod, sender_id)
    response = client.post(
        "/api/alice/chat/private",
        json={"message": "Ping", "recipient_id": "999"},
    )

    assert response.status_code == 400
    assert (
        response.json().get("detail")
        == "Select a valid operator for private dispatch."
    )
