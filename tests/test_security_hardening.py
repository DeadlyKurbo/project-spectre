from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import config_app


@pytest.mark.parametrize(
    "target",
    [
        "//evil.example",
        "/\\evil.example",
        "/\\/evil.example",
        "https://evil.example/",
        "evil.example",
        "/ok\r\nSet-Cookie: x=1",
    ],
)
def test_unsafe_redirect_targets_are_rejected(target):
    assert not config_app._is_safe_redirect(target)
    assert config_app._clean_redirect_target(target) == "/dashboard"


@pytest.mark.parametrize("target", ["/", "/dashboard", "/alice?tab=chat", "/server/123"])
def test_local_redirect_targets_are_allowed(target):
    assert config_app._clean_redirect_target(target) == target


def test_empty_basic_auth_does_not_unlock_portal_admin_when_unconfigured(monkeypatch):
    monkeypatch.setattr(config_app, "ADMIN_USER", "")
    monkeypatch.setattr(config_app, "ADMIN_PASS", "")
    monkeypatch.setattr(config_app, "_session_user_is_admin", lambda _request: False)
    client = TestClient(config_app.app, base_url="https://testserver")

    empty_creds = base64.b64encode(b":").decode()
    response = client.get(
        "/admin/definitions",
        headers={"Authorization": f"Basic {empty_creds}"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_oauth_callback_does_not_leak_exception_details(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("client_secret=hunter2")

    monkeypatch.setattr(config_app.oauth, "fetch_token", _boom)
    client = TestClient(config_app.app, base_url="https://testserver")
    location = client.get("/login", follow_redirects=False).headers["location"]
    state = dict(part.partition("=")[::2] for part in location.split("?", 1)[1].split("&"))["state"]
    response = client.get(f"/auth/callback?code=abc&state={state}")

    assert response.status_code == 500
    assert "hunter2" not in response.text


def test_alice_command_is_rate_limited(monkeypatch):
    monkeypatch.setattr(
        config_app,
        "_ALICE_COMMAND_LIMITER",
        config_app._SlidingWindowRateLimiter(limit=2, window_seconds=60.0),
    )
    monkeypatch.setattr(config_app.llm_client, "run_assistant", lambda message: f"echo {message}")
    monkeypatch.setattr(config_app, "ADMIN_USER", "ops")
    monkeypatch.setattr(config_app, "ADMIN_PASS", "secret")
    client = TestClient(config_app.app, base_url="https://testserver")

    statuses = [
        client.post("/api/alice/command", json={"message": "status"}, auth=("ops", "secret")).status_code
        for _ in range(3)
    ]

    assert statuses == [200, 200, 429]


def test_alice_command_rejects_oversized_messages(monkeypatch):
    config_app._ALICE_COMMAND_LIMITER.reset()
    monkeypatch.setattr(config_app.llm_client, "run_assistant", lambda message: "unused")
    monkeypatch.setattr(config_app, "ADMIN_USER", "ops")
    monkeypatch.setattr(config_app, "ADMIN_PASS", "secret")
    client = TestClient(config_app.app, base_url="https://testserver")

    response = client.post(
        "/api/alice/command",
        json={"message": "x" * (config_app._ALICE_COMMAND_MAX_LENGTH + 1)},
        auth=("ops", "secret"),
    )

    assert response.status_code == 400


def _visit_request(ip: str):
    return SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/"),
        headers={"accept": "text/html", "x-forwarded-for": ip, "user-agent": "pytest"},
        client=None,
        session={},
    )


def test_site_visit_tracker_is_bounded(monkeypatch):
    persisted: list[int] = []
    monkeypatch.setattr(config_app, "_SITE_VISIT_LOADED", True)
    monkeypatch.setattr(config_app, "_SITE_VISIT_DAILY", {})
    monkeypatch.setattr(config_app, "_SITE_VISIT_SEEN_KEYS", {})
    monkeypatch.setattr(config_app, "_SITE_VISIT_RECENT", {})
    monkeypatch.setattr(config_app, "_SITE_VISIT_LAST_MAINTENANCE", None)
    monkeypatch.setattr(config_app, "_SITE_VISIT_RECENT_MAX", 5)
    monkeypatch.setattr(config_app, "_persist_site_visit_log", lambda: persisted.append(1))

    for index in range(20):
        config_app._record_site_visit(_visit_request(f"10.0.0.{index}"))

    assert len(config_app._SITE_VISIT_RECENT) == 5
    # Persistence is throttled instead of firing once per new visitor.
    assert len(persisted) == 1
    today = datetime.now(timezone.utc).date().isoformat()
    assert config_app._SITE_VISIT_DAILY[today] == 20

    config_app._SITE_VISIT_LAST_MAINTENANCE = datetime.now(timezone.utc) - timedelta(minutes=5)
    config_app._record_site_visit(_visit_request("10.0.0.1"))
    assert len(persisted) == 2
