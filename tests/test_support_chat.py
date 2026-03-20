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
