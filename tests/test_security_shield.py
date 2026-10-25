from __future__ import annotations

import dataclasses

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import security_shield
from security_shield import ClientIpResolver, SecurityShield, ShieldMiddleware, ShieldSettings


# conftest stubs out block persistence for every test; this module tests it.
_real_ensure_loaded = SecurityShield.ensure_loaded
_real_flush = SecurityShield.flush


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class MemoryStore:
    def __init__(self, payload=None) -> None:
        self.payload = payload
        self.saves: list[dict] = []

    def load(self):
        if self.payload is None:
            raise FileNotFoundError("security-blocks.json")
        return self.payload

    def save(self, payload) -> None:
        self.saves.append(payload)
        self.payload = payload


def _shield(clock=None, alerts=None, store=None, **overrides) -> SecurityShield:
    defaults = {
        "requests_per_minute": 10,
        "writes_per_minute": 4,
        "assets_per_minute": 20,
        "credential_failures": 5,
        "not_found": 6,
        "probes": 3,
        "surge_requests_per_minute": 10_000,
    }
    settings = dataclasses.replace(ShieldSettings(), **{**defaults, **overrides})
    return SecurityShield(
        settings,
        resolver=ClientIpResolver(),
        store=store,
        on_alert=alerts.append if alerts is not None else None,
        clock=clock or FakeClock(),
    )


# ---------------------------------------------------------------- client IPs


def test_spoofed_forwarded_for_entries_are_ignored():
    resolver = ClientIpResolver()
    # The client claims to be 1.1.1.1; the platform proxy appended the real address.
    assert resolver.resolve(["1.1.1.1", " 198.51.100.7"], peer="10.0.0.2") == "198.51.100.7"


def test_cloudflare_hop_vouches_for_cf_connecting_ip():
    resolver = ClientIpResolver()
    chain = ["6.6.6.6", "198.51.100.7", "172.70.1.1"]  # last hop is a Cloudflare edge
    assert resolver.resolve(chain, peer="10.0.0.2", cloudflare="198.51.100.7") == "198.51.100.7"
    # Platform proxy that replaces the header with the Cloudflare edge address.
    assert resolver.resolve(["172.70.1.1"], cloudflare="203.0.113.50") == "203.0.113.50"


def test_fake_cloudflare_header_from_direct_attacker_is_ignored():
    resolver = ClientIpResolver()
    chain = ["104.16.0.1", "203.0.113.66"]  # attacker forged a Cloudflare hop; proxy appended the truth
    assert resolver.resolve(chain, cloudflare="9.9.9.9") == "203.0.113.66"


def test_resolver_falls_back_sensibly():
    resolver = ClientIpResolver()
    assert resolver.resolve([], peer="testclient") == "testclient"
    assert resolver.resolve([], peer=None) == "unknown"
    assert resolver.resolve(["10.0.0.5", "10.0.0.6"]) == "10.0.0.5"
    assert resolver.resolve(["garbage", "[2001:db8::1]:443"]) == "2001:db8::1"
    assert resolver.resolve(["::ffff:198.51.100.9"]) == "198.51.100.9"


def test_resolver_honours_configured_header_and_extra_proxies():
    resolver = ClientIpResolver(header="X-Real-IP", trusted_networks=["198.51.100.0/24"])
    assert resolver.resolve(["1.1.1.1"], custom="203.0.113.9") == "203.0.113.9"
    assert resolver.resolve(["203.0.113.4", "198.51.100.7"]) == "203.0.113.4"


# ------------------------------------------------------------------- limits


def test_soft_limit_throttles_and_hard_limit_blocks():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts)
    verdicts = [shield.check("203.0.113.5", path="/dashboard").action for _ in range(10)]
    assert verdicts == ["allow"] * 10

    assert shield.check("203.0.113.5", path="/dashboard").action == "throttle"
    assert alerts == []  # throttling alone is logged, not alerted

    actions = [shield.check("203.0.113.5", path="/dashboard").action for _ in range(10)]
    assert actions[-1] == "block"
    assert alerts and alerts[-1]["kind"] == "blocked"
    assert "203.0.113.5" in alerts[-1]["summary"]
    # Other visitors are unaffected.
    assert shield.check("203.0.113.99", path="/dashboard").action == "allow"


def test_writes_have_their_own_tighter_budget():
    shield = _shield()
    actions = [shield.check("203.0.113.5", method="POST", path="/api/x").action for _ in range(5)]
    assert actions == ["allow"] * 4 + ["throttle"]


def test_static_assets_use_the_larger_budget():
    shield = _shield()
    actions = [shield.check("203.0.113.5", path="/static/app.js").action for _ in range(20)]
    assert set(actions) == {"allow"}
    assert shield.check("203.0.113.5", path="/dashboard").action == "allow"


