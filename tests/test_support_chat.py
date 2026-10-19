from __future__ import annotations

import importlib
import sys

import jwt
import pytest
from fastapi.testclient import TestClient

from owner_portal import OWNER_USER_KEY


@pytest.fixture
def support_chat_mod(monkeypatch):
    """Fresh ``support_chat`` with in-memory JSON backend."""

    import support_chat as sc

    store: dict = {}

    def fake_read(path: str):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def fake_write(path: str, data: dict, *, etag=None):
        store[path] = data
        return True

    monkeypatch.setattr(sc, "read_json", fake_read)
    monkeypatch.setattr(sc, "write_json", fake_write)
    yield sc
    store.clear()


def test_append_message_creates_thread(support_chat_mod):
    sc = support_chat_mod
    admin_id = str(OWNER_USER_KEY)
    msg, key = sc.append_message(
        member_id="100",
        target_admin_id=admin_id,
        sender_id="100",
        sender_label="Pilot",
        is_staff=False,
        body="Hello admins",
    )
    assert msg["body"] == "Hello admins"
    assert ":" in key
    thread = sc.get_thread_for_pair("100", admin_id)
    assert thread is not None
    assert len(thread["messages"]) == 1


def test_staff_reply_same_thread(support_chat_mod):
    sc = support_chat_mod
    aid = "99"
    sc.append_message(
        member_id="200",
        target_admin_id=aid,
        sender_id="200",
        sender_label="Recruit",
        is_staff=False,
        body="Need help",
    )
    sc.append_message(
        member_id="200",
        target_admin_id=aid,
        sender_id="99",
        sender_label="Overseer",
        is_staff=True,
        body="On it.",
    )
    thread = sc.get_thread_for_pair("200", aid)
    assert len(thread["messages"]) == 2
    assert thread["messages"][1]["isStaff"] is True


def test_delete_thread(support_chat_mod):
    sc = support_chat_mod
    aid = "88"
    sc.append_message(
        member_id="300",
        target_admin_id=aid,
        sender_id="300",
        sender_label="X",
        is_staff=False,
        body="Ping",
    )
    assert sc.delete_thread_by_pair("300", aid) is True
    assert sc.get_thread_for_pair("300", aid) is None
    assert sc.delete_thread_by_pair("300", aid) is False


def test_list_thread_summaries_ordered(support_chat_mod):
    sc = support_chat_mod
    sc.append_message(
        member_id="400",
        target_admin_id="11",
        sender_id="400",
        sender_label="A",
        is_staff=False,
        body="First",
    )
    sc.append_message(
        member_id="500",
        target_admin_id="22",
        sender_id="500",
        sender_label="B",
        is_staff=False,
        body="Second",
    )
    summaries = sc.list_thread_summaries()
    assert len(summaries) == 2
    assert all("targetAdminId" in s for s in summaries)


