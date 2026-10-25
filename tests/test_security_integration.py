from __future__ import annotations

import base64
import hashlib
import json

import importlib

import itsdangerous
import pytest
from fastapi.testclient import TestClient

import config_app


ADMIN_ID = "42"


@pytest.fixture(autouse=True)
def _current_app_module():
    """Other tests re-import config_app; always drive the current module."""

    global config_app
    config_app = importlib.import_module("config_app")
    yield


def _session_cookie(data: dict) -> str:
    signer = itsdangerous.TimestampSigner(str(config_app.SESSION_SECRET))
    return signer.sign(base64.b64encode(json.dumps(data).encode("utf-8"))).decode("utf-8")


def _client(user_id: str | None = None) -> TestClient:
    client = TestClient(config_app.app, base_url="https://testserver")
    if user_id:
        cookie = _session_cookie({"user": {"id": user_id, "username": f"user{user_id}", "global_name": "Ada"}})
        client.cookies.set(config_app.SESSION_COOKIE_NAME, cookie)
    return client


@pytest.fixture
def presence(monkeypatch):
    """Empty presence store that never writes to the repository's dossiers."""

    monkeypatch.setattr(config_app, "_persist_admin_presence", lambda _entries: None)
    monkeypatch.setattr(config_app, "_persist_activity_log", lambda _entries: None)
    monkeypatch.setattr(config_app, "_user_is_portal_admin", lambda candidate: str(candidate) == ADMIN_ID)
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE_LOADED = True
    with config_app._ACTIVITY_LOG_LOCK:
        config_app._ACTIVITY_LOGS.clear()
        config_app._ACTIVITY_LOG_LOADED = True
    yield
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()


# ------------------------------------------------------------------- shield


def test_scanner_is_blocked_and_reported_to_directors(presence):
    client = _client()
    assert client.get("/.env").status_code == 404
    assert client.get("/wp-login.php").status_code == 404
    assert client.get("/.git/config").status_code == 403
    blocked = client.get("/", headers={"accept": "text/html"})
    assert blocked.status_code == 403
    assert "temporarily blocked" in blocked.text

    feed = config_app._activity_snapshot()
    assert feed[0]["type"] == "security-alert"
    assert "Auto-blocked testclient" in feed[0]["user"]
    assert config_app.SECURITY_SHIELD.active_blocks()[0]["ip"] == "testclient"


def test_health_check_is_never_limited(presence):
    client = _client()
    for _ in range(3):
        client.get("/.env")
    assert client.get("/health").status_code == 200


def test_signed_in_admins_are_never_blocked(presence):
    client = _client(ADMIN_ID)
    for _ in range(10):
        client.get("/.env")
    assert client.get("/me").status_code == 200


def test_security_headers_include_hsts():
    response = _client().get("/health")
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"