def test_blocks_expire_and_escalate():
    clock = FakeClock()
    shield = _shield(clock=clock)
    durations = []
    for _ in range(4):
        for _ in range(3):
            shield.check("203.0.113.5", path="/.env")
        verdict = shield.check("203.0.113.5", path="/")
        assert verdict.action == "block"
        durations.append(verdict.retry_after)
        clock.advance(verdict.retry_after + 1)
        assert shield.check("203.0.113.5", path="/").action == "allow"
    assert durations == [900, 3600, 86400, 86400]


def test_probe_paths_are_refused_then_blocked():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts)
    assert shield.check("203.0.113.5", path="/wp-login.php").action == "probe"
    assert shield.check("203.0.113.5", path="/.git/config").action == "probe"
    assert shield.check("203.0.113.5", path="/.env").action == "block"
    assert "exploit paths" in alerts[-1]["summary"]


def test_scrambled_public_path_is_checked_for_probes():
    shield = _shield()
    for _ in range(2):
        assert shield.check("203.0.113.5", path="/.scrambled-not-found", raw_path="/.env").action == "probe"


def test_not_found_scanning_and_failed_logins_block():
    shield = _shield()
    for _ in range(6):
        shield.note_response("203.0.113.5", 404)
    assert shield.check("203.0.113.5", path="/").action == "block"

    for _ in range(4):
        shield.note_response("203.0.113.6", 401, had_credentials=True)
    # Anonymous 401s (a page polling before sign-in) never count.
    for _ in range(20):
        shield.note_response("203.0.113.6", 401, had_credentials=False)
    assert shield.check("203.0.113.6", path="/").action == "allow"
    shield.note_response("203.0.113.6", 403, had_credentials=True)
    assert shield.check("203.0.113.6", path="/").action == "block"


def test_auto_block_off_still_raises_the_alarm():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts, auto_block=False)
    actions = [shield.check("203.0.113.5", path="/.env").action for _ in range(3)]
    assert actions == ["probe", "probe", "throttle"]
    assert alerts[-1]["kind"] == "would-block"
    assert shield.active_blocks() == []


def test_internal_unknown_and_allowlisted_addresses_are_never_limited():
    shield = _shield(allowlist=("198.51.100.0/24",))
    for ip in ("10.1.2.3", "unknown", "198.51.100.20"):
        actions = {shield.check(ip, path="/.env").action for _ in range(50)}
        assert actions == {"allow"}, ip
    with pytest.raises(ValueError):
        shield.block_ip("10.1.2.3", seconds=3600, reason="no")


def test_alert_flood_is_held_back_and_summarised():
    alerts: list[dict] = []
    clock = FakeClock()
    shield = _shield(alerts=alerts, clock=clock)
    for index in range(25):
        ip = f"203.0.113.{index + 1}"
        for _ in range(3):
            shield.check(ip, path="/.env")
    assert len(alerts) == 10
    clock.advance(301)
    shield.check("198.51.100.1", path="/")  # periodic sweep reports what was held back
    assert "held back" in alerts[-1]["summary"]
    assert len(shield.active_blocks()) == 25


def test_site_wide_surge_and_spread_alerts():
    alerts: list[dict] = []
    clock = FakeClock()
    shield = _shield(alerts=alerts, clock=clock, surge_requests_per_minute=100, surge_throttled_ips=3)
    for index in range(100):
        shield.check(f"198.51.100.{index % 50 + 1}", path="/")
    assert any(alert["kind"] == "surge" for alert in alerts)

    for index in range(3):
        for _ in range(11):
            shield.check(f"203.0.113.{index + 1}", path="/")
    clock.advance(31)
    shield.check("198.51.100.200", path="/")
    assert any(alert["kind"] == "distributed" for alert in alerts)


def test_blocks_survive_a_restart():
    store = MemoryStore()
    clock = FakeClock()
    shield = _shield(clock=clock, store=store)
    _real_ensure_loaded(shield)
    shield.block_ip("203.0.113.5", seconds=3600, reason="Spam bot", actor="Director")
    _real_flush(shield)
    assert store.saves and store.saves[-1]["blocks"][0]["ip"] == "203.0.113.5"

    restarted = _shield(clock=clock, store=store)
    _real_ensure_loaded(restarted)
    verdict = restarted.check("203.0.113.5", path="/")
    assert verdict.action == "block"
    assert restarted.active_blocks()[0]["reason"] == "Spam bot"

    assert restarted.unblock_ip("203.0.113.5", actor="Director") is True
    assert restarted.check("203.0.113.5", path="/").action == "allow"
    assert restarted.unblock_ip("203.0.113.5") is False