def _reload_config_app(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def test_support_chat_api_member_thread_and_staff_inbox(monkeypatch):
    mod = _reload_config_app(monkeypatch)
    import support_chat as sc

    store: dict = {}

    def fake_read(path: str):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def fake_write(path: str, data: dict, *, etag=None):
        store[path] = data
        return True

    monkeypatch.setattr(sc, "read_json", fake_read)
    monkeypatch.setattr(sc, "write_json", fake_write)

    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="x",
        managers=["99"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    monkeypatch.setattr(
        mod,
        "load_admin_team_settings",
        lambda: mod.AdminTeamSettings(members=[], ranks={}, clearances={}),
    )

    def token_for(sub: str, name: str):
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        return jwt.encode(
            {
                "sub": sub,
                "name": name,
                "role": "Admin",
                "iat": int(now.timestamp()),
                "exp": int(now.timestamp()) + 3600,
            },
            "test-secret",
            algorithm="HS256",
        )

    client = TestClient(mod.app)

    member_tok = token_for("400", "Member Four")
    staff_tok = token_for("99", "Staff Nine")

    target_admin = str(OWNER_USER_KEY)

    r = client.get(
        "/api/support-chat/with/" + target_admin,
        headers={"Authorization": f"Bearer {member_tok}"},
    )
    assert r.status_code == 200
    assert r.json()["thread"]["messages"] == []

    r = client.post(
        "/api/support-chat/messages",
        headers={"Authorization": f"Bearer {member_tok}"},
        json={"body": "Please advise", "targetAdminId": target_admin},
    )
    assert r.status_code == 200
    assert r.json()["message"]["body"] == "Please advise"

    r = client.get(
        "/api/support-chat/inbox",
        headers={"Authorization": f"Bearer {staff_tok}"},
    )
    assert r.status_code == 200
    threads = r.json()["threads"]
    assert len(threads) == 1
    assert threads[0]["threadUserId"] == "400"
    assert threads[0]["targetAdminId"] == target_admin

    r = client.post(
        "/api/support-chat/messages",
        headers={"Authorization": f"Bearer {staff_tok}"},
        json={
            "body": "Roger.",
            "threadUserId": "400",
            "targetAdminId": target_admin,
        },
    )
    assert r.status_code == 200

    r = client.get(
        f"/api/support-chat/thread/400/{target_admin}",
        headers={"Authorization": f"Bearer {staff_tok}"},
    )
    assert r.status_code == 200
    assert len(r.json()["thread"]["messages"]) == 2

    r = client.delete(
        f"/api/support-chat/thread/400/{target_admin}",
        headers={"Authorization": f"Bearer {staff_tok}"},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] is True


def test_guest_support_chat_without_discord(monkeypatch):
    mod = _reload_config_app(monkeypatch)
    import support_chat as sc

    store: dict = {}

    def fake_read(path: str):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def fake_write(path: str, data: dict, *, etag=None):
        store[path] = data
        return True

    monkeypatch.setattr(sc, "read_json", fake_read)
    monkeypatch.setattr(sc, "write_json", fake_write)

    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="x",
        managers=["99"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    monkeypatch.setattr(
        mod,
        "load_admin_team_settings",
        lambda: mod.AdminTeamSettings(members=[], ranks={}, clearances={}),
    )

    client = TestClient(mod.app, base_url="https://testserver")
    target_admin = str(OWNER_USER_KEY)

    r = client.post("/api/support-chat/guest/start", json={"name": "Site visitor"})
    assert r.status_code == 200
    body = r.json()
    assert body["guestId"].startswith("guest")
    assert body["name"] == "Site visitor"

    r = client.get(f"/api/support-chat/with/{target_admin}")
    assert r.status_code == 200
    assert r.json()["thread"]["messages"] == []

    r = client.post(
        "/api/support-chat/messages",
        json={"body": "Hello from the website", "targetAdminId": target_admin},
    )
    assert r.status_code == 200
    assert r.json()["message"]["body"] == "Hello from the website"

    r = client.get("/api/support-chat/guest/me")
    assert r.status_code == 200
    assert r.json()["guest"]["name"] == "Site visitor"


@pytest.fixture
def support_api(monkeypatch):
    """config_app with in-memory support store, owner + manager "99" as admins."""

    mod = _reload_config_app(monkeypatch)
    import support_chat as sc

    store: dict = {}

    def fake_read(path: str):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def fake_write(path: str, data: dict, *, etag=None):
        store[path] = data
        return True

    monkeypatch.setattr(sc, "read_json", fake_read)
    monkeypatch.setattr(sc, "write_json", fake_write)
    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="x",
        managers=["99"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    monkeypatch.setattr(
        mod,
        "load_admin_team_settings",
        lambda: mod.AdminTeamSettings(members=[], ranks={}, clearances={}),
    )
    mod._SUPPORT_MESSAGE_LIMITER.reset()
    mod._SUPPORT_GUEST_START_LIMITER.reset()
    return mod


def _bearer(sub: str, role: str = "Member", name: str = "Pilot") -> dict[str, str]:
    import datetime

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": sub, "name": name, "role": role, "iat": now, "exp": now + 3600},
        "test-secret",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_support_chat_requires_identity(support_api):
    client = TestClient(support_api.app, base_url="https://testserver")
    response = client.get(f"/api/support-chat/with/{OWNER_USER_KEY}")
    assert response.status_code == 401


def test_support_chat_members_cannot_use_staff_endpoints(support_api):
    client = TestClient(support_api.app, base_url="https://testserver")
    owner = str(OWNER_USER_KEY)
    victim = _bearer("500")
    assert client.post(
        "/api/support-chat/messages",
        headers=victim,
        json={"body": "private", "targetAdminId": owner},
    ).status_code == 200

    attacker = _bearer("600")
    # Even an "Admin" role claim is not enough without being a portal manager.
    forged = _bearer("600", role="Admin")
    for headers in (attacker, forged):
        assert client.get("/api/support-chat/inbox", headers=headers).status_code == 403
        assert client.get(f"/api/support-chat/thread/500/{owner}", headers=headers).status_code == 403
        assert client.delete(f"/api/support-chat/thread/500/{owner}", headers=headers).status_code == 403
        reply = client.post(
            "/api/support-chat/messages",
            headers=headers,
            json={"body": "spoofed staff reply", "threadUserId": "500", "targetAdminId": owner},
        )
        assert reply.status_code == 403


def test_support_chat_rejects_targets_outside_admin_roster(support_api):
    client = TestClient(support_api.app, base_url="https://testserver")
    response = client.post(
        "/api/support-chat/messages",
        headers=_bearer("500"),
        json={"body": "hello", "targetAdminId": "123456"},
    )
    assert response.status_code == 404


def test_support_chat_staff_cannot_open_new_threads_by_reply(support_api):
    client = TestClient(support_api.app, base_url="https://testserver")
    response = client.post(
        "/api/support-chat/messages",
        headers=_bearer("99", role="Admin"),
        json={"body": "hi", "threadUserId": "777", "targetAdminId": str(OWNER_USER_KEY)},
    )
    assert response.status_code == 404


def test_support_chat_guest_session_survives_and_keeps_id(support_api):
    client = TestClient(support_api.app, base_url="https://testserver")
    first = client.post("/api/support-chat/guest/start", json={"name": "  Ghost   Rider "}).json()
    assert first["name"] == "Ghost Rider"
    second = client.post("/api/support-chat/guest/start", json={"name": "Ghost"}).json()
    assert second["guestId"] == first["guestId"]
    assert client.post("/api/support-chat/guest/start", json={"name": "   "}).status_code == 400


def test_support_chat_message_rate_limit(support_api, monkeypatch):
    monkeypatch.setattr(
        support_api,
        "_SUPPORT_MESSAGE_LIMITER",
        support_api._SlidingWindowRateLimiter(limit=2, window_seconds=60.0),
    )
    client = TestClient(support_api.app, base_url="https://testserver")
    statuses = [
        client.post(
            "/api/support-chat/messages",
            headers=_bearer("500"),
            json={"body": f"msg {i}", "targetAdminId": str(OWNER_USER_KEY)},
        ).status_code
        for i in range(3)
    ]
    assert statuses == [200, 200, 429]


def test_support_chat_events_only_reach_their_thread(support_api):
    import asyncio

    mod = support_api
    owner = str(OWNER_USER_KEY)
    member_queue: asyncio.Queue = asyncio.Queue(maxsize=5)
    other_queue: asyncio.Queue = asyncio.Queue(maxsize=5)
    staff_queue: asyncio.Queue = asyncio.Queue(maxsize=5)
    with mod._SUPPORT_STREAM_LOCK:
        mod._SUPPORT_STREAM_SUBSCRIBERS[member_queue] = f"500:{owner}"
        mod._SUPPORT_STREAM_SUBSCRIBERS[other_queue] = f"600:{owner}"
        mod._SUPPORT_STREAM_SUBSCRIBERS[staff_queue] = None
    try:
        mod._publish_support_event(f"500:{owner}", {"type": "message"})
    finally:
        with mod._SUPPORT_STREAM_LOCK:
            mod._SUPPORT_STREAM_SUBSCRIBERS.clear()

    assert member_queue.qsize() == 1
    assert staff_queue.qsize() == 1
    assert other_queue.qsize() == 0


def test_message_pages_are_not_redirected_to_moderation_spa(support_api, monkeypatch):
    mod = support_api
    monkeypatch.setenv("ADMIN_MODERATION_SPA_ENABLED", "1")

    async def _anonymous_context(_request):
        return None, []

    async def _roster(ids, *_args, **_kwargs):
        return [{"id": str(i), "name": "Owner"} for i in ids]

    monkeypatch.setattr(mod, "_load_user_context", _anonymous_context)
    monkeypatch.setattr(mod, "load_admin_bios", lambda: {})
    monkeypatch.setattr(mod, "_build_admin_roster_entries", _roster)
    client = TestClient(mod.app, base_url="https://testserver")

    response = client.get(f"/admin-team/message/{OWNER_USER_KEY}", follow_redirects=False)
    assert response.status_code == 200
    assert 'id="dm-root"' in response.text