def test_director_can_block_and_unblock_from_security_overview(monkeypatch, presence):
    monkeypatch.setattr(config_app, "save_json", lambda *_args, **_kwargs: None)

    async def fake_director(_request):
        return {"id": config_app.OWNER_USER_ID, "username": "Director"}, None

    monkeypatch.setattr(config_app, "_require_director", fake_director)
    client = _client()

    response = client.post(
        "/director/security/block",
        data={"ip": "198.51.100.23", "duration": "3600", "reason": "Credential stuffing"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/director/security-overview")
    assert "Automated Defences" in page.text
    assert "198.51.100.23" in page.text
    assert "Credential stuffing" in page.text
    assert "Blocked 198.51.100.23 for 1 hour." in page.text

    response = client.post("/director/security/unblock", data={"ip": "198.51.100.23"}, follow_redirects=False)
    assert response.status_code == 303
    assert config_app.SECURITY_SHIELD.active_blocks() == []

    client.post("/director/security/block", data={"ip": "10.0.0.4"}, follow_redirects=False)
    assert "cannot be blocked" in client.get("/director/security-overview").text


def test_block_routes_require_the_director(presence):
    response = _client(ADMIN_ID).post("/director/security/block", data={"ip": "198.51.100.23"})
    assert response.status_code == 403
    assert config_app.SECURITY_SHIELD.active_blocks() == []


def test_removed_admin_token_stops_working(monkeypatch, presence):
    monkeypatch.setattr(config_app, "_session_user_is_admin", lambda _request: True)
    client = _client(ADMIN_ID)
    token = client.get("/api/auth/token").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    beat = {"id": ADMIN_ID}
    assert client.post("/api/admin/heartbeat", json=beat, headers=headers).status_code == 200

    monkeypatch.setattr(config_app, "_user_is_portal_admin", lambda _candidate: False)
    assert client.post("/api/admin/heartbeat", json=beat, headers=headers).status_code == 403
    assert client.get("/api/moderation/actions", headers=headers).status_code == 403


def test_alice_site_wide_budget_raises_an_alert(monkeypatch, presence):
    monkeypatch.setattr(config_app.llm_client, "run_assistant", lambda message: f"echo: {message}")
    monkeypatch.setattr(
        config_app, "_ALICE_DAILY_SITE_WIDE", config_app._SlidingWindowRateLimiter(limit=1, window_seconds=86400)
    )
    monkeypatch.setattr(config_app, "_ALICE_BUDGET_ALERTED_AT", None)
    client = _client("777")
    assert client.post("/api/alice/command", json={"message": "status"}).json() == {"reply": "echo: status"}
    response = client.post("/api/alice/command", json={"message": "status"})
    assert response.status_code == 429
    assert config_app.SECURITY_SHIELD.recent_events()[0]["kind"] == "llm-budget"


# ----------------------------------------------------------------- presence


def test_admin_is_online_from_any_page(presence):
    assert _client().get("/api/admins/presence").json() == []

    _client(ADMIN_ID).get("/me")

    rows = _client().get("/api/admins/presence").json()
    assert rows == [{"id": ADMIN_ID, "status": "Online", "lastActive": "Recently"}]
    assert [entry["type"] for entry in config_app._activity_snapshot()] == ["online"]


def test_regular_members_are_not_tracked(presence):
    _client("777").get("/me")
    assert _client().get("/api/admins/presence").json() == []


def test_presence_ping(presence):
    assert _client(ADMIN_ID).post("/api/presence/ping").status_code == 204
    assert _client("777").post("/api/presence/ping").status_code == 403
    assert _client().post("/api/presence/ping").status_code == 403
    assert _client().get("/api/admins/presence").json()[0]["status"] == "Online"


def test_public_presence_hides_details_and_former_admins(presence):
    config_app._record_admin_heartbeat(ADMIN_ID, name="Ada", role="Director", clearance="Omega-9", ip="203.0.113.8")
    config_app._record_admin_heartbeat("99", name="Former", ip="203.0.113.9")
    rows = _client().get("/api/admins/presence").json()
    assert rows == [{"id": ADMIN_ID, "status": "Online", "lastActive": "Recently"}]


def _contact_page_fakes(monkeypatch):
    owner_settings, _etag = config_app.load_owner_settings()
    owner_settings = owner_settings.copy()
    owner_settings.managers = [ADMIN_ID]
    monkeypatch.setattr(config_app, "load_owner_settings", lambda *a, **k: (owner_settings, "etag"))
    monkeypatch.setattr(config_app, "load_admin_bios", lambda: {})

    async def roster(*_args, **_kwargs):
        return [
            {
                "id": ADMIN_ID,
                "name": "Ada",
                "username": "ada",
                "role": "System Overseer",
                "avatar": None,
                "initials": "A",
                "bio": "",
                "profile_url": "https://discord.com/users/42",
                "can_edit": False,
                "has_bio": False,
                "clearance": "Omega-9",
            }
        ]

    monkeypatch.setattr(config_app, "_build_admin_roster_entries", roster)


def test_contact_page_shows_online_admin_to_guests(monkeypatch, presence):
    _contact_page_fakes(monkeypatch)
    page = _client().get("/admin-team")
    assert page.status_code == 200
    assert ">Offline</span>" in page.text
    assert "admin_presence.js" not in page.text

    config_app._record_admin_heartbeat(ADMIN_ID, name="Ada", ip="203.0.113.8")
    page = _client().get("/admin-team")
    assert 'badge js-admin-status badge--online" data-admin-id="42">Online</span>' in page.text


def test_admin_pages_carry_the_presence_keepalive(monkeypatch, presence):
    _contact_page_fakes(monkeypatch)
    page = _client(ADMIN_ID).get("/admin-team")
    assert page.status_code == 200
    assert "/static/js/admin_presence.js" in page.text


# ---------------------------------------------------------------- passwords


def test_operator_passwords_use_bcrypt_and_upgrade_legacy_hashes(monkeypatch):
    import operator_login

    monkeypatch.setattr(operator_login, "_save", lambda: None)
    monkeypatch.setattr(operator_login, "_operators", {})

    operator_login.set_password(1, "correct horse battery staple")
    stored = operator_login.get_or_create_operator(1).password_hash
    assert stored.startswith("bcrypt-sha256$")
    assert operator_login.verify_password(1, "correct horse battery staple") == (True, False)
    assert operator_login.verify_password(1, "wrong") == (False, False)

    legacy = operator_login.get_or_create_operator(2)
    legacy.password_hash = hashlib.sha256(b"old-password").hexdigest()
    assert operator_login.verify_password(2, "old-password") == (True, False)
    assert legacy.password_hash.startswith("bcrypt-sha256$")
    assert operator_login.verify_password(2, "old-password") == (True, False)


def test_discord_alert_cannot_be_used_to_ping_or_link(monkeypatch):
    import asyncio
    import functools

    import httpx

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(204)

    monkeypatch.setattr(config_app, "_SECURITY_ALERT_WEBHOOK_URL", "https://discord.test/api/webhooks/1/x")
    monkeypatch.setattr(config_app, "_SECURITY_ALERT_MENTION", "<@&555>")
    monkeypatch.setattr(
        config_app.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))
    )
    event = {
        "summary": "Auto-blocked 203.0.113.5: probing (last: /<@&999>/`[x](https://evil.example)`)",
        "severity": "critical",
    }
    asyncio.run(config_app._send_security_alert(event))

    payload = sent[0]
    assert payload["allowed_mentions"] == {"parse": [], "roles": ["555"], "users": []}
    assert payload["content"].startswith("<@&555> ")
    # The attacker's text sits inside one code span with its backticks neutralised.
    assert payload["content"].count("`") == 2
