"""Front-door protection for the website: rate limits, automatic IP blocks and alerts.

The limits are generous on purpose. Normal browsing never meets them; they are
there so a flood, a vulnerability scanner or a password-guessing run stands out
at once and is stopped without anyone having to be awake.

Per client IP:

* every request counts towards a per-minute budget (static files have their
  own, larger one) and writes (POST/PUT/PATCH/DELETE) towards a smaller one.
  Past the budget the client is answered ``429 Too Many Requests``; a client
  that ignores that and keeps going to twice the budget is blocked.
* failed logins (401/403 answers to requests that carried credentials), 404s
  and requests for well-known exploit paths (``/.env``, ``/wp-login.php``, ...)
  are counted over ten minutes; too many of any of them blocks the IP.
* blocks last 15 minutes, then 1 hour, then 24 hours for repeat offenders.

Site-wide, a surge of traffic or many IPs being throttled at once raises an
alert even when no single IP crosses a line, which is what a distributed
attack looks like.

Every incident is logged and handed to ``on_alert`` (the app puts it in the
director's activity feed and, when configured, a Discord channel). Blocks are
saved through a :class:`BlockStore` so a redeploy does not let an attacker
straight back in.

Client IPs come from ``X-Forwarded-For`` read right to left, skipping hops that
are our own proxies (private addresses and Cloudflare's published ranges), so
a client cannot dodge its budget, or get someone else blocked, by sending a
made-up header.

Every number can be tuned with ``SECURITY_*`` environment variables; see
``ShieldSettings.from_env`` and ``docs/security-shield.md``.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import os
import re
import threading
import time
import weakref
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NamedTuple, Protocol

from starlette.exceptions import HTTPException

logger = logging.getLogger("security_shield")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Cloudflare's published edge ranges (https://www.cloudflare.com/ips/).
CLOUDFLARE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)
# Where our own proxies (Railway's edge among them) reach the container from:
# RFC 1918, carrier-grade NAT, loopback, link-local and IPv6 unique-local space.
# Spelled out because ``is_private`` also covers documentation and benchmark
# ranges that are not ours.
_INTERNAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "0.0.0.0/8",
        "::1/128",
        "::/128",
        "fc00::/7",
        "fe80::/10",
    )
)

_MINUTE = 60.0
# Offences older than this no longer make the next block longer.
_OFFENCE_MEMORY_SECONDS = 7 * 24 * 3600.0
_SWEEP_INTERVAL_SECONDS = 30.0
_SITE_ALERT_COOLDOWN_SECONDS = 600.0
# At most this many alerts reach ``on_alert`` per window; the rest are counted
# and summarised so a distributed attack cannot flood the alert channel.
_ALERT_BUDGET = 10
_ALERT_BUDGET_WINDOW_SECONDS = 300.0
_MAX_EVENTS = 200

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_ASSET_PREFIXES = ("/static/", "/images/", "/media/", "/branding/", "/favicon.ico")

# Paths only vulnerability scanners ask for: this site has no PHP, WordPress,
# dotfiles or admin panels of other products, so nobody legitimate lands here.
_PROBE_RE = re.compile(
    r"""
      (?:^|/)\.(?:env|git|svn|hg|bzr|aws|ssh|docker|kube|vscode|idea|npmrc|ds_store|htaccess|htpasswd)(?:[./_~-]|$)
    | \.(?:php[0-9]?|phtml|asp|aspx|ashx|jsp|jspx|cgi|sql|bak|old|swp|ini|cfg|conf|log)$
    | (?:^|/)(?:wp-admin|wp-login|wp-content|wp-includes|wp-json|wp-config|wordpress|xmlrpc|phpmyadmin|
              myadmin|phpunit|cgi-bin|boaform|hnap1|actuator|server-status|server-info|jenkins|
              manager/html|telescope|_ignition|containers/json|geoserver|vendor/phpunit|
              id_rsa|id_ed25519|etc/passwd|etc/shadow|win\.ini|web\.config|config\.json|
              credentials|secrets?\.(?:json|ya?ml))(?:[/.]|$)
    | \.\./
    """,
    re.IGNORECASE | re.VERBOSE,
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _printable(text: str, limit: int = 120) -> str:
    """Client-supplied text made safe to quote in logs and alerts."""

    return _CONTROL_CHARS_RE.sub("?", text[:limit])


def is_probe_path(path: str) -> bool:
    """Return ``True`` for paths that only scanners and exploit kits request."""

    if not path:
        return False
    if "\x00" in path or "%00" in path:
        return True
    return _PROBE_RE.search(path.replace("\\", "/")) is not None


def env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError:
        logger.warning("%s=%r is not a number; using %s.", name, raw, default)
        return default
    return max(value, minimum)


def _env_flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_list(name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in (os.getenv(name) or "").split(",") if part.strip())


def parse_ip(value: str | None) -> IPAddress | None:
    """Parse one address as it appears in proxy headers (ports and brackets allowed)."""

    if not value:
        return None
    candidate = str(value).strip().strip('"')
    if candidate.startswith("["):
        candidate = candidate[1:].split("]", 1)[0]
    elif candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_internal_address(address: IPAddress) -> bool:
    """Private, loopback and platform addresses: proxies, never real visitors."""

    return any(address in network for network in _INTERNAL_NETWORKS)


class ClientIpResolver:
    """Work out the real visitor address behind Cloudflare and the platform proxy."""

    def __init__(self, *, header: str | None = None, trusted_networks: Iterable[str] = ()) -> None:
        self.header = (header or "").strip().lower() or None
        extra = []
        for raw in trusted_networks:
            try:
                extra.append(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                logger.warning("Ignoring invalid trusted proxy network %r", raw)
        self._extra_proxies = tuple(extra)

    @classmethod
    def from_env(cls) -> "ClientIpResolver":
        return cls(
            header=os.getenv("SECURITY_CLIENT_IP_HEADER"),
            trusted_networks=_env_list("SECURITY_TRUSTED_PROXIES"),
        )

    def _is_proxy(self, address: IPAddress) -> bool:
        return is_internal_address(address) or any(address in network for network in self._extra_proxies)

    @staticmethod
    def _is_cloudflare(address: IPAddress) -> bool:
        return any(address in network for network in CLOUDFLARE_NETWORKS)

    def resolve(
        self,
        forwarded: Iterable[str],
        *,
        peer: str | None = None,
        cloudflare: str | None = None,
        custom: str | None = None,
    ) -> str:
        if self.header:
            address = parse_ip(custom)
            if address is not None:
                return str(address)

        hops = [address for address in (parse_ip(entry) for entry in forwarded) if address is not None]
        # Each proxy appends the address it saw, so the right end of the chain is
        # what our own infrastructure recorded and the left end is whatever the
        # client chose to send. Walk in from the right past our own proxies.
        for address in reversed(hops):
            if self._is_cloudflare(address):
                vouched = parse_ip(cloudflare)
                if vouched is not None:
                    return str(vouched)
                continue
            if not self._is_proxy(address):
                return str(address)
        if hops:
            return str(hops[0])
        peer_address = parse_ip(peer)
        if peer_address is not None:
            return str(peer_address)
        return str(peer or "unknown")

    def from_scope(self, scope: Mapping[str, Any]) -> str:
        forwarded: list[str] = []
        cloudflare = custom = None
        for key, value in scope.get("headers") or ():
            name = key.decode("latin-1").lower()
            if name == "x-forwarded-for":
                forwarded.extend(value.decode("latin-1").split(","))
            elif name == "cf-connecting-ip":
                cloudflare = value.decode("latin-1")
            if self.header and name == self.header:
                custom = value.decode("latin-1")
        client = scope.get("client")
        peer = client[0] if client else None
        return self.resolve(forwarded, peer=peer, cloudflare=cloudflare, custom=custom)


@dataclass(frozen=True)
class ShieldSettings:
    enabled: bool = True
    auto_block: bool = True
    requests_per_minute: int = 600
    writes_per_minute: int = 120
    assets_per_minute: int = 2400
    # A client still sending this many times its budget after being told to
    # slow down is not a browser: block it.
    hard_limit_factor: float = 2.0
    review_window_seconds: float = 600.0
    credential_failures: int = 30
    not_found: int = 200
    probes: int = 3
    block_seconds: tuple[int, ...] = (15 * 60, 60 * 60, 24 * 60 * 60)
    surge_requests_per_minute: int = 6000
    surge_throttled_ips: int = 20
    max_body_bytes: int = 8 * 1024 * 1024
    max_upload_bytes: int = 30 * 1024 * 1024
    allowlist: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "ShieldSettings":
        return cls(
            enabled=_env_flag("SECURITY_SHIELD", True),
            auto_block=_env_flag("SECURITY_AUTO_BLOCK", True),
            requests_per_minute=env_int("SECURITY_REQUESTS_PER_MINUTE", cls.requests_per_minute, minimum=10),
            writes_per_minute=env_int("SECURITY_WRITES_PER_MINUTE", cls.writes_per_minute, minimum=5),
            assets_per_minute=env_int("SECURITY_ASSETS_PER_MINUTE", cls.assets_per_minute, minimum=10),
            credential_failures=env_int("SECURITY_FAILED_LOGIN_LIMIT", cls.credential_failures, minimum=3),
            not_found=env_int("SECURITY_NOT_FOUND_LIMIT", cls.not_found, minimum=10),
            probes=env_int("SECURITY_PROBE_LIMIT", cls.probes, minimum=1),
            surge_requests_per_minute=env_int(
                "SECURITY_SURGE_ALERT_PER_MINUTE", cls.surge_requests_per_minute, minimum=100
            ),
            surge_throttled_ips=env_int("SECURITY_SURGE_ALERT_IPS", cls.surge_throttled_ips, minimum=2),
            max_body_bytes=env_int("SECURITY_MAX_BODY_MB", 8, minimum=1) * 1024 * 1024,
            max_upload_bytes=env_int("SECURITY_MAX_UPLOAD_MB", 30, minimum=1) * 1024 * 1024,
            allowlist=_env_list("SECURITY_ALLOWLIST"),
        )


class _SlidingCount:
    """Events in the last ``window`` seconds, estimated from two fixed buckets.

    Constant memory per counter, which matters when an attack spreads across
    thousands of addresses.
    """

    __slots__ = ("window", "bucket", "current", "previous")

    def __init__(self, window: float) -> None:
        self.window = window
        self.bucket = 0
        self.current = 0
        self.previous = 0

    def _roll(self, now: float) -> None:
        bucket = int(now // self.window)
        if bucket != self.bucket:
            self.previous = self.current if bucket == self.bucket + 1 else 0
            self.current = 0
            self.bucket = bucket

    def add(self, now: float) -> float:
        self._roll(now)
        self.current += 1
        return self.estimate(now)

    def estimate(self, now: float) -> float:
        self._roll(now)
        elapsed = (now % self.window) / self.window
        return self.previous * (1.0 - elapsed) + self.current


class _Visitor:
    __slots__ = ("requests", "writes", "assets", "failures", "misses", "probes", "last_seen", "throttle_logged_at")

    def __init__(self, review_window: float) -> None:
        self.requests = _SlidingCount(_MINUTE)
        self.writes = _SlidingCount(_MINUTE)
        self.assets = _SlidingCount(_MINUTE)
        self.failures = _SlidingCount(review_window)
        self.misses = _SlidingCount(review_window)
        self.probes = _SlidingCount(review_window)
        self.last_seen = 0.0
        self.throttle_logged_at = 0.0


@dataclass
class Block:
    ip: str
    until: float
    reason: str
    created: float
    offences: int = 1
    manual: bool = False
    actor: str | None = None
    hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "until": self.until,
            "reason": self.reason,
            "created": self.created,
            "offences": self.offences,
            "manual": self.manual,
            "actor": self.actor,
            "hits": self.hits,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Block | None":
        if not isinstance(raw, Mapping):
            return None
        ip = str(raw.get("ip") or "").strip()
        try:
            until = float(raw.get("until"))
            created = float(raw.get("created") or until)
            offences = int(raw.get("offences") or 1)
            hits = int(raw.get("hits") or 0)
        except (TypeError, ValueError):
            return None
        if not ip:
            return None
        actor = raw.get("actor")
        return cls(
            ip=ip,
            until=until,
            reason=str(raw.get("reason") or "Blocked")[:300],
            created=created,
            offences=max(offences, 1),
            manual=bool(raw.get("manual")),
            actor=str(actor)[:120] if actor else None,
            hits=max(hits, 0),
        )


class Verdict(NamedTuple):
    action: str  # "allow", "throttle", "block" or "probe"
    retry_after: int = 0
    reason: str = ""


_ALLOW = Verdict("allow")


class BlockStore(Protocol):
    def load(self) -> Any: ...

    def save(self, payload: dict[str, Any]) -> None: ...


@dataclass
class CallbackBlockStore:
    """Persist blocks through plain ``load()`` / ``save(payload)`` callables."""

    loader: Callable[[], Any]
    saver: Callable[[dict[str, Any]], None]

    def load(self) -> Any:
        return self.loader()

    def save(self, payload: dict[str, Any]) -> None:
        self.saver(payload)


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _describe_duration(seconds: float) -> str:
    seconds = max(int(round(seconds)), 0)
    if seconds >= 86400 and seconds % 86400 == 0:
        amount, unit = seconds // 86400, "day"
    elif seconds >= 3600 and seconds % 3600 == 0:
        amount, unit = seconds // 3600, "hour"
    elif seconds >= 60:
        amount, unit = max(seconds // 60, 1), "minute"
    else:
        amount, unit = seconds, "second"
    return f"{amount} {unit}{'' if amount == 1 else 's'}"


_INSTANCES: "weakref.WeakSet[SecurityShield]" = weakref.WeakSet()


def all_shields() -> list["SecurityShield"]:
    """Every live shield; tests reset them all, since apps get re-imported."""

    return list(_INSTANCES)


class SecurityShield:
    """Per-IP request accounting, automatic blocks and the incident log."""

    def __init__(
        self,
        settings: ShieldSettings | None = None,
        *,
        resolver: ClientIpResolver | None = None,
        store: BlockStore | None = None,
        on_alert: Callable[[dict[str, Any]], None] | None = None,
        asset_prefixes: Iterable[str] = DEFAULT_ASSET_PREFIXES,
        clock: Callable[[], float] = time.time,
        max_tracked_ips: int = 100_000,
    ) -> None:
        self.settings = settings or ShieldSettings.from_env()
        self.resolver = resolver or ClientIpResolver.from_env()
        self.on_alert = on_alert
        self._store = store
        self._clock = clock
        self._asset_prefixes = tuple(asset_prefixes)
        self._max_tracked_ips = max(int(max_tracked_ips), 100)
        self._allowlist = self._parse_allowlist(self.settings.allowlist)
        self._lock = threading.RLock()
        self._visitors: OrderedDict[str, _Visitor] = OrderedDict()
        self._blocks: dict[str, Block] = {}
        self._offences: dict[str, tuple[int, float]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
        self._site_requests = _SlidingCount(_MINUTE)
        self._throttled_ips: dict[str, float] = {}
        self._last_surge_alert = float("-inf")
        self._last_spread_alert = float("-inf")
        self._alert_times: deque[float] = deque()
        self._suppressed_alerts = 0
        self._last_sweep = 0.0
        self._warned_internal = False
        self._loaded = store is None
        self._dirty = False
        self._flush_task: asyncio.Task | None = None
        _INSTANCES.add(self)

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _parse_allowlist(entries: Iterable[str]):
        networks = []
        for raw in entries:
            try:
                networks.append(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                logger.warning("Ignoring invalid SECURITY_ALLOWLIST entry %r", raw)
        return tuple(networks)

    def reset(self) -> None:
        """Forget all counters, blocks and events without touching saved blocks (tests)."""

        with self._lock:
            self._visitors.clear()
            self._blocks.clear()
            self._offences.clear()
            self._events.clear()
            self._site_requests = _SlidingCount(_MINUTE)
            self._throttled_ips.clear()
            self._last_surge_alert = float("-inf")
            self._last_spread_alert = float("-inf")
            self._alert_times.clear()
            self._suppressed_alerts = 0
            self._dirty = False
            self._loaded = True

    def ensure_loaded(self) -> None:
        """Restore saved blocks once per process. Blocking; call off the event loop."""

        if self._loaded:
            return
        try:
            payload = self._store.load() if self._store is not None else None
        except FileNotFoundError:
            payload = None
        except Exception:
            logger.exception("Failed to load saved IP blocks; starting with none")
            payload = None
        now = self._clock()
        entries = payload.get("blocks") if isinstance(payload, Mapping) else None
        with self._lock:
            for raw in entries or ():
                block = Block.from_dict(raw)
                if block is None:
                    continue
                if block.until > now:
                    self._blocks.setdefault(block.ip, block)
                if not block.manual and now - block.created < _OFFENCE_MEMORY_SECONDS:
                    self._offences[block.ip] = (block.offences, block.created)
            self._loaded = True

    async def ensure_loaded_async(self) -> None:
        # Two requests racing here both load; restoring blocks is idempotent.
        if not self._loaded:
            await asyncio.get_running_loop().run_in_executor(None, self.ensure_loaded)

    def schedule_flush(self) -> None:
        """Save blocks in the background if they changed. Call from the event loop."""

        if not self._dirty or self._store is None:
            return
        if self._flush_task is not None and not self._flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush()
            return
        self._flush_task = loop.create_task(self._flush_async())

    async def _flush_async(self) -> None:
        loop = asyncio.get_running_loop()
        while self._dirty:
            await loop.run_in_executor(None, self.flush)

    def flush(self) -> None:
        if self._store is None:
            return
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            now = self._clock()
            payload = {
                "blocks": [block.to_dict() for block in self._blocks.values() if block.until > now],
                "updated_at": _iso(now),
            }
        try:
            self._store.save(payload)
        except Exception:
            logger.exception("Failed to save IP blocks")

    # --------------------------------------------------------------- helpers

    def is_allowlisted(self, ip: str) -> bool:
        address = parse_ip(ip)
        return address is not None and any(address in network for network in self._allowlist)

    def _never_limit(self, ip: str) -> bool:
        if ip == "unknown" or self.is_allowlisted(ip):
            return True
        address = parse_ip(ip)
        if address is not None and is_internal_address(address):
            # Every visitor resolving to one internal address means the proxy
            # chain is not understood; limiting it would throttle the whole site.
            if not self._warned_internal:
                self._warned_internal = True
                logger.warning(
                    "Client address resolved to internal %s; rate limits are not applied to it. "
                    "Check SECURITY_CLIENT_IP_HEADER / SECURITY_TRUSTED_PROXIES.",
                    ip,
                )
            return True
        return False

    def _visitor(self, ip: str, now: float) -> _Visitor:
        visitor = self._visitors.get(ip)
        if visitor is None:
            visitor = _Visitor(self.settings.review_window_seconds)
            self._visitors[ip] = visitor
            while len(self._visitors) > self._max_tracked_ips:
                self._visitors.popitem(last=False)
        else:
            self._visitors.move_to_end(ip)
        visitor.last_seen = now
        return visitor

    def _active_block(self, ip: str, now: float) -> Block | None:
        block = self._blocks.get(ip)
        if block is None:
            return None
        if block.until <= now:
            self._blocks.pop(ip, None)
            self._dirty = True
            return None
        return block

    def _event(
        self,
        pending: list[dict[str, Any]],
        kind: str,
        summary: str,
        *,
        ip: str | None,
        now: float,
        severity: str = "warning",
        alert: bool = True,
    ) -> dict[str, Any]:
        event = {
            "kind": kind,
            "ip": ip or "",
            "summary": summary,
            "severity": severity,
            "time": _iso(now),
            "timestamp": now,
        }
        self._events.appendleft(event)
        if alert:
            pending.append(event)
        else:
            logger.info("Security shield: %s", summary)
        return event

    def _dispatch(self, pending: list[dict[str, Any]]) -> None:
        for event in pending:
            log = logger.error if event.get("severity") == "critical" else logger.warning
            log("Security shield: %s", event["summary"])
            if self.on_alert is None:
                continue
            now = self._clock()
            with self._lock:
                while self._alert_times and now - self._alert_times[0] > _ALERT_BUDGET_WINDOW_SECONDS:
                    self._alert_times.popleft()
                if len(self._alert_times) >= _ALERT_BUDGET:
                    self._suppressed_alerts += 1
                    continue
                self._alert_times.append(now)
                suppressed, self._suppressed_alerts = self._suppressed_alerts, 0
            outgoing = dict(event)
            if suppressed:
                outgoing["summary"] = f"{event['summary']} (+{suppressed} more alerts held back)"
            try:
                self.on_alert(outgoing)
            except Exception:
                logger.exception("Security alert handler failed")

    def _block_locked(
        self,
        pending: list[dict[str, Any]],
        ip: str,
        now: float,
        reason: str,
        *,
        seconds: float | None = None,
        manual: bool = False,
        actor: str | None = None,
    ) -> Block:
        if manual:
            offences = self._offences.get(ip, (0, 0.0))[0]
        else:
            offences, last = self._offences.get(ip, (0, 0.0))
            if now - last > _OFFENCE_MEMORY_SECONDS:
                offences = 0
            offences += 1
            self._offences[ip] = (offences, now)
        steps = self.settings.block_seconds or (900,)
        duration = float(seconds) if seconds else float(steps[min(offences, len(steps)) - 1])
        block = Block(
            ip=ip,
            until=now + duration,
            reason=reason,
            created=now,
            offences=max(offences, 1),
            manual=manual,
            actor=actor,
        )
        self._blocks[ip] = block
        self._visitors.pop(ip, None)
        self._dirty = True
        if manual:
            summary = f"{actor or 'A director'} blocked {ip} for {_describe_duration(duration)}: {reason}"
            self._event(pending, "manual-block", summary, ip=ip, now=now, severity="warning")
        else:
            repeat = f" (offence #{offences})" if offences > 1 else ""
            summary = f"Auto-blocked {ip} for {_describe_duration(duration)}{repeat}: {reason}"
            self._event(pending, "blocked", summary, ip=ip, now=now, severity="critical")
        return block

    def _offend(self, pending: list[dict[str, Any]], ip: str, now: float, reason: str) -> Verdict:
        """Block ``ip``, or with auto-blocking off, throttle it and raise the alarm."""

        if self.settings.auto_block:
            block = self._block_locked(pending, ip, now, reason)
            return Verdict("block", int(block.until - now), reason)
        visitor = self._visitors.get(ip)
        if visitor is None or now - visitor.throttle_logged_at >= _MINUTE:
            if visitor is not None:
                visitor.throttle_logged_at = now
            self._event(
                pending,
                "would-block",
                f"{ip} would have been blocked (auto-block is off): {reason}",
                ip=ip,
                now=now,
                severity="critical",
            )
        return Verdict("throttle", int(_MINUTE), reason)

    def _note_throttle(self, pending: list[dict[str, Any]], visitor: _Visitor, ip: str, now: float, what: str) -> None:
        self._throttled_ips[ip] = now
        if now - visitor.throttle_logged_at >= _MINUTE:
            visitor.throttle_logged_at = now
            self._event(pending, "throttled", f"Throttled {ip}: {what}", ip=ip, now=now, alert=False)

    def _site_checks(self, pending: list[dict[str, Any]], now: float, site_rate: float) -> None:
        settings = self.settings
        surging = site_rate >= settings.surge_requests_per_minute
        if surging and now - self._last_surge_alert >= _SITE_ALERT_COOLDOWN_SECONDS:
            self._last_surge_alert = now
            self._event(
                pending,
                "surge",
                f"Traffic surge: about {int(site_rate):,} requests in the last minute across the site",
                ip=None,
                now=now,
                severity="critical",
            )
        if now - self._last_sweep >= _SWEEP_INTERVAL_SECONDS:
            self._sweep(pending, now)

    def _sweep(self, pending: list[dict[str, Any]], now: float) -> None:
        self._last_sweep = now
        review = self.settings.review_window_seconds
        for ip in [ip for ip, seen in self._throttled_ips.items() if now - seen > review]:
            self._throttled_ips.pop(ip, None)
        stale = [ip for ip, visitor in self._visitors.items() if now - visitor.last_seen > review]
        for ip in stale:
            self._visitors.pop(ip, None)
        for ip in [ip for ip, block in self._blocks.items() if block.until <= now]:
            self._blocks.pop(ip, None)
            self._dirty = True
        for ip in [ip for ip, (_count, last) in self._offences.items() if now - last > _OFFENCE_MEMORY_SECONDS]:
            self._offences.pop(ip, None)
        spread = len(self._throttled_ips)
        widespread = spread >= self.settings.surge_throttled_ips
        if widespread and now - self._last_spread_alert >= _SITE_ALERT_COOLDOWN_SECONDS:
            self._last_spread_alert = now
            self._event(
                pending,
                "distributed",
                f"Possible distributed attack: {spread} different IPs hit rate limits in the last "
                f"{_describe_duration(review)}",
                ip=None,
                now=now,
                severity="critical",
            )
        if self._suppressed_alerts and self.on_alert is not None:
            while self._alert_times and now - self._alert_times[0] > _ALERT_BUDGET_WINDOW_SECONDS:
                self._alert_times.popleft()
            if len(self._alert_times) < _ALERT_BUDGET:
                count, self._suppressed_alerts = self._suppressed_alerts, 0
                self._event(
                    pending,
                    "summary",
                    f"{count} further security alerts were held back during a burst; "
                    "see the security overview for the full list",
                    ip=None,
                    now=now,
                    severity="warning",
                )

    # ------------------------------------------------------------ the checks

    def check(self, ip: str, *, method: str = "GET", path: str = "/", raw_path: str | None = None) -> Verdict:
        """Account for one incoming request and say what to do with it."""

        now = self._clock()
        pending: list[dict[str, Any]] = []
        settings = self.settings
        with self._lock:
            site_rate = self._site_requests.add(now)
            self._site_checks(pending, now, site_rate)
            block = self._active_block(ip, now)
            if block is not None:
                block.hits += 1
                verdict = Verdict("block", max(int(block.until - now), 1), block.reason)
            elif self._never_limit(ip):
                verdict = _ALLOW
            elif is_probe_path(raw_path or path) or (raw_path and is_probe_path(path)):
                visitor = self._visitor(ip, now)
                count = visitor.probes.add(now)
                if count >= settings.probes:
                    last = _printable(raw_path or path)
                    verdict = self._offend(pending, ip, now, f"probing for exploit paths (last: {last})")
                else:
                    verdict = Verdict("probe")
            else:
                visitor = self._visitor(ip, now)
                if path.startswith(self._asset_prefixes):
                    load = visitor.assets.add(now) / settings.assets_per_minute
                    what = "static file requests"
                else:
                    load = visitor.requests.add(now) / settings.requests_per_minute
                    what = "requests"
                    if method.upper() in _WRITE_METHODS:
                        write_load = visitor.writes.add(now) / settings.writes_per_minute
                        if write_load > load:
                            load, what = write_load, "form submissions / API writes"
                if load >= settings.hard_limit_factor:
                    verdict = self._offend(
                        pending, ip, now, f"request flood ({what} kept coming after being told to slow down)"
                    )
                elif load > 1.0:
                    self._note_throttle(pending, visitor, ip, now, f"too many {what} per minute")
                    verdict = Verdict("throttle", int(_MINUTE), "rate limit")
                else:
                    verdict = _ALLOW
        self._dispatch(pending)
        return verdict

    def note_response(self, ip: str, status_code: int, *, had_credentials: bool = False) -> None:
        """Count answers that betray scanning or password guessing."""

        if status_code != 404 and not (had_credentials and status_code in (401, 403)):
            return
        now = self._clock()
        pending: list[dict[str, Any]] = []
        settings = self.settings
        with self._lock:
            if self._never_limit(ip) or self._active_block(ip, now) is not None:
                return
            visitor = self._visitor(ip, now)
            window = _describe_duration(settings.review_window_seconds)
            if status_code == 404:
                count = visitor.misses.add(now)
                if count >= settings.not_found:
                    self._offend(pending, ip, now, f"scanning ({int(count)} not-found responses in {window})")
            else:
                count = visitor.failures.add(now)
                if count >= settings.credential_failures:
                    self._offend(pending, ip, now, f"repeated failed logins ({int(count)} in {window})")
        self._dispatch(pending)

    # ------------------------------------------------------- director tools

    def block_ip(self, ip: str, *, seconds: float, reason: str, actor: str | None = None) -> Block:
        address = parse_ip(ip)
        if address is None:
            raise ValueError("Enter a valid IPv4 or IPv6 address.")
        if is_internal_address(address):
            raise ValueError("Internal addresses belong to our own proxies and cannot be blocked.")
        now = self._clock()
        pending: list[dict[str, Any]] = []
        reason = " ".join(str(reason or "").split())[:200] or "Blocked by a director"
        with self._lock:
            block = self._block_locked(
                pending, str(address), now, reason, seconds=max(float(seconds), 60.0), manual=True, actor=actor
            )
        self._dispatch(pending)
        return block

    def unblock_ip(self, ip: str, *, actor: str | None = None) -> bool:
        address = parse_ip(ip)
        key = str(address) if address is not None else str(ip or "").strip()
        now = self._clock()
        pending: list[dict[str, Any]] = []
        with self._lock:
            removed = self._blocks.pop(key, None)
            self._offences.pop(key, None)
            self._visitors.pop(key, None)
            if removed is not None:
                self._dirty = True
                self._event(
                    pending,
                    "unblocked",
                    f"{actor or 'A director'} lifted the block on {key}",
                    ip=key,
                    now=now,
                    severity="info",
                )
        self._dispatch(pending)
        return removed is not None

    def report(self, kind: str, summary: str, *, ip: str | None = None, severity: str = "warning") -> None:
        """Record an incident spotted elsewhere in the app (and alert on it)."""

        now = self._clock()
        pending: list[dict[str, Any]] = []
        with self._lock:
            self._event(pending, kind, summary, ip=ip, now=now, severity=severity)
        self._dispatch(pending)

    def active_blocks(self) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            blocks = [block for block in self._blocks.values() if block.until > now]
        blocks.sort(key=lambda block: block.created, reverse=True)
        rows = []
        for block in blocks:
            row = block.to_dict()
            row["remaining"] = _describe_duration(block.until - now)
            row["until_label"] = datetime.fromtimestamp(block.until, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            rows.append(row)
        return rows

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            events = [dict(event) for event in list(self._events)[: max(int(limit), 0)]]
        for event in events:
            event["time_label"] = datetime.fromtimestamp(event["timestamp"], timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        return events

    def stats(self) -> dict[str, Any]:
        now = self._clock()
        review = self.settings.review_window_seconds
        with self._lock:
            return {
                "enabled": self.settings.enabled,
                "auto_block": self.settings.auto_block,
                "requests_last_minute": int(self._site_requests.estimate(now)),
                "tracked_ips": len(self._visitors),
                "active_blocks": sum(1 for block in self._blocks.values() if block.until > now),
                "throttled_ips": sum(1 for seen in self._throttled_ips.values() if now - seen <= review),
                "requests_per_minute": self.settings.requests_per_minute,
                "writes_per_minute": self.settings.writes_per_minute,
            }


# ------------------------------------------------------------------ middleware


def _header(scope: Mapping[str, Any], name: bytes) -> str:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def _shield_page(status_code: int, title: str, message: str, retry_after: int, accept: str) -> tuple[bytes, bytes]:
    if "text/html" in accept:
        body = (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>"
            "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0f0d;"
            "color:#d7e2d3;font:16px/1.5 system-ui,sans-serif}main{max-width:32rem;padding:2rem;text-align:center}"
            "h1{font-size:1.4rem;color:#8ea784}</style></head><body><main>"
            f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></main></body></html>"
        )
        return body.encode("utf-8"), b"text/html; charset=utf-8"
    payload = {"error": title, "detail": message}
    if retry_after:
        payload["retryAfter"] = retry_after
    return json.dumps(payload).encode("utf-8"), b"application/json"


async def _send_shield_response(
    scope: Mapping[str, Any],
    send: Callable[[dict[str, Any]], Awaitable[None]],
    status_code: int,
    title: str,
    message: str,
    *,
    retry_after: int = 0,
) -> None:
    body, content_type = _shield_page(status_code, title, message, retry_after, _header(scope, b"accept"))
    headers = [
        (b"content-type", content_type),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"x-robots-tag", b"noindex, nofollow"),
        (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"),
    ]
    if retry_after:
        headers.append((b"retry-after", str(int(retry_after)).encode("ascii")))
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body if scope.get("method") != "HEAD" else b""})


class _BodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body is too large.")


class ShieldMiddleware:
    """ASGI middleware putting :class:`SecurityShield` in front of every request.

    It also caps request body sizes and refuses state-changing requests that a
    browser reports as coming from another site (CSRF), whatever the session
    cookie's SameSite setting.

    ``trusted_session`` receives the ASGI scope (with the session already
    decoded) and returns ``True`` for signed-in admins, who are never limited
    so they cannot lock themselves out from a shared network.
    """

    def __init__(
        self,
        app: Callable,
        *,
        shield: SecurityShield,
        trusted_session: Callable[[Mapping[str, Any]], bool] | None = None,
        exempt_paths: Iterable[str] = ("/health",),
        trusted_origins: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.shield = shield
        self._trusted_session = trusted_session
        self._exempt_paths = frozenset(exempt_paths)
        self._trusted_origins = frozenset(origin.rstrip("/").lower() for origin in trusted_origins if origin)

    def _is_trusted(self, scope: Mapping[str, Any]) -> bool:
        if self._trusted_session is None:
            return False
        try:
            return bool(self._trusted_session(scope))
        except Exception:
            logger.exception("Trusted-session check failed; treating the request as anonymous")
            return False

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        shield = self.shield
        path = scope.get("path") or "/"
        is_http = scope["type"] == "http"
        method = str(scope.get("method") or "GET").upper() if is_http else "GET"
        ip: str | None = None

        if shield.settings.enabled and path not in self._exempt_paths and not self._is_trusted(scope):
            await shield.ensure_loaded_async()
            ip = shield.resolver.from_scope(scope)
            verdict = shield.check(ip, method=method, path=path, raw_path=scope.get("spectre.public_path"))
            shield.schedule_flush()
            if verdict.action != "allow":
                if not is_http:
                    await send({"type": "websocket.close", "code": 1008})
                elif verdict.action == "block":
                    await _send_shield_response(
                        scope,
                        send,
                        403,
                        "Access temporarily blocked",
                        "Unusual activity from your network tripped our automatic defences. "
                        f"Try again in {_describe_duration(verdict.retry_after)}.",
                        retry_after=verdict.retry_after,
                    )
                elif verdict.action == "throttle":
                    await _send_shield_response(
                        scope,
                        send,
                        429,
                        "Too many requests",
                        "You're going a little fast. Wait a moment and try again.",
                        retry_after=verdict.retry_after or 60,
                    )
                else:
                    await _send_shield_response(scope, send, 404, "Not Found", "Not Found")
                return

        if not is_http:
            await self.app(scope, receive, send)
            return

        if method in _WRITE_METHODS and _header(scope, b"sec-fetch-site").lower() == "cross-site":
            origin = _header(scope, b"origin").rstrip("/").lower()
            if origin not in self._trusted_origins:
                await _send_shield_response(
                    scope, send, 403, "Forbidden", "Cross-site form submissions are not accepted."
                )
                return

        content_type = _header(scope, b"content-type").lower()
        is_upload = content_type.startswith("multipart/")
        limit = shield.settings.max_upload_bytes if is_upload else shield.settings.max_body_bytes
        declared = _header(scope, b"content-length")
        if declared:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = True
            if too_large:
                await _send_shield_response(scope, send, 413, "Request too large", "The request body is too large.")
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > limit:
                    raise _BodyTooLarge()
            return message

        status_seen: list[int] = []

        async def tracking_send(message):
            if message.get("type") == "http.response.start":
                status_seen.append(int(message.get("status") or 0))
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if status_seen:
                raise
            await _send_shield_response(scope, send, 413, "Request too large", "The request body is too large.")
            return
        finally:
            if ip is not None and status_seen:
                had_credentials = bool(_header(scope, b"authorization"))
                shield.note_response(ip, status_seen[0], had_credentials=had_credentials)
                shield.schedule_flush()
