import importlib
import sys


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def test_director_alert_content_truncates_to_discord_limit(monkeypatch):
    mod = _load_app(monkeypatch)

    content = mod._director_alert_content(
        priority="emergency",
        actor="Director Jane",
        message="A" * 5000,
    )

    assert len(content) <= 2000
    assert "SPECTRE DIRECTOR ALERT" in content
    assert "EMERGENCY" in content


def test_dispatch_director_alert_to_server_owners(monkeypatch):
    mod = _load_app(monkeypatch)

    async def fake_get_bot_guilds():
        return [{"id": "101"}, {"id": "202"}, {"id": "303"}]

    class DummyResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._payload

    sent_messages = []

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers):
            if url.endswith("/guilds/101"):
                return DummyResponse({"owner_id": "9001"})
            if url.endswith("/guilds/202"):
                return DummyResponse({"owner_id": "9001"})
            if url.endswith("/guilds/303"):
                return DummyResponse({"owner_id": "9002"})
            raise AssertionError(f"Unexpected URL: {url}")

        async def post(self, url, *, headers, json):
            if url.endswith("/users/@me/channels"):
                return DummyResponse({"id": f"{json['recipient_id']}77"})
            if "/channels/" in url and url.endswith("/messages") and "dm-" not in url:
                sent_messages.append({"url": url, "content": json.get("content")})
                return DummyResponse({"id": "msg-1"})
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(mod, "get_bot_guilds", fake_get_bot_guilds)
    monkeypatch.setattr(mod.httpx, "AsyncClient", DummyAsyncClient)

    result = mod.asyncio.run(
        mod._dispatch_director_alert_to_server_owners(
            message="Server owners check-in.",
            priority="high-priority",
            actor="Director",
        )
    )

    assert result["attempted"] == 2
    assert result["delivered"] == 2
    assert result["failed"] == []
    assert len(sent_messages) == 2
    assert all("SPECTRE DIRECTOR ALERT" in entry["content"] for entry in sent_messages)
