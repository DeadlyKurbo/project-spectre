from fastapi.testclient import TestClient
import httpx
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


def test_push_director_broadcast_does_not_dm_for_dashboard_delivery(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    async def fake_require_director(_request):
        return {"id": "1", "username": "Director", "discriminator": "0001"}, None

    monkeypatch.setattr(mod, "_require_director", fake_require_director)
    class _Entry:
        def __init__(self, message, priority, actor):
            self.message = message
            self.priority = priority
            self.actor = actor

        def to_payload(self):
            return {
                "message": self.message,
                "priority": self.priority,
                "actor": self.actor,
                "created_at": "2026-01-01T00:00:00+00:00",
            }

    monkeypatch.setattr(
        mod,
        "record_broadcast",
        lambda message, *, priority, actor: _Entry(message, priority, actor),
    )
    monkeypatch.setattr(mod, "set_operations_broadcast", lambda *a, **k: None)

    async def fail_dispatch(**_kwargs):  # pragma: no cover - should never run
        raise AssertionError("dispatch should not be called for dashboard delivery")

    monkeypatch.setattr(mod, "_dispatch_director_alert_to_server_owners", fail_dispatch)

    response = client.post(
        "/director/broadcasts",
        json={"priority": "standard", "message": "Routine update", "delivery": "dashboard"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery"] == "dashboard"
    assert payload["dispatch"]["attempted"] == 0
    assert payload["dispatch"]["delivered"] == 0


def test_push_director_broadcast_dms_for_discord_alert_delivery(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    async def fake_require_director(_request):
        return {"id": "1", "username": "Director", "discriminator": "0001"}, None

    monkeypatch.setattr(mod, "_require_director", fake_require_director)
    class _Entry:
        def __init__(self, message, priority, actor):
            self.message = message
            self.priority = priority
            self.actor = actor

        def to_payload(self):
            return {
                "message": self.message,
                "priority": self.priority,
                "actor": self.actor,
                "created_at": "2026-01-01T00:00:00+00:00",
            }

    monkeypatch.setattr(
        mod,
        "record_broadcast",
        lambda message, *, priority, actor: _Entry(message, priority, actor),
    )
    monkeypatch.setattr(mod, "set_operations_broadcast", lambda *a, **k: None)

    calls = []

    async def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {"attempted": 2, "delivered": 2, "failed": []}

    monkeypatch.setattr(mod, "_dispatch_director_alert_to_server_owners", fake_dispatch)

    response = client.post(
        "/director/broadcasts",
        json={"priority": "emergency", "message": "Immediate action", "delivery": "discord-alert"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery"] == "discord-alert"
    assert payload["dispatch"]["delivered"] == 2
    assert len(calls) == 1


def test_director_form_only_offers_priorities_the_server_accepts(monkeypatch):
    # The form used to send "operational", which the endpoint rejected with a 400.
    import re
    from pathlib import Path

    from owner_portal import BROADCAST_PRIORITIES

    template = Path(__file__).resolve().parents[1] / "templates" / "director.html"
    select = re.search(
        r'<select id="priority".*?</select>', template.read_text(), flags=re.DOTALL
    ).group(0)
    offered = re.findall(r'<option value="([^"]+)"', select)

    assert offered
    assert set(offered) <= BROADCAST_PRIORITIES


class _FakeDiscordClient:
    """Stand-in for ``httpx.AsyncClient`` that replays canned responses."""

    def __init__(self, responses, calls):
        self._responses = responses
        self._calls = calls

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def _reply(self, method, url):
        self._calls.append((method, url))
        status_code, payload = self._responses[(method, url.rsplit("/api/v10", 1)[-1])].pop(0)
        return httpx.Response(status_code, json=payload, request=httpx.Request(method, url))

    async def get(self, url, *, headers):
        return await self._reply("GET", url)

    async def post(self, url, *, headers, json):
        return await self._reply("POST", url)


def test_get_bot_guilds_is_cached_and_survives_rate_limits(monkeypatch):
    mod = _load_app(monkeypatch)
    calls = []
    responses = {
        ("GET", "/users/@me/guilds"): [
            (200, [{"id": "101"}]),
            (429, {"retry_after": 30.0, "message": "You are being rate limited."}),
        ]
    }
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeDiscordClient(responses, calls))

    first = mod.asyncio.run(mod.get_bot_guilds())
    second = mod.asyncio.run(mod.get_bot_guilds())
    assert first == second == [{"id": "101"}]
    assert len(calls) == 1

    # Once the cache expires, a 429 serves the last known list instead of failing.
    monkeypatch.setattr(mod, "BOT_GUILDS_CACHE_TTL_SECONDS", 0)
    assert mod.asyncio.run(mod.get_bot_guilds()) == [{"id": "101"}]
    assert len(calls) == 2


def test_dispatch_reports_rate_limited_guild_lookup_instead_of_crashing(monkeypatch):
    mod = _load_app(monkeypatch)
    calls = []
    responses = {
        ("GET", "/users/@me/guilds"): [(429, {"retry_after": 30.0})],
    }
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeDiscordClient(responses, calls))

    result = mod.asyncio.run(
        mod._dispatch_director_alert_to_server_owners(
            message="Check in.", priority="emergency", actor="Director"
        )
    )

    assert result["attempted"] == 0
    assert result["delivered"] == 0
    assert "rate limit" in result["skipped"]


def test_dispatch_waits_out_a_short_rate_limit(monkeypatch):
    mod = _load_app(monkeypatch)
    calls = []
    responses = {
        ("GET", "/users/@me/guilds"): [(200, [{"id": "101"}])],
        ("GET", "/guilds/101"): [(429, {"retry_after": 0.0}), (200, {"owner_id": "9001"})],
        ("POST", "/users/@me/channels"): [(200, {"id": "5551"})],
        ("POST", "/channels/5551/messages"): [(429, {"retry_after": 0.0}), (200, {"id": "1"})],
    }
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeDiscordClient(responses, calls))

    result = mod.asyncio.run(
        mod._dispatch_director_alert_to_server_owners(
            message="Check in.", priority="standard", actor="Director"
        )
    )

    assert result == {"attempted": 1, "delivered": 1, "failed": []}
    assert len(calls) == 6
