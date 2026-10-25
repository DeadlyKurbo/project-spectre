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
    assert response.status_code == 401


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
    assert _authed_client(mod, "999999999999999999").get("/api/zeta/sync").status_code == 401


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


def test_zeta_page_asks_for_a_name_and_opens_channel(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    client = TestClient(mod.app, base_url="https://testserver")

    locked = client.get("/zeta")
    assert locked.status_code == 200
    assert 'action="/zeta/join"' in locked.text
    assert 'id="chatFeed"' not in locked.text

    joined = client.post("/zeta/join", data={"name": "  Night   Owl "}, follow_redirects=False)
    assert joined.status_code == 303
    assert joined.headers["location"] == "/zeta"
    opened = client.get("/zeta")
    assert 'id="chatFeed"' in opened.text
    assert "Night Owl" in opened.text


def test_approved_discord_members_skip_the_name_form(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)

    opened = _browser_client(mod, user_id).get("/zeta")
    assert 'id="chatFeed"' in opened.text
    assert 'action="/zeta/join"' not in opened.text


def _guest_client(mod, name: str):
    client = TestClient(mod.app, base_url="https://testserver")
    client.post("/zeta/join", data={"name": name})
    return client


def test_guests_chat_under_their_chosen_name(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    member_id = "123456789012345678"
    _grant_chat_access(mod, member_id)
    guest = _guest_client(mod, "Night Owl")
    member = _authed_client(mod, member_id)

    post = guest.post("/api/alice/chat", json={"message": "Hello from a guest"})
    assert post.status_code == 200
    assert post.json()["message"]["mine"] is True
    assert post.json()["message"]["operator"] == "Night Owl"

    sync = member.get("/api/zeta/sync?members=1").json()
    assert sync["channel"][0]["operator"] == "Night Owl"
    assert sync["channel"][0]["mine"] is False
    listed = next(m for m in sync["members"] if m["label"] == "Night Owl")
    assert listed["group"] == "guest"

    sent = member.post(f"/api/zeta/dm/{listed['handle']}", json={"message": "Welcome"})
    assert sent.status_code == 200
    assert guest.get("/api/zeta/sync").json()["unread_total"] == 1


def _joined(client) -> bool:
    return client.get("/api/zeta/sync").status_code == 200


def test_guest_names_must_be_unique_and_not_reserved(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    assert _joined(_guest_client(mod, "Night Owl"))

    lookalikes = (
        "night owl",
        "NIGHT  OWL",
        "Night-Owl",
        "NightOwl",
        "Night\u200bOwl",  # zero-width space
        "\uff2eight Owl",  # full-width N
    )
    for name in lookalikes + ("Operator A", "operator-b", "   ", "!!!"):
        assert not _joined(_guest_client(mod, name)), name


def test_guest_names_cannot_copy_a_discord_members_name(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    member_id = "123456789012345678"
    _grant_chat_access(mod, member_id)
    importlib.import_module("operator_login").update_profile(int(member_id), name="Delta")

    assert not _joined(_guest_client(mod, "delta"))


def test_guest_can_rename_but_not_into_a_taken_name(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    guest = _guest_client(mod, "Night Owl")
    _guest_client(mod, "Lark")

    guest.post("/zeta/join", data={"name": "Lark"})
    assert _member_handle(guest, "Night Owl", self_=True)
    guest.post("/zeta/join", data={"name": "Kestrel"})
    assert _member_handle(guest, "Kestrel", self_=True)


def test_simultaneous_joins_cannot_share_a_name(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    _guest_client(mod, "Lark")  # create the registry so writes are ETag-checked
    real_backend = mod._storage_backend()
    rival = {"id": "zeta" + "b" * 32, "name": "Night Owl"}

    class RacingBackend:
        raced = False

        def __getattr__(self, name):
            return getattr(real_backend, name)

        def write_json(self, key, data, *, etag=None):
            if key == mod._ZETA_GUESTS_KEY and not self.raced:
                # Another server process claims the name between our read and our write.
                self.raced = True
                current = real_backend.read_json(key)
                current["guests"][rival["id"]] = {
                    "name": rival["name"],
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }
                real_backend.write_json(key, current)
            return real_backend.write_json(key, data, etag=etag)

    monkeypatch.setattr(mod, "_storage_backend", lambda: RacingBackend())
    problem = mod._zeta_claim_guest({"id": "zeta" + "a" * 32, "name": "night owl"}, force=True)
    assert problem == "Someone in Project ZETA already uses that name."
    names = [g["name"] for g in mod._zeta_guests().values()]
    assert sorted(names) == ["Lark", "Night Owl"]


def test_returning_guest_whose_name_was_taken_must_pick_another(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    returning = _guest_client(mod, "Night Owl")
    lark = _guest_client(mod, "Lark")
    lark_handle = _member_handle(returning, "Lark")
    returning.post(f"/api/zeta/dm/{lark_handle}", json={"message": "Before I left"})
    mod._ZETA_SEND_LIMITER.reset()

    # Their entry expires and a newcomer takes the name.
    expired = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    guests = mod._storage_backend().read_json(mod._ZETA_GUESTS_KEY)
    for entry in guests["guests"].values():
        if entry["name"] == "Night Owl":
            entry["last_seen"] = expired
    mod.write_json(mod._ZETA_GUESTS_KEY, guests)
    assert _joined(_guest_client(mod, "Night Owl"))

    # An open tab cannot post under the old name...
    blocked = returning.post("/api/alice/chat", json={"message": "I'm back"})
    assert blocked.status_code == 401
    assert mod._load_alice_chat()[0]["messages"] == []
    # ...and the page asks for a new one, keeping their DMs.
    page = returning.get("/zeta")
    assert 'action="/zeta/join"' in page.text
    returning.post("/zeta/join", data={"name": "Owl Two"})
    sync = returning.get(f"/api/zeta/sync?dm={lark_handle}").json()
    assert [m["message"] for m in sync["dm"]["messages"]] == ["Before I left"]
    names = sorted(g["name"] for g in mod._zeta_guests().values())
    assert names == ["Lark", "Night Owl", "Owl Two"]
    del lark


def test_zeta_allows_one_message_every_three_seconds(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    guest = _guest_client(mod, "Night Owl")
    _guest_client(mod, "Lark")
    lark = _member_handle(guest, "Lark")

    assert guest.post("/api/alice/chat", json={"message": "One"}).status_code == 200
    # The limit spans the channel and direct messages.
    blocked = guest.post(f"/api/zeta/dm/{lark}", json={"message": "Two"})
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "3"
    assert guest.post("/api/alice/chat", json={"message": "Three"}).status_code == 429

    mod._ZETA_SEND_LIMITER.reset()
    assert guest.post(f"/api/zeta/dm/{lark}", json={"message": "Four"}).status_code == 200


def test_channel_marks_own_messages_after_reload(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    user_id = "123456789012345678"
    _grant_chat_access(mod, user_id)
    client = _authed_client(mod, user_id)

    client.post("/api/alice/chat", json={"message": "Mine"})
    mod._ZETA_SEND_LIMITER.reset()
    client.post("/api/alice/chat", json={"message": "Also mine"})
    messages = client.get("/api/alice/chat").json()["messages"]
    assert [m["mine"] for m in messages] == [True, True]


MODERATOR_ID = "555555555555555555"


def _moderated_app(monkeypatch, tmp_path):
    """App where MODERATOR_ID is a moderator, with an in-memory audit log."""

    from app_spectre.services.moderation_service import InMemoryModerationRepository, ModerationService

    mod = _load_app(monkeypatch, tmp_path)
    _grant_chat_access(mod, MODERATOR_ID)
    monkeypatch.setattr(
        mod,
        "_session_user_is_admin",
        lambda request: (request.session.get("user") or {}).get("id") == MODERATOR_ID,
    )
    service = ModerationService(InMemoryModerationRepository())
    monkeypatch.setattr(mod, "get_moderation_service", lambda: service)
    return mod, service, _authed_client(mod, MODERATOR_ID)


def _audit(mod, service):
    import asyncio

    return asyncio.run(service.list_audit_events(limit=50))


def test_moderator_bans_a_guest_by_identity_and_ip(monkeypatch, tmp_path):
    mod, service, moderator = _moderated_app(monkeypatch, tmp_path)
    guest = _guest_client(mod, "Night Owl")
    guest.post("/api/alice/chat", json={"message": "Spam"})
    handle = _member_handle(moderator, "Night Owl")

    banned = moderator.post(
        "/api/zeta/bans", json={"handle": handle, "duration": "24h", "reason": "Spamming"}
    )
    assert banned.status_code == 200
    assert banned.json()["bans"][0]["label"] == "Night Owl"

    # The banned identity is locked out, with the reason.
    denied = guest.get("/api/zeta/sync")
    assert denied.status_code == 403
    assert "banned from Project ZETA until" in denied.json()["detail"]
    assert "Spamming" in denied.json()["detail"]
    assert guest.post("/api/alice/chat", json={"message": "Again"}).status_code == 403
    assert "Access suspended" in guest.get("/zeta").text

    # A fresh name from the same IP is refused too.
    newcomer = _guest_client(mod, "Lark")
    assert not _joined(newcomer)
    assert "Access suspended" in newcomer.get("/zeta").text

    # They leave the member list; moderators see the ban instead.
    sync = moderator.get("/api/zeta/sync?members=1").json()
    assert "Night Owl" not in [m["label"] for m in sync["members"]]
    assert [b["label"] for b in sync["bans"]] == ["Night Owl"]

    event = _audit(mod, service)[0]
    assert event["eventType"] == "zeta.banned"
    assert event["metadata"]["zetaMember"] == "Night Owl"
    assert event["metadata"]["duration"] == "24 hours"
    assert event["metadata"]["reason"] == "Spamming"
    assert event["metadata"]["ipCount"] == 1
    assert event["metadata"]["actor"]["id"] == MODERATOR_ID


def test_lifting_a_ban_restores_access_and_is_audited(monkeypatch, tmp_path):
    mod, service, moderator = _moderated_app(monkeypatch, tmp_path)
    guest = _guest_client(mod, "Night Owl")
    handle = _member_handle(moderator, "Night Owl")
    ban_id = moderator.post(
        "/api/zeta/bans", json={"handle": handle, "duration": "permanent"}
    ).json()["bans"][0]["id"]
    assert "permanently banned" in guest.get("/api/zeta/sync").json()["detail"]

    lifted = moderator.delete(f"/api/zeta/bans/{ban_id}")
    assert lifted.status_code == 200
    assert lifted.json()["bans"] == []
    assert _joined(guest)
    assert [e["eventType"] for e in _audit(mod, service)] == ["zeta.unbanned", "zeta.banned"]


def test_expired_bans_stop_applying(monkeypatch, tmp_path):
    mod, _service, moderator = _moderated_app(monkeypatch, tmp_path)
    guest = _guest_client(mod, "Night Owl")
    handle = _member_handle(moderator, "Night Owl")
    moderator.post("/api/zeta/bans", json={"handle": handle, "duration": "15m"})
    assert not _joined(guest)

    bans = mod._storage_backend().read_json(mod._ZETA_BANS_KEY)
    bans["bans"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    mod.write_json(mod._ZETA_BANS_KEY, bans)
    mod._zeta_bans_cache = None
    assert _joined(guest)


def test_only_moderators_ban_and_command_cannot_be_banned(monkeypatch, tmp_path):
    mod, _service, moderator = _moderated_app(monkeypatch, tmp_path)
    guest = _guest_client(mod, "Night Owl")
    lark = _guest_client(mod, "Lark")
    lark_handle = _member_handle(guest, "Lark")

    attempt = guest.post("/api/zeta/bans", json={"handle": lark_handle, "duration": "1h"})
    assert attempt.status_code == 403
    assert _joined(lark)

    owner_handle = next(
        m["handle"]
        for m in moderator.get("/api/zeta/sync?members=1").json()["members"]
        if m["group"] == "command" and not m["self"]
    )
    assert moderator.post(
        "/api/zeta/bans", json={"handle": owner_handle, "duration": "1h"}
    ).status_code == 403
    own = _member_handle(moderator, self_=True)
    assert moderator.post("/api/zeta/bans", json={"handle": own, "duration": "1h"}).status_code == 400
    bad = moderator.post("/api/zeta/bans", json={"handle": lark_handle, "duration": "forever-ish"})
    assert bad.status_code == 400


def test_ping_shows_only_the_latest_message_once(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    alpha = _guest_client(mod, "Alpha")
    bravo = _guest_client(mod, "Bravo")
    bravo_handle = _member_handle(alpha, "Bravo")
    alpha_handle = _member_handle(bravo, "Alpha")

    assert bravo.post("/api/zeta/ping").json() == {"ping": None}

    for text in ("First", "Second", "Third"):
        mod._ZETA_SEND_LIMITER.reset()
        alpha.post(f"/api/zeta/dm/{bravo_handle}", json={"message": text})

    ping = bravo.post("/api/zeta/ping").json()["ping"]
    assert ping["from"] == "Alpha"
    assert ping["preview"] == "Third"
    assert ping["unread_total"] == 3
    assert ping["url"] == f"/zeta#dm-{alpha_handle}"
    # Already shown: other tabs and later page loads stay quiet.
    assert bravo.post("/api/zeta/ping").json() == {"ping": None}
    # The sender is not pinged about their own message.
    assert alpha.post("/api/zeta/ping").json() == {"ping": None}

    mod._ZETA_SEND_LIMITER.reset()
    alpha.post(f"/api/zeta/dm/{bravo_handle}", json={"message": "Fourth"})
    bravo.get(f"/api/zeta/sync?dm={alpha_handle}")  # read it in ZETA first
    assert bravo.post("/api/zeta/ping").json() == {"ping": None}


def test_ping_waits_for_the_next_visit(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    alpha = _guest_client(mod, "Alpha")
    bravo = _guest_client(mod, "Bravo")
    alpha.post(f"/api/zeta/dm/{_member_handle(alpha, 'Bravo')}", json={"message": "While you were out"})

    # Bravo had no page open; the ping is still waiting when they come back.
    assert bravo.post("/api/zeta/ping").json()["ping"]["preview"] == "While you were out"


def test_ping_script_loads_site_wide_but_not_on_zeta(monkeypatch, tmp_path):
    mod = _load_app(monkeypatch, tmp_path)
    anonymous = TestClient(mod.app, base_url="https://testserver")
    anonymous.cookies.set(mod.TOS_CONSENT_COOKIE_NAME, mod.TOS_CONSENT_COOKIE_VALUE)
    assert "zeta_ping.js" not in anonymous.get("/features").text

    guest = _guest_client(mod, "Alpha")
    guest.cookies.set(mod.TOS_CONSENT_COOKIE_NAME, mod.TOS_CONSENT_COOKIE_VALUE)
    assert "zeta_ping.js" in guest.get("/features").text
    assert "zeta_ping.js" not in guest.get("/zeta").text


def _client_with(mod, *, ip="198.51.100.7", device=None, fp=None, discord_id=None):
    """A browser on ``ip`` with optional ZETA device marker, fingerprint and Discord session."""

    client = TestClient(mod.app, base_url="https://testserver")
    client.headers["x-test-ip"] = ip
    if device:
        client.cookies.set(mod._ZETA_DEVICE_COOKIE, device)
    if fp:
        client.cookies.set(mod._ZETA_FINGERPRINT_COOKIE, fp)
    if discord_id:
        client.cookies.set(
            mod.SESSION_COOKIE_NAME,
            _session_cookie(mod, {"user": {"username": "Evader", "id": discord_id}, "discord_token": {"access_token": "x"}}),
        )
    return client


@pytest.fixture
def traced_app(monkeypatch, tmp_path):
    mod, service, moderator = _moderated_app(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_client_ip_from_request", lambda request: request.headers.get("x-test-ip", "198.51.100.1"))
    import vpn_blocklist

    monkeypatch.setattr(vpn_blocklist, "_current", vpn_blocklist.Blocklist({}))
    return mod, service, moderator


def _ban(moderator, label):
    handle = _member_handle(moderator, label)
    response = moderator.post("/api/zeta/bans", json={"handle": handle, "duration": "7d"})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("shared", ["device", "fp", "discord_id"])
def test_ban_follows_a_device_fingerprint_or_discord_account_to_a_new_ip(traced_app, shared):
    mod, service, moderator = traced_app
    traits = {"device": "a" * 32, "fp": "b" * 64, "discord_id": "777777777777777777"}
    banned = _client_with(mod, ip="198.51.100.10", **{shared: traits[shared]})
    banned.post("/zeta/join", data={"name": "Night Owl"})
    assert _joined(banned)
    _ban(moderator, "Night Owl")

    # Same trait, new IP, new name.
    evader = _client_with(mod, ip="198.51.100.99", **{shared: traits[shared]})
    evader.post("/zeta/join", data={"name": "Totally New"})
    assert not _joined(evader)
    assert "Access suspended" in evader.get("/zeta").text

    # Someone else on that new IP is unaffected.
    bystander = _client_with(mod, ip="198.51.100.99", device="c" * 32, fp="d" * 64)
    bystander.post("/zeta/join", data={"name": "Bystander"})
    assert _joined(bystander)

    counts = _audit(mod, service)[0]["metadata"]
    expected = {"device": "deviceCount", "fp": "fingerprintCount", "discord_id": "discordCount"}[shared]
    assert counts[expected] == 1


def test_malformed_device_cookies_are_ignored(traced_app):
    mod, _service, _moderator = traced_app
    client = _client_with(mod, device="not-hex", fp="short")
    client.post("/zeta/join", data={"name": "Night Owl"})
    assert _joined(client)
    traces = mod._zeta_member_traces(next(iter(mod._zeta_guests())))
    assert traces["devices"] == [] and traces["fingerprints"] == []
    assert len(traces["ips"]) == 1


def test_guests_cannot_use_zeta_through_a_vpn(traced_app):
    mod, _service, moderator = traced_app
    import vpn_blocklist

    vpn_blocklist.install({"vpn": ["45.83.0.0/16"], "datacenter": ["2a05:d000::/25"], "tor": ["185.220.101.4"]})

    for ip, label in (("45.83.12.1", "a VPN"), ("2a05:d000::1", "hosting network"), ("185.220.101.4", "Tor")):
        guest = _client_with(mod, ip=ip)
        guest.post("/zeta/join", data={"name": f"Guest {ip}"})
        assert not _joined(guest), ip
        page = guest.get("/zeta").text
        assert "VPN detected" in page and label in page and 'action="/zeta/join"' not in page

    # A guest who joined at home is cut off once they switch the VPN on.
    home = _client_with(mod, ip="198.51.100.20")
    home.post("/zeta/join", data={"name": "Night Owl"})
    assert _joined(home)
    home.headers["x-test-ip"] = "45.83.12.1"
    blocked = home.get("/api/zeta/sync")
    assert blocked.status_code == 403
    assert "sign in with Discord" in blocked.json()["detail"]

    # Signing in with Discord is the way in from a VPN; moderators are never blocked.
    discord_guest = _client_with(mod, ip="45.83.12.1", discord_id="888888888888888888")
    discord_guest.post("/zeta/join", data={"name": "Lark"})
    assert _joined(discord_guest)
    moderator.headers["x-test-ip"] = "45.83.12.1"
    assert moderator.get("/api/zeta/sync").status_code == 200


def test_vpn_blocklist_matches_ranges_and_fails_open():
    import vpn_blocklist

    empty = vpn_blocklist.Blocklist({})
    assert empty.classify("45.83.12.1") is None

    blocklist = vpn_blocklist.Blocklist(
        {
            "vpn": ["45.83.0.0/16", "45.84.0.0/16", "# comment", "garbage"],
            "datacenter": ["2a05:d000::/25", "8.8.8.0/24"],
            "tor": ["185.220.101.4"],
        }
    )
    assert len(blocklist.ranges["vpn"][4]) == 1  # adjacent ranges merge
    assert blocklist.classify("45.84.255.255") == "vpn"
    assert blocklist.classify("45.85.0.0") is None
    assert blocklist.classify("::ffff:45.83.1.1") == "vpn"
    assert blocklist.classify("2a05:d000:1::1") == "datacenter"
    assert blocklist.classify("185.220.101.4") == "tor"
    assert blocklist.classify("185.220.101.5") is None
    assert blocklist.classify("192.168.1.1") is None
    assert blocklist.classify("Unknown") is None


def test_vpn_blocklist_refresh_caches_and_keeps_old_lists_on_failure(monkeypatch, tmp_path):
    import asyncio

    import vpn_blocklist

    store = {}

    class Backend:
        def write_json(self, key, data, etag=None):
            store[key] = json.loads(json.dumps(data))
            return True

        def read_json(self, key):
            if key not in store:
                raise FileNotFoundError(key)
            return store[key]

    class Response:
        def __init__(self, text, status=200):
            self.text, self.status = text, status

        def raise_for_status(self):
            if self.status != 200:
                raise RuntimeError("HTTP %s" % self.status)

    class Client:
        def __init__(self, fail=False):
            self.fail = fail

        async def get(self, url, timeout=None):
            if self.fail:
                return Response("", 503)
            return Response("185.220.101.4\n" if "tor" in url else "45.83.0.0/16\n")

    monkeypatch.setattr(vpn_blocklist, "_current", vpn_blocklist.Blocklist({}))
    assert asyncio.run(vpn_blocklist.refresh(Backend(), Client())) is True
    assert vpn_blocklist.classify("45.83.1.1") == "vpn"
    assert asyncio.run(vpn_blocklist.refresh(Backend(), Client(fail=True))) is False
    assert vpn_blocklist.classify("45.83.1.1") == "vpn"

    monkeypatch.setattr(vpn_blocklist, "_current", vpn_blocklist.Blocklist({}))
    assert vpn_blocklist.load_cached(Backend()) is not None
    assert vpn_blocklist.classify("185.220.101.4") == "tor"
