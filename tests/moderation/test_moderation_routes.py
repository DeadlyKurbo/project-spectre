from __future__ import annotations

import datetime
import importlib
import sys

import jwt
import pytest
from fastapi.testclient import TestClient

from app_spectre.services.moderation_service import InMemoryModerationRepository, ModerationService


@pytest.fixture
def moderation_app(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "moderation-test-secret")
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")

    service = ModerationService(repository=InMemoryModerationRepository())
    mod.app.dependency_overrides.clear()
    from app_spectre.routers.moderation_routes import get_moderation_service

    mod.app.dependency_overrides[get_moderation_service] = lambda: service

    client = TestClient(mod.app)
    yield mod, client
    mod.app.dependency_overrides.clear()


def _token(secret: str, role: str = "Admin", sub: str = "100") -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": sub,
        "name": "Operator",
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_subject_case_sanction_and_appeal_flow(moderation_app):
    mod, client = moderation_app
    token = _token(mod._JWT_SECRET, role="Admin", sub="9001")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/moderation/subjects",
        headers=headers,
        json={"canonicalLabel": "Test User #1"},
    )
    assert response.status_code == 200
    subject = response.json()["subject"]
    subject_id = subject["id"]

    response = client.post(
        f"/api/moderation/subjects/{subject_id}/identities",
        headers=headers,
        json={"provider": "discord", "providerUserId": "1234567890", "displayName": "Discord User"},
    )
    assert response.status_code == 200
    assert response.json()["identity"]["provider"] == "discord"

    response = client.post(
        "/api/moderation/cases",
        headers=headers,
        json={
            "subjectId": subject_id,
            "title": "Unsafe archive upload",
            "description": "User posted suspicious materials.",
            "priority": "high",
        },
    )
    assert response.status_code == 200
    case_id = response.json()["case"]["id"]

    response = client.post(
        "/api/moderation/sanctions",
        headers=headers,
        json={
            "subjectId": subject_id,
            "caseId": case_id,
            "target": "website",
            "sanction": "suspension",
            "reason": "Investigating harmful uploads",
        },
    )
    assert response.status_code == 200
    sanction = response.json()["sanction"]
    assert sanction["status"] == "active"

    response = client.post(
        "/api/moderation/appeals",
        headers=headers,
        json={
            "sanctionId": sanction["id"],
            "caseId": case_id,
            "appealReason": "This was a false positive.",
        },
    )
    assert response.status_code == 200
    appeal_id = response.json()["appeal"]["id"]

    response = client.patch(
        f"/api/moderation/appeals/{appeal_id}",
        headers=headers,
        json={"status": "denied", "decisionSummary": "Evidence confirms violation."},
    )
    assert response.status_code == 200
    assert response.json()["appeal"]["status"] == "denied"

    response = client.get("/api/moderation/audit-events?limit=50", headers=headers)
    assert response.status_code == 200
    events = response.json()["events"]
    assert any(event["eventType"] == "sanction.imposed" for event in events)

    response = client.get("/api/moderation/monitored-guild-owners?limit=20", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json()["owners"], list)


def test_moderation_routes_reject_non_admin_role(moderation_app):
    mod, client = moderation_app
    token = _token(mod._JWT_SECRET, role="Member", sub="5")
    response = client.get("/api/moderation/subjects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_console_endpoints_for_rules_revoke_and_case_status(moderation_app):
    mod, client = moderation_app
    headers = {"Authorization": f"Bearer {_token(mod._JWT_SECRET, role='Admin', sub='9001')}"}

    rules = client.get("/api/moderation/actions", headers=headers).json()
    assert {rule["value"] for rule in rules["actions"]["website"]} == {"warning", "note", "timeout", "suspension", "ban"}
    assert "resolved" in rules["caseStatuses"]

    subject = client.post(
        "/api/moderation/subjects",
        headers=headers,
        json={"canonicalLabel": "Route User", "discordUserId": "1234567890"},
    ).json()["subject"]
    profile = client.get(f"/api/moderation/subjects/{subject['id']}", headers=headers).json()
    assert profile["identities"][0]["providerUserId"] == "1234567890"

    case = client.post(
        "/api/moderation/cases",
        headers=headers,
        json={"subjectId": subject["id"], "title": "Spam wave", "description": "Many links posted."},
    ).json()["case"]
    resp = client.patch(f"/api/moderation/cases/{case['id']}", headers=headers, json={"status": "resolved"})
    assert resp.status_code == 200 and resp.json()["case"]["status"] == "resolved"
    assert client.patch(f"/api/moderation/cases/{case['id']}", headers=headers, json={"status": "bogus"}).status_code == 400
    assert client.patch("/api/moderation/cases/nope", headers=headers, json={"status": "open"}).status_code == 404

    ban = client.post(
        "/api/moderation/sanctions",
        headers=headers,
        json={"subjectId": subject["id"], "target": "website", "sanction": "ban", "reason": "Repeated spam"},
    ).json()["sanction"]
    resp = client.post(f"/api/moderation/sanctions/{ban['id']}/revoke", headers=headers, json={"reason": "Appealed"})
    assert resp.status_code == 200 and resp.json()["sanction"]["status"] == "revoked"
    again = client.post(f"/api/moderation/sanctions/{ban['id']}/revoke", headers=headers, json={"reason": "Twice"})
    assert again.status_code == 400

    bad = client.post(
        "/api/moderation/sanctions",
        headers=headers,
        json={"subjectId": subject["id"], "target": "discord", "sanction": "ban", "reason": "No server picked"},
    )
    assert bad.status_code == 400
    assert "Discord server" in bad.json()["detail"]