def test_manual_block_validates_address():
    shield = _shield()
    with pytest.raises(ValueError):
        shield.block_ip("not-an-ip", seconds=60, reason="x")
    block = shield.block_ip(" 2001:db8::5 ", seconds=60, reason="")
    assert block.ip == "2001:db8::5"
    assert block.reason == "Blocked by a director"


def test_probe_detector_leaves_real_paths_alone():
    for path in ("/", "/dashboard", "/static/admin/console.js", "/media/wasp/track.mp3", "/api/admins/presence",
                 "/director/security-overview", "/branding/wallpapers/manifest", "/.well-known/acme-challenge/x"):
        assert not security_shield.is_probe_path(path), path
    for path in ("/.env", "/app/.env.production", "/wp-admin/", "/index.php", "/cgi-bin/luci", "/../etc/passwd",
                 "/.git/HEAD", "/actuator/env", "/backup.sql", "/x%00.html"):
        assert security_shield.is_probe_path(path), path


# --------------------------------------------------------------- middleware


def _app(shield: SecurityShield, *, trusted=None, origins=()):
    async def page(request: Request):
        return PlainTextResponse("ok")

    async def upload(request: Request):
        body = await request.body()
        return JSONResponse({"size": len(body)})

    async def denied(request: Request):
        return PlainTextResponse("no", status_code=401)

    app = Starlette(
        routes=[
            Route("/", page),
            Route("/health", page),
            Route("/upload", upload, methods=["POST"]),
            Route("/denied", denied),
        ]
    )
    app.add_middleware(
        ShieldMiddleware, shield=shield, trusted_session=trusted, trusted_origins=list(origins)
    )
    return app


def test_middleware_throttles_with_retry_after_and_blocks():
    shield = _shield()
    client = TestClient(_app(shield))
    for _ in range(10):
        assert client.get("/").status_code == 200
    throttled = client.get("/", headers={"accept": "application/json"})
    assert throttled.status_code == 429
    assert throttled.headers["retry-after"] == "60"
    assert throttled.json()["error"] == "Too many requests"
    for _ in range(10):
        response = client.get("/", headers={"accept": "text/html"})
    assert response.status_code == 403
    assert "temporarily blocked" in response.text
    assert int(response.headers["retry-after"]) > 0
    # Health checks from the platform are never limited.
    assert client.get("/health").status_code == 200


def test_middleware_counts_404s_and_refuses_probes():
    shield = _shield()
    client = TestClient(_app(shield))
    assert client.get("/wp-login.php").status_code == 404
    for _ in range(6):
        client.get("/nothing-here")
    assert client.get("/").status_code == 403


def test_middleware_counts_failed_credentials():
    shield = _shield()
    client = TestClient(_app(shield))
    for _ in range(5):
        assert client.get("/denied", headers={"authorization": "Basic Zm9vOmJhcg=="}).status_code == 401
    assert client.get("/").status_code == 403


def test_trusted_sessions_are_never_limited():
    shield = _shield()
    client = TestClient(_app(shield, trusted=lambda scope: True))
    assert {client.get("/.env").status_code for _ in range(40)} == {404}
    assert client.get("/").status_code == 200


def test_body_size_limits():
    shield = _shield(max_body_bytes=100, max_upload_bytes=1000)
    client = TestClient(_app(shield))
    assert client.post("/upload", content=b"x" * 100).json() == {"size": 100}
    assert client.post("/upload", content=b"x" * 101).status_code == 413

    def chunks():
        for _ in range(5):
            yield b"x" * 50

    # No Content-Length: the stream is cut off once it passes the limit.
    assert client.post("/upload", content=chunks()).status_code == 413
    files = {"file": ("a.bin", b"x" * 500)}
    assert client.post("/upload", files=files).status_code == 200


def test_cross_site_writes_are_refused():
    shield = _shield()
    client = TestClient(_app(shield, origins=["https://panel.example.com"]))
    cross = {"sec-fetch-site": "cross-site", "origin": "https://evil.example"}
    assert client.post("/upload", content=b"x", headers=cross).status_code == 403
    assert client.post("/upload", content=b"x", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    trusted = {"sec-fetch-site": "cross-site", "origin": "https://panel.example.com"}
    assert client.post("/upload", content=b"x", headers=trusted).status_code == 200
    # Cross-site navigation (GET) is how links work and stays allowed.
    assert client.get("/", headers={"sec-fetch-site": "cross-site"}).status_code == 200


def test_disabled_shield_passes_everything_through():
    shield = _shield(enabled=False)
    client = TestClient(_app(shield))
    assert {client.get("/").status_code for _ in range(50)} == {200}
