import asyncio
import base64
import importlib
import json
import sys

import itsdangerous
from fastapi.testclient import TestClient

from app_spectre.services.moderation_service import InMemoryModerationRepository, ModerationService

ACTOR = {"id": "1059522006602752150", "name": "DK"}


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _client_as(mod, user_id):
    client = TestClient(mod.app, base_url="https://testserver")
    payload = base64.b64encode(json.dumps({"user": {"id": user_id, "username": "member"}}).encode())
    cookie = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET)).sign(payload).decode()
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    return client


def test_website_ban_signs_the_account_out_until_lifted(monkeypatch):
    mod = _load_app(monkeypatch)
    service = ModerationService(InMemoryModerationRepository())
    monkeypatch.setattr(mod, "get_moderation_service", lambda: service)
    monkeypatch.setattr(mod, "_website_blocks_loaded_at", None)

    person = asyncio.run(service.create_subject("Banned member", ACTOR, discord_user_id="424242"))
    ban = asyncio.run(
        service.create_sanction(
            {"subjectId": person["id"], "target": "website", "sanction": "ban", "reason": "Doxxing other members"},
            ACTOR,
        )
    )

    resp = _client_as(mod, "424242").get("/about")
    assert resp.status_code == 403
    assert "Your access has been revoked" in resp.text
    assert "Doxxing other members" in resp.text

    assert _client_as(mod, "999").get("/about").status_code == 200
    assert _client_as(mod, mod.OWNER_USER_KEY).get("/about").status_code == 200

    asyncio.run(service.revoke_sanction(ban["id"], "Appeal approved", ACTOR))
    assert _client_as(mod, "424242").get("/about").status_code == 200
