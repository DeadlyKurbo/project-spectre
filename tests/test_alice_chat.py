import base64
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone

import itsdangerous
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _release_storage_root():
    """Point storage back at its default root once a test's temp dir is gone.

    The app pins ``storage_spaces`` to each test's ``tmp_path``; modules that
    later re-import it (``dossier``, ``utils``) would otherwise inherit a
    deleted directory.
    """

    yield
    storage_spaces = sys.modules.get("storage_spaces")
    setter = getattr(storage_spaces, "set_local_root", None)
    if callable(setter):
        setter(None)


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


def test_alice_chat_authors_can_delete_only_their_own(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    author_id = "123456789012345678"
    other_id = "223456789012345678"
    _grant_chat_access(mod, author_id)
    _grant_chat_access(mod, other_id)
    author = _authed_client(mod, author_id)
    other = _authed_client(mod, other_id)

    message_id = author.post("/api/alice/chat", json={"message": "One"}).json()["message"]["id"]

    assert other.delete(f"/api/alice/chat/{message_id}").status_code == 403
    response = author.delete(f"/api/alice/chat/{message_id}")
    assert response.status_code == 200
    assert response.json() == {"messages": []}


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


def _member_handle(client, label=None, *, self_=False):
    members = client.get("/api/zeta/sync?members=1").json()["members"]
    for member in members:
        if member["self"] == self_ and (label is None or member["label"] == label):
            return member["handle"]
    raise AssertionError(f"no member {label!r} in {members}")


def test_direct_messages_persist_and_stay_private(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    alpha_id, bravo_id, charlie_id = "111111111111111111", "222222222222222222", "333333333333333333"
    for user_id in (alpha_id, bravo_id, charlie_id):
        _grant_chat_access(mod, user_id)
    ops = importlib.import_module("operator_login")
    ops.update_profile(int(alpha_id), name="Alpha")
    ops.update_profile(int(bravo_id), name="Bravo")
    ops.update_profile(int(charlie_id), name="Charlie")

    alpha = _authed_client(mod, alpha_id)
    bravo = _authed_client(mod, bravo_id)
    charlie = _authed_client(mod, charlie_id)
    bravo_handle = _member_handle(alpha, "Operator B")
    alpha_handle = _member_handle(bravo, "Operator A")

    sent = alpha.post(f"/api/zeta/dm/{bravo_handle}", json={"message": "Eyes only"})
    assert sent.status_code == 200
    assert [m["message"] for m in sent.json()["dm"]["messages"]] == ["Eyes only"]
    assert sent.json()["dm"]["messages"][0]["mine"] is True

    inbox = bravo.get("/api/zeta/sync").json()
    assert inbox["unread_total"] == 1
    assert inbox["threads"][0]["label"] == "Operator A"
    assert inbox["threads"][0]["preview"] == "Eyes only"

    opened = bravo.get(f"/api/zeta/sync?dm={alpha_handle}").json()
    assert [(m["message"], m["mine"], m["operator"]) for m in opened["dm"]["messages"]] == [
        ("Eyes only", False, "Operator A")
    ]
    assert bravo.get("/api/zeta/sync").json()["unread_total"] == 0

    # A third member asking for the same handle only sees their own thread with Alpha.
    peek = charlie.get(f"/api/zeta/sync?dm={alpha_handle}").json()
    assert peek["dm"]["messages"] == []

    # Messages stay: the channel purge does not touch them.
    mod._enforce_chat_retention()
    again = alpha.get(f"/api/zeta/sync?dm={bravo_handle}").json()
    assert [m["message"] for m in again["dm"]["messages"]] == ["Eyes only"]


def test_direct_message_payloads_never_carry_discord_ids(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    alpha_id, bravo_id = "111111111111111111", "222222222222222222"
    _grant_chat_access(mod, alpha_id)
    _grant_chat_access(mod, bravo_id)
    alpha = _authed_client(mod, alpha_id)
    bravo = _authed_client(mod, bravo_id)

    alpha.post("/api/alice/chat", json={"message": "Channel"})
    bravo_handle = _member_handle(alpha, self_=False)
    alpha.post(f"/api/zeta/dm/{bravo_handle}", json={"message": "Direct"})

    for client, peer in ((alpha, bravo_handle), (bravo, _member_handle(bravo, self_=False))):
        body = client.get(f"/api/zeta/sync?members=1&dm={peer}").text
        assert alpha_id not in body and bravo_id not in body


def test_channel_and_direct_messages_share_callsigns(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    alpha_id, bravo_id = "111111111111111111", "222222222222222222"
    _grant_chat_access(mod, alpha_id)
    _grant_chat_access(mod, bravo_id)
    alpha = _authed_client(mod, alpha_id)
    bravo = _authed_client(mod, bravo_id)

    alpha.post("/api/alice/chat", json={"message": "Hello"})
    sync = bravo.get("/api/zeta/sync?members=1").json()
    entry = sync["channel"][0]
    member = next(m for m in sync["members"] if m["handle"] == entry["handle"])
    assert entry["operator"] == member["label"]


def test_direct_message_rejects_unknown_handle_and_self(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    assert client.post("/api/zeta/dm/nope", json={"message": "Ping"}).status_code == 404
    own = _member_handle(client, self_=True)
    assert client.post(f"/api/zeta/dm/{own}", json={"message": "Ping"}).status_code == 400


def test_zeta_sync_requires_access(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    assert _authed_client(mod, "999999999999999999").get("/api/zeta/sync").status_code == 403


def test_members_use_unique_operator_aliases(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)

    ops = importlib.import_module("operator_login")
    ops.update_profile(111111111111111111, name="Delta")
    ops.update_profile(222222222222222222, name="Dune")
    ops.update_profile(333333333333333333, name="Drake")

    settings, etag = mod.load_owner_settings(with_etag=True)
    updated = settings.copy()
    updated.managers = ["111111111111111111", "222222222222222222", "333333333333333333"]
    mod.save_owner_settings(updated, etag=etag)

    members = mod._zeta_members(updated)
    mapping = {entry["id"]: entry for entry in members}
    initials = {entry.get("initial") for entry in members}

    assert mapping[mod.OWNER_USER_ID]["label"] == "Operator O"
    assert mapping["111111111111111111"]["label"] == "Operator D"
    assert mapping["222222222222222222"]["label"] == "Operator U"
    assert mapping["333333333333333333"]["label"] == "Operator R"
    assert mapping["111111111111111111"]["group"] == "command"
    assert len(initials) == len(members)


def test_legacy_dispatches_move_into_direct_messages(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    sender_id, recipient_id = "111111111111111111", "222222222222222222"
    _grant_chat_access(mod, sender_id)
    _grant_chat_access(mod, recipient_id)
    mod.write_json(
        mod._ALICE_PRIVATE_MESSAGE_KEY,
        {"messages": [{"id": "x", "recipient_id": recipient_id, "sender_id": sender_id,
                       "sender": "Alpha", "message": "Queued", "created_at": "2026-10-24T10:00:00+00:00"}]},
    )

    recipient = _browser_client(mod, recipient_id)
    assert recipient.get("/zeta").status_code == 200
    sync = recipient.get("/api/zeta/sync").json()
    assert sync["unread_total"] == 1
    assert sync["threads"][0]["preview"] == "Queued"
    assert mod._load_private_messages()[0]["messages"] == []


def test_chat_marks_own_messages_without_exposing_author_ids(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    author_id = "123456789012345678"
    reader_id = "223456789012345678"
    _grant_chat_access(mod, author_id)
    _grant_chat_access(mod, reader_id)

    author = _authed_client(mod, author_id)
    post = author.post("/api/alice/chat", json={"message": "Mine"})
    assert post.status_code == 200
    assert post.json()["message"]["mine"] is True
    assert "user_id" not in post.json()["message"]

    reader = _authed_client(mod, reader_id)
    messages = reader.get("/api/alice/chat").json()["messages"]
    assert messages[0]["mine"] is False
    assert "user_id" not in messages[0]


def _browser_client(mod, user_id: str):
    client = TestClient(mod.app, base_url="https://testserver")
    cookie = _session_cookie(
        mod,
        {"user": {"username": "Delta", "id": user_id}, "discord_token": {"access_token": "x"}},
    )
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    return client


def test_legacy_chat_url_redirects_to_zeta(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    client = _browser_client(mod, "123456789012345678")

    response = client.get("/alice/chat?recipient=42", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/zeta?recipient=42"


def test_zeta_page_gates_and_opens_channel(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    client = _browser_client(mod, user_id)

    locked = client.get("/zeta")
    assert locked.status_code == 200
    assert "Clearance required" in locked.text
    assert 'action="/zeta/request"' in locked.text
    assert 'id="chatFeed"' not in locked.text

    _grant_chat_access(mod, user_id)
    opened = client.get("/zeta")
    assert opened.status_code == 200
    assert 'id="chatFeed"' in opened.text
    assert "Clearance required" not in opened.text


def test_zeta_access_request_redirects_back_to_zeta(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    client = _browser_client(mod, "123456789012345678")

    response = client.post("/zeta/request", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/zeta"
    assert "Request pending review" in client.get("/zeta").text


def test_channel_marks_own_messages_after_reload(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    client.post("/api/alice/chat", json={"message": "Mine"})
    client.post("/api/alice/chat", json={"message": "Also mine"})
    messages = client.get("/api/alice/chat").json()["messages"]
    assert [m["mine"] for m in messages] == [True, True]
