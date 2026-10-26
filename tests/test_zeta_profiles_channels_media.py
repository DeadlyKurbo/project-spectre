"""Project ZETA profiles, extra channels, picture and video uploads, and message edits."""

import io
import os
import time
from types import SimpleNamespace

import pytest

from tests.test_alice_chat import (
    MODERATOR_ID,
    _authed_client,
    _grant_chat_access,
    _guest_client,
    _load_app,
    _member_handle,
    _moderated_app,
    _release_storage_root,  # noqa: F401 - autouse fixture
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200
MEMBER_ID = "123456789012345678"


@pytest.fixture
def app(monkeypatch, tmp_path):
    mod, service, moderator = _moderated_app(monkeypatch, tmp_path)
    # Tests send faster than the 3-second limit allows.
    unlimited = SimpleNamespace(hit=lambda key: False)
    monkeypatch.setattr(mod, "_ZETA_SEND_LIMITER", unlimited)
    monkeypatch.setattr(mod, "_ZETA_PROFILE_LIMITER", unlimited)
    monkeypatch.setattr(mod, "_ZETA_UPLOAD_LIMITER", unlimited)
    mod._zeta_channel_tails.clear()
    return SimpleNamespace(mod=mod, service=service, moderator=moderator)


def _upload(client, room, data, *, name="clip.bin", message=""):
    return client.post(
        "/api/zeta/upload",
        data={"room": room, "message": message},
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )


def _me(client):
    return client.get("/api/zeta/sync").json()["me"]


# ---------- Profiles ----------


def test_custom_name_replaces_the_callsign_for_everyone_and_resets(app):
    _grant_chat_access(app.mod, MEMBER_ID)
    app.mod._zeta_remember_member({"id": MEMBER_ID, "username": "Delta"})
    member = _authed_client(app.mod, MEMBER_ID)
    guest = _guest_client(app.mod, "Night Owl")

    assert _me(member)["label"] == "Operator D"
    saved = member.put("/api/zeta/profile/name", json={"name": "  Ghost   Rider "})
    assert saved.status_code == 200
    assert saved.json()["me"]["label"] == "Ghost Rider"
    assert saved.json()["me"]["default_label"] == "Operator D"

    member.post("/api/alice/chat", json={"message": "Hi"})
    seen = guest.get("/api/zeta/sync?members=1").json()
    assert seen["channel"][-1]["operator"] == "Ghost Rider"
    assert any(m["label"] == "Ghost Rider" for m in seen["members"])

    # Moderators see the custom name, and who is behind it.
    listed = next(m for m in app.moderator.get("/api/zeta/sync?members=1").json()["members"] if m["label"] == "Ghost Rider")
    assert listed["real_name"] == "Delta"

    reset = member.delete("/api/zeta/profile/name")
    assert reset.json()["me"]["label"] == "Operator D"
    assert guest.get("/api/zeta/sync").json()["channel"][-1]["operator"] == "Operator D"


def test_guests_can_rename_and_reset_to_their_join_name(app):
    guest = _guest_client(app.mod, "Night Owl")
    assert guest.put("/api/zeta/profile/name", json={"name": "Kestrel"}).json()["me"]["label"] == "Kestrel"
    assert guest.delete("/api/zeta/profile/name").json()["me"]["label"] == "Night Owl"
    # Picking the name you would have anyway is the same as resetting.
    guest.put("/api/zeta/profile/name", json={"name": "Kestrel"})
    assert guest.put("/api/zeta/profile/name", json={"name": "night owl"}).json()["me"]["nickname"] == ""


@pytest.mark.parametrize("name", ["Lark", "LARK", "Operator Z", "moderator", "Delta", "Taken One", "   "])
def test_custom_names_cannot_copy_or_impersonate(app, name):
    _grant_chat_access(app.mod, MEMBER_ID)
    _authed_client(app.mod, MEMBER_ID)
    _guest_client(app.mod, "Lark")
    _guest_client(app.mod, "Somebody").put("/api/zeta/profile/name", json={"name": "Taken One"})
    app.mod._zeta_remember_member({"id": MEMBER_ID, "username": "Delta"})

    attempt = _guest_client(app.mod, "Night Owl").put("/api/zeta/profile/name", json={"name": name})
    assert attempt.status_code == 400


def test_new_guests_cannot_join_under_someones_custom_name(app):
    _guest_client(app.mod, "Night Owl").put("/api/zeta/profile/name", json={"name": "Kestrel"})
    newcomer = _guest_client(app.mod, "Kestrel")
    assert newcomer.get("/api/zeta/sync").status_code == 401


def test_profile_picture_upload_serve_replace_and_reset(app):
    guest = _guest_client(app.mod, "Night Owl")
    other = _guest_client(app.mod, "Lark")

    uploaded = guest.post("/api/zeta/profile/avatar", files={"file": ("me.png", io.BytesIO(PNG), "image/png")})
    assert uploaded.status_code == 200
    first = uploaded.json()["me"]["avatar"]
    assert first.startswith("/media/zeta/avatars/") and first.endswith(".png")

    served = other.get(first)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == PNG
    listed = next(m for m in other.get("/api/zeta/sync?members=1").json()["members"] if m["label"] == "Night Owl")
    assert listed["avatar"] == first

    guest.post("/api/alice/chat", json={"message": "Look"})
    assert other.get("/api/zeta/sync").json()["channel"][-1]["avatar"] == first

    second = guest.post("/api/zeta/profile/avatar", files={"file": ("me.jpg", io.BytesIO(JPEG), "image/jpeg")})
    assert second.json()["me"]["avatar"].endswith(".jpg")
    assert other.get(first).status_code == 404  # the old picture is deleted

    reset = guest.delete("/api/zeta/profile/avatar")
    assert reset.json()["me"]["avatar"] == ""
    assert other.get(second.json()["me"]["avatar"]).status_code == 404


def test_profile_pictures_must_be_pictures(app):
    guest = _guest_client(app.mod, "Night Owl")
    for name, data in (("clip.mp4", MP4), ("page.html", b"<script>alert(1)</script>"), ("empty.png", b"")):
        rejected = guest.post("/api/zeta/profile/avatar", files={"file": (name, io.BytesIO(data), "image/png")})
        assert rejected.status_code == 400, name
    assert _me(guest)["avatar"] == ""


def test_media_requires_zeta_access(app):
    guest = _guest_client(app.mod, "Night Owl")
    avatar = guest.post("/api/zeta/profile/avatar", files={"file": ("me.png", io.BytesIO(PNG), "image/png")})
    from fastapi.testclient import TestClient

    stranger = TestClient(app.mod.app, base_url="https://testserver")
    assert stranger.get(avatar.json()["me"]["avatar"]).status_code == 401


# ---------- Channels ----------


def test_moderators_create_channels_everyone_can_use(app):
    guest = _guest_client(app.mod, "Night Owl")

    created = app.moderator.post("/api/zeta/channels", json={"name": "Field Ops!", "topic": "Mission chatter"})
    assert created.status_code == 200
    assert created.json()["channel"] == "field-ops"
    ids = [c["id"] for c in created.json()["channels"]]
    assert ids == ["zeta-ops", "field-ops"]

    posted = guest.post("/api/zeta/channels/field-ops/messages", json={"message": "In position"})
    assert posted.status_code == 200
    assert posted.json()["messages"][-1]["message"] == "In position"

    sync = app.moderator.get("/api/zeta/sync?channel=field-ops").json()
    assert sync["channel_id"] == "field-ops"
    assert [m["message"] for m in sync["channel"]] == ["In position"]
    # The default channel stays separate, and the channel list marks the new message for unread dots.
    assert app.moderator.get("/api/zeta/sync").json()["channel"] == []
    field = next(c for c in sync["channels"] if c["id"] == "field-ops")
    assert field["latest"] == posted.json()["messages"][-1]["id"]
    assert field["topic"] == "Mission chatter" and field["custom"] is True

    events = [e["eventType"] for e in __import__("asyncio").run(app.service.list_audit_events(limit=10))]
    assert "zeta.channel_created" in events


def test_command_members_can_create_channels_but_operators_and_guests_cannot(app, monkeypatch):
    _grant_chat_access(app.mod, MEMBER_ID)
    member = _authed_client(app.mod, MEMBER_ID)
    guest = _guest_client(app.mod, "Night Owl")
    assert member.post("/api/zeta/channels", json={"name": "ops"}).status_code == 403
    assert guest.post("/api/zeta/channels", json={"name": "ops"}).status_code == 403

    settings, etag = app.mod.load_owner_settings(with_etag=True)
    updated = settings.copy()
    updated.managers.append(MEMBER_ID)
    app.mod.save_owner_settings(updated, etag=etag)
    # Managers are portal admins too; check the command group on its own.
    monkeypatch.setattr(app.mod, "_session_user_is_admin", lambda request: False)
    assert member.post("/api/zeta/channels", json={"name": "ops"}).status_code == 200


def test_channel_names_must_be_unique_and_valid(app):
    assert app.moderator.post("/api/zeta/channels", json={"name": "zeta ops"}).status_code == 400
    assert app.moderator.post("/api/zeta/channels", json={"name": "!!!"}).status_code == 400
    assert app.moderator.post("/api/zeta/channels", json={"name": "intel"}).status_code == 200
    assert app.moderator.post("/api/zeta/channels", json={"name": "INTEL"}).status_code == 400


def test_unknown_channels_are_not_found(app):
    guest = _guest_client(app.mod, "Night Owl")
    assert guest.get("/api/zeta/sync?channel=nope").status_code == 404
    assert guest.post("/api/zeta/channels/nope/messages", json={"message": "x"}).status_code == 404
    assert guest.post("/api/zeta/channels/..%2F..%2Fsecrets/messages", json={"message": "x"}).status_code == 404


def test_deleting_a_channel_removes_its_messages_and_files(app):
    guest = _guest_client(app.mod, "Night Owl")
    app.moderator.post("/api/zeta/channels", json={"name": "intel"})
    guest.post("/api/zeta/channels/intel/messages", json={"message": "secret"})
    url = _upload(guest, "channel:intel", PNG).json()["messages"][-1]["attachment"]["url"]
    assert guest.get(url).status_code == 200

    assert guest.delete("/api/zeta/channels/intel").status_code == 403
    assert app.moderator.delete("/api/zeta/channels/zeta-ops").status_code == 400
    deleted = app.moderator.delete("/api/zeta/channels/intel")
    assert deleted.status_code == 200
    assert [c["id"] for c in deleted.json()["channels"]] == ["zeta-ops"]
    assert guest.get(url).status_code == 404
    assert app.mod._storage_backend().list_tree("zeta/media/intel") == []

    # A new channel under the same name starts empty.
    app.moderator.post("/api/zeta/channels", json={"name": "intel"})
    assert guest.get("/api/zeta/sync?channel=intel").json()["channel"] == []


# ---------- Pictures and videos ----------


def test_pictures_and_videos_post_to_channels_with_captions(app):
    guest = _guest_client(app.mod, "Night Owl")
    other = _guest_client(app.mod, "Lark")

    photo = _upload(guest, "channel:zeta-ops", PNG, name="sitrep.png", message="Look at this")
    assert photo.status_code == 200
    entry = photo.json()["messages"][-1]
    assert entry["message"] == "Look at this"
    assert entry["attachment"]["kind"] == "image"
    assert entry["attachment"]["name"] == "sitrep.png"
    assert entry["attachment"]["url"].startswith("/media/zeta/channel/zeta-ops/")

    video = _upload(guest, "channel:zeta-ops", MP4, name="IMG_0001.MOV")
    assert video.status_code == 200
    clip = video.json()["messages"][-1]
    assert clip["message"] == "" and clip["attachment"]["kind"] == "video"

    seen = other.get("/api/zeta/sync").json()["channel"]
    assert [m["attachment"]["kind"] for m in seen] == ["image", "video"]

    # Videos stream in ranges, so players can seek.
    whole = other.get(clip["attachment"]["url"])
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "video/mp4"
    assert whole.headers["accept-ranges"] == "bytes"
    part = other.get(clip["attachment"]["url"], headers={"Range": "bytes=4-11"})
    assert part.status_code == 206
    assert part.content == b"ftypisom"


def test_uploads_are_checked_by_content_and_size(app, monkeypatch):
    guest = _guest_client(app.mod, "Night Owl")
    for name, data in (("evil.png", b"<svg onload=alert(1)>"), ("photo.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32), ("x.png", b"")):
        rejected = _upload(guest, "channel:zeta-ops", data, name=name)
        assert rejected.status_code == 400, name
    assert guest.post("/api/zeta/upload", data={"room": "channel:zeta-ops"}).status_code == 400
    assert _upload(guest, "nowhere", PNG).status_code == 400

    monkeypatch.setattr(app.mod.zeta_media, "MAX_BYTES", len(PNG) - 1)
    too_big = _upload(guest, "channel:zeta-ops", PNG)
    assert too_big.status_code == 400
    assert "at most" in too_big.json()["detail"]
    assert guest.get("/api/zeta/sync").json()["channel"] == []


def test_upload_limit_is_fifty_megabytes():
    import security_shield
    import zeta_media

    assert zeta_media.MAX_BYTES == 50 * 1024 * 1024
    # The shield in front of the app lets a full 50 MB file plus its form through.
    assert security_shield.ShieldSettings().max_upload_bytes > zeta_media.MAX_BYTES


def test_uploads_are_capped_per_hour(app, monkeypatch):
    guest = _guest_client(app.mod, "Night Owl")
    monkeypatch.setattr(app.mod, "_ZETA_UPLOAD_LIMITER", app.mod._SlidingWindowRateLimiter(limit=1, window_seconds=3600))
    assert _upload(guest, "channel:zeta-ops", PNG).status_code == 200
    capped = _upload(guest, "channel:zeta-ops", PNG)
    assert capped.status_code == 429
    assert len(guest.get("/api/zeta/sync").json()["channel"]) == 1


def test_direct_message_media_is_only_for_the_two_participants(app):
    sender = _guest_client(app.mod, "Night Owl")
    recipient = _guest_client(app.mod, "Lark")
    outsider = _guest_client(app.mod, "Kestrel")
    lark = _member_handle(sender, "Lark")
    owl = _member_handle(recipient, "Night Owl")

    sent = _upload(sender, f"dm:{lark}", JPEG, message="for you")
    assert sent.status_code == 200
    url = sent.json()["dm"]["messages"][-1]["attachment"]["url"]
    name = url.rsplit("/", 1)[1]
    assert sender.get(url).status_code == 200

    received = recipient.get(f"/api/zeta/sync?dm={owl}").json()["dm"]["messages"][-1]
    assert received["attachment"]["url"] == f"/media/zeta/dm/{owl}/{name}"
    assert recipient.get(received["attachment"]["url"]).content == JPEG
    thread = next(t for t in recipient.get("/api/zeta/sync").json()["threads"] if t["handle"] == owl)
    assert thread["preview"] == "Photo: for you"

    # Someone else cannot reach it through their own thread with either participant.
    assert outsider.get(f"/media/zeta/dm/{owl}/{name}").status_code == 404
    assert outsider.get(f"/media/zeta/dm/{lark}/{name}").status_code == 404

    message_id = sent.json()["dm"]["messages"][-1]["id"]
    assert sender.delete(f"/api/zeta/dm/{lark}/{message_id}").status_code == 200
    assert recipient.get(received["attachment"]["url"]).status_code == 404


def test_deleting_a_channel_message_deletes_its_file(app):
    guest = _guest_client(app.mod, "Night Owl")
    entry = _upload(guest, "channel:zeta-ops", PNG).json()["messages"][-1]
    assert guest.delete(f"/api/zeta/channels/zeta-ops/messages/{entry['id']}").status_code == 200
    assert guest.get(entry["attachment"]["url"]).status_code == 404


def test_purge_sweeps_channel_files_older_than_the_purge(app, tmp_path):
    guest = _guest_client(app.mod, "Night Owl")
    old = _upload(guest, "channel:zeta-ops", PNG).json()["messages"][-1]["attachment"]["url"]
    fresh = _upload(guest, "channel:zeta-ops", JPEG).json()["messages"][-1]["attachment"]["url"]
    path = tmp_path / "zeta" / "media" / "zeta-ops" / old.rsplit("/", 1)[1]
    stale = time.time() - 26 * 3600
    os.utime(path, (stale, stale))

    app.mod._zeta_purge_channels()
    assert guest.get(old).status_code == 404
    assert guest.get(fresh).status_code == 200


# ---------- Editing ----------


def test_authors_edit_their_own_channel_messages(app):
    author = _guest_client(app.mod, "Night Owl")
    other = _guest_client(app.mod, "Lark")
    message_id = author.post("/api/alice/chat", json={"message": "Helo"}).json()["message"]["id"]

    assert other.patch(f"/api/zeta/channels/zeta-ops/messages/{message_id}", json={"message": "x"}).status_code == 403
    # Moderators can delete anyone's message, but not put words in their mouth.
    assert app.moderator.patch(f"/api/zeta/channels/zeta-ops/messages/{message_id}", json={"message": "x"}).status_code == 403
    assert author.patch(f"/api/zeta/channels/zeta-ops/messages/{message_id}", json={"message": "  "}).status_code == 400

    edited = author.patch(f"/api/zeta/channels/zeta-ops/messages/{message_id}", json={"message": "Hello"})
    assert edited.status_code == 200
    entry = edited.json()["messages"][-1]
    assert entry["message"] == "Hello" and entry["edited_at"]
    assert other.get("/api/zeta/sync").json()["channel"][-1]["message"] == "Hello"
    assert author.patch("/api/zeta/channels/zeta-ops/messages/missing", json={"message": "x"}).status_code == 404


def test_captions_can_be_edited_or_cleared(app):
    author = _guest_client(app.mod, "Night Owl")
    entry = _upload(author, "channel:zeta-ops", PNG, message="first").json()["messages"][-1]
    cleared = author.patch(f"/api/zeta/channels/zeta-ops/messages/{entry['id']}", json={"message": ""})
    assert cleared.status_code == 200
    assert cleared.json()["messages"][-1]["message"] == ""
    assert cleared.json()["messages"][-1]["attachment"]["kind"] == "image"


def test_authors_edit_their_own_direct_messages(app):
    sender = _guest_client(app.mod, "Night Owl")
    recipient = _guest_client(app.mod, "Lark")
    lark = _member_handle(sender, "Lark")
    owl = _member_handle(recipient, "Night Owl")
    message_id = sender.post(f"/api/zeta/dm/{lark}", json={"message": "Meet at 9"}).json()["dm"]["messages"][-1]["id"]

    assert recipient.patch(f"/api/zeta/dm/{owl}/{message_id}", json={"message": "x"}).status_code == 404
    edited = sender.patch(f"/api/zeta/dm/{lark}/{message_id}", json={"message": "Meet at 10"})
    assert edited.status_code == 200
    assert edited.json()["dm"]["messages"][-1]["edited_at"]

    seen = recipient.get(f"/api/zeta/sync?dm={owl}").json()
    assert seen["dm"]["messages"][-1]["message"] == "Meet at 10"
    assert next(t for t in seen["threads"] if t["handle"] == owl)["preview"] == "Meet at 10"


# ---------- Page ----------


def test_page_shows_profile_button_and_channel_tools_to_command_only(app):
    guest_page = _guest_client(app.mod, "Night Owl").get("/zeta").text
    assert 'id="profileButton"' in guest_page
    assert 'id="attachButton"' in guest_page
    assert 'id="newChannelButton"' not in guest_page

    moderator_page = app.moderator.get("/zeta").text
    assert 'id="newChannelButton"' in moderator_page
    assert 'id="channelDialog"' in moderator_page
