"""Front-door protection for the website: rate limits, automatic blocks and alerts.

The limits are generous on purpose. Normal browsing never meets them; they are
there so a flood, a vulnerability scanner or a password-guessing run stands out
at once and is stopped without anyone having to be awake.

Per client (an IPv4 address, an IPv6 /64, or a signed-in admin's account):

* every request counts towards a per-minute budget (static files have their
  own, larger one) and writes (POST/PUT/PATCH/DELETE) towards a smaller one.
  Past the budget the client is answered ``429 Too Many Requests``; a client
  that ignores that and keeps going to twice the budget is blocked. Each
  client may also only have so many requests in progress at once.
* failed logins (401/403 answers to requests that carried credentials), 404s,
  requests for well-known exploit paths (``/.env``, ``/wp-login.php``, ...) and
  URLs carrying script, SQL or command injection are counted over ten minutes;
  too many of any of them blocks the client.
* blocks last 15 minutes, then 1 hour, then 24 hours for repeat offenders.

Nobody is exempt. Signed-in admins (the owner included) are counted per
account, not per IP, against limits ``admin_limit_factor`` times larger, so a
person working fast never meets them but a script or a stolen session does.

Site-wide, the addresses of one network (IPv4 /24, IPv6 /48) share a larger
budget, so rotating through neighbouring addresses does not reset the count.
A surge of traffic or many clients being throttled at once raises an alert and
switches on "under attack" mode, which tightens anonymous limits (hosting, VPN
and Tor networks most) until things calm down. When too many requests are in
progress at once, anonymous ones are shed with ``503`` so admins can still work.

Every incident is logged and handed to ``on_alert`` (the app puts it in the
director's activity feed and, when configured, a Discord channel). Blocks are
saved through a :class:`BlockStore` so a redeploy does not let an attacker
straight back in.

Client IPs come from ``X-Forwarded-For`` read right to left, skipping hops that
are our own proxies (private addresses and Cloudflare's published ranges), so
a client cannot dodge its budget, or get someone else blocked, by sending a
made-up header.

The module also holds the per-request Content-Security-Policy nonce
(:func:`csp_nonce`), which lets the site's own inline scripts run while
injected ones are refused by the browser.

Every number can be tuned with ``SECURITY_*`` environment variables; see
``ShieldSettings.from_env`` and ``docs/security-shield.md``.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
import weakref
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NamedTuple, Protocol
from urllib.parse import unquote_plus

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

# Attack payloads in the URL. Only the path and query string are checked, never
# bodies: someone writing about "<script>" in a dossier or chat is not attacking.
# Each pattern is something no link or form on this site ever produces. Every
# repeat is bounded so a crafted URL cannot make the check itself slow.
_INJECTION_RE = re.compile(
    r"""
      <\s*/?\s*(?:script|iframe|frame|object|embed|svg|math|base|meta|template)\b   # markup
    | <[^<>]{0,200}\s(?:on[a-z]{3,}|formaction|srcdoc)\s*=                          # <img onerror=...>
    | (?:java|vb|live)script\s*:
    | document\s*\.\s*(?:cookie|domain|write)
    | \bunion\b[\s(/*+]+(?:all[\s(/*+]+)?select\b                                   # SQL
    | ['"`]\s*\)?\s*(?:or|and)\s+['"]?\w{1,40}['"]?\s*(?:=|like)\s*['"]?\w
    | \b(?:pg_sleep|sleep|benchmark)\s*\(\s*\d
    | \bwaitfor\s+delay\b
    | \binformation_schema\b
    | \$\{\s*(?:jndi|env|sys|lower|upper|date|::-)                                  # Log4Shell
    | \{\{[^{}]{0,200}?(?:__|\bconfig\b|\bself\b|\brequest\b|\bcycler\b|\d\s*[*+]\s*\d)  # template injection
    | \$\{\s*\d+\s*[*+]\s*\d+\s*\}
    | (?:;|\||&&|\$\(|`)\s*(?:wget|curl|bash|ncat|nc|python[23]?|perl|powershell|whoami|uname)\s   # shell
    | /bin/(?:ba)?sh\b
    | (?:file|php|phar|gopher|expect|dict|jar)://                                   # file inclusion
    | (?:^|[=/])\.\.[/\\]
    | etc/(?:passwd|shadow)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def printable(text: str, limit: int = 120) -> str:
    """Client-supplied text made safe to quote in logs and alerts."""

    return _CONTROL_CHARS_RE.sub("?", text[:limit])


def is_probe_path(path: str) -> bool:
    """Return ``True`` for paths that only scanners and exploit kits request."""

    if not path:
        return False
    if "\x00" in path or "%00" in path:
        return True
    return _PROBE_RE.search(path.replace("\\", "/")) is not None


def _decoded(text: str) -> str:
    # Payloads are often encoded twice to slip past filters that decode once.
    for _ in range(3):
        decoded = unquote_plus(text)
        if decoded == text:
            break
        text = decoded
    return text


_INJECTION_SCAN_CHARS = 4096


def looks_like_injection(path: str, query: str = "") -> bool:
    """Return ``True`` when the URL carries a script, SQL, shell or file-inclusion payload."""

    for part in (path, query):
        # Real URLs here are short; capping the scan keeps every check cheap.
        if part and _INJECTION_RE.search(_decoded(part[:_INJECTION_SCAN_CHARS])) is not None:
            return True
    return False


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


def env_float(name: str, default: float, *, minimum: float, maximum: float | None = None) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using %s.", name, raw, default)
        return default
    if value != value:  # NaN
        return default
    value = max(value, minimum)
    return min(value, maximum) if maximum is not None else value


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


def client_key(ip: str) -> str:
    """What one visitor is counted as: its IPv4 address, or its IPv6 /64.

    A home or server connection gets a whole IPv6 /64, so counting single IPv6
    addresses would hand every visitor billions of fresh budgets.
    """

    address = parse_ip(ip)
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address) if address is not None else ip


def network_key(ip: str) -> str | None:
    """The network neighbouring addresses share a budget in (IPv4 /24, IPv6 /48)."""

    address = parse_ip(ip)
    if address is None:
        return None
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def admin_key(account: str) -> str:
    return f"admin:{account}"


def _block_network(key: str):
    if "/" not in key or key.startswith("admin:"):
        return None
    try:
        return ipaddress.ip_network(key, strict=False)
    except ValueError:
        return None


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
    # Signed-in admins get every limit multiplied by this: far past what a
    # person clicking through the console can reach, well short of a script.
    admin_limit_factor: float = 5.0
    # Neighbouring addresses (IPv4 /24, IPv6 /48) share this many per-IP budgets.
    network_factor: float = 8.0
    # Requests one client may have in progress at once (admins: times the factor).
    max_pending_per_client: int = 50
    # Past this many requests in progress site-wide, anonymous ones are shed.
    max_pending: int = 1000
    # Under attack, anonymous budgets shrink to this share, and to
    # ``hosting_factor`` for data-centre, VPN and Tor addresses.
    under_attack_factor: float = 0.5
    hosting_factor: float = 0.25
    under_attack_seconds: float = 600.0

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
            admin_limit_factor=env_float("SECURITY_ADMIN_LIMIT_FACTOR", cls.admin_limit_factor, minimum=1.0),
            network_factor=env_float("SECURITY_NETWORK_FACTOR", cls.network_factor, minimum=1.0),
            max_pending_per_client=env_int(
                "SECURITY_MAX_PENDING_PER_IP", cls.max_pending_per_client, minimum=5
            ),
            max_pending=env_int("SECURITY_MAX_PENDING", cls.max_pending, minimum=50),
            under_attack_factor=env_float(
                "SECURITY_UNDER_ATTACK_FACTOR", cls.under_attack_factor, minimum=0.05, maximum=1.0
            ),
            hosting_factor=env_float("SECURITY_HOSTING_FACTOR", cls.hosting_factor, minimum=0.05, maximum=1.0),
            under_attack_seconds=env_int("SECURITY_UNDER_ATTACK_MINUTES", 10, minimum=1) * 60.0,
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


_UNCLASSIFIED = object()


class _Visitor:
    __slots__ = (
        "requests",
        "writes",
        "assets",
        "failures",
        "misses",
        "probes",
        "last_seen",
        "throttle_logged_at",
        "network",
    )

    def __init__(self, review_window: float) -> None:
        self.requests = _SlidingCount(_MINUTE)
        self.writes = _SlidingCount(_MINUTE)
        self.assets = _SlidingCount(_MINUTE)
        self.failures = _SlidingCount(review_window)
        self.misses = _SlidingCount(review_window)
        self.probes = _SlidingCount(review_window)
        self.last_seen = 0.0
        self.throttle_logged_at = 0.0
        # "datacenter", "vpn", "tor" or None once looked up.
        self.network: Any = _UNCLASSIFIED


@dataclass
class Block:
    # An IP address, a network ("203.0.113.0/24") or an admin account ("admin:<id>").
    ip: str
    until: float
    reason: str
    created: float
    offences: int = 1
    manual: bool = False
    actor: str | None = None
    hits: int = 0
    network: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.network = _block_network(self.ip)

    @property
    def kind(self) -> str:
        if self.ip.startswith("admin:"):
            return "account"
        return "network" if self.network is not None and self.network.num_addresses > 1 else "ip"

    @property
    def label(self) -> str:
        if self.kind == "account":
            return f"admin account {self.ip[len('admin:'):]}"
        if self.kind == "network":
            return f"network {self.ip}"
        return self.ip

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
    action: str  # "allow", "throttle", "block", "probe" or "overload"
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
        network_classifier: Callable[[str], str | None] | None = None,
    ) -> None:
        self.settings = settings or ShieldSettings.from_env()
        self.resolver = resolver or ClientIpResolver.from_env()
        self.on_alert = on_alert
        self._store = store
        self._clock = clock
        self._asset_prefixes = tuple(asset_prefixes)
        self._max_tracked_ips = max(int(max_tracked_ips), 100)
        # Names the hosting/VPN/Tor network an address belongs to, if any.
        self._classify = network_classifier
        self._allowlist = self._parse_allowlist(self.settings.allowlist)
        self._lock = threading.RLock()
        self._visitors: OrderedDict[str, _Visitor] = OrderedDict()
        self._networks: OrderedDict[str, _SlidingCount] = OrderedDict()
        self._blocks: dict[str, Block] = {}
        # Blocks covering more than one address, checked by containment.
        self._network_blocks: dict[str, Any] = {}
        self._offences: dict[str, tuple[int, float]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
        self._site_requests = _SlidingCount(_MINUTE)
        self._throttled_ips: dict[str, float] = {}
        self._pending: dict[str, int] = {}
        self._pending_total = 0
        self._under_attack_until = 0.0
        self._under_attack_reason = ""
        self._last_surge_alert = float("-inf")
        self._last_spread_alert = float("-inf")
        self._last_overload_alert = float("-inf")
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
            self._networks.clear()
            self._blocks.clear()
            self._network_blocks.clear()
            self._offences.clear()
            self._events.clear()
            self._site_requests = _SlidingCount(_MINUTE)
            self._throttled_ips.clear()
            self._pending.clear()
            self._pending_total = 0
            self._under_attack_until = 0.0
            self._under_attack_reason = ""
            self._last_surge_alert = float("-inf")
            self._last_spread_alert = float("-inf")
            self._last_overload_alert = float("-inf")
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
            was_dirty = self._dirty
            for raw in entries or ():
                block = Block.from_dict(raw)
                if block is None:
                    continue
                if block.until > now and block.ip not in self._blocks:
                    self._put_block(block)
                if not block.manual and now - block.created < _OFFENCE_MEMORY_SECONDS:
                    self._offences[block.ip] = (block.offences, block.created)
            if isinstance(payload, Mapping):
                try:
                    until = float(payload.get("under_attack_until") or 0)
                except (TypeError, ValueError):
                    until = 0.0
                if until > max(now, self._under_attack_until):
                    self._under_attack_until = until
                    self._under_attack_reason = str(payload.get("under_attack_reason") or "")[:200]
            # Restoring what storage already holds is not a change to save.
            self._dirty = was_dirty
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
            if self._under_attack_until > now:
                payload["under_attack_until"] = self._under_attack_until
                payload["under_attack_reason"] = self._under_attack_reason
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

    def _network_counter(self, key: str) -> _SlidingCount:
        counter = self._networks.get(key)
        if counter is None:
            counter = _SlidingCount(_MINUTE)
            self._networks[key] = counter
            while len(self._networks) > self._max_tracked_ips:
                self._networks.popitem(last=False)
        else:
            self._networks.move_to_end(key)
        return counter

    def _put_block(self, block: Block) -> None:
        self._blocks[block.ip] = block
        network = block.network
        # IPv4 /24s and IPv6 /48s and /64s are found by key; only other sizes
        # (a director's /16, say) need checking address by address.
        if network is not None and network.prefixlen not in ((24,) if network.version == 4 else (48, 64, 128)):
            if network.num_addresses > 1:
                self._network_blocks[block.ip] = network
        else:
            self._network_blocks.pop(block.ip, None)
        self._dirty = True

    def _remove_block(self, key: str) -> Block | None:
        self._network_blocks.pop(key, None)
        block = self._blocks.pop(key, None)
        if block is not None:
            self._dirty = True
        return block

    def _active_block(self, key: str, now: float) -> Block | None:
        block = self._blocks.get(key)
        if block is None:
            return None
        if block.until <= now:
            self._remove_block(key)
            return None
        return block

    def _find_block(self, ip: str, now: float) -> Block | None:
        """The block stopping this address: its own, its /64's, its network's or a wider one's."""

        for key in dict.fromkeys((ip, client_key(ip), network_key(ip))):
            block = self._active_block(key, now) if key is not None else None
            if block is not None:
                return block
        address = parse_ip(ip) if self._network_blocks else None
        if address is not None:
            for key, network in list(self._network_blocks.items()):
                if address.version == network.version and address in network:
                    block = self._active_block(key, now)
                    if block is not None:
                        return block
        return None

    def under_attack(self, now: float | None = None) -> bool:
        return (self._clock() if now is None else now) < self._under_attack_until

    def _engage_under_attack(self, now: float, reason: str) -> bool:
        """Tighten anonymous limits for a while; ``True`` when this switched it on."""

        entering = not self.under_attack(now)
        until = now + self.settings.under_attack_seconds
        if until > self._under_attack_until:
            self._under_attack_until = until
            if entering:
                self._under_attack_reason = reason
        return entering

    def _anonymous_factor(self, visitor: _Visitor, ip: str, now: float) -> float:
        if not self.under_attack(now):
            return 1.0
        factor = self.settings.under_attack_factor
        if self._classify is not None:
            if visitor.network is _UNCLASSIFIED:
                try:
                    visitor.network = self._classify(ip)
                except Exception:
                    logger.exception("Network classification failed for %s", ip)
                    visitor.network = None
            if visitor.network:
                factor = min(factor, self.settings.hosting_factor)
        return factor

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
        source: str | None = None,
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
        self._put_block(block)
        self._visitors.pop(ip, None)
        label = source or block.label
        if manual:
            summary = f"{actor or 'A director'} blocked {label} for {_describe_duration(duration)}: {reason}"
            self._event(pending, "manual-block", summary, ip=ip, now=now, severity="warning")
        else:
            repeat = f" (offence #{offences})" if offences > 1 else ""
            summary = f"Auto-blocked {label} for {_describe_duration(duration)}{repeat}: {reason}"
            self._event(pending, "blocked", summary, ip=ip, now=now, severity="critical")
        return block

    def _offend(
        self, pending: list[dict[str, Any]], key: str, now: float, reason: str, *, source: str | None = None
    ) -> Verdict:
        """Block ``key``, or with auto-blocking off, throttle it and raise the alarm."""

        if self.settings.auto_block:
            block = self._block_locked(pending, key, now, reason, source=source)
            return Verdict("block", int(block.until - now), reason)
        visitor = self._visitors.get(key)
        if visitor is None or now - visitor.throttle_logged_at >= _MINUTE:
            if visitor is not None:
                visitor.throttle_logged_at = now
            self._event(
                pending,
                "would-block",
                f"{source or key} would have been blocked (auto-block is off): {reason}",
                ip=key,
                now=now,
                severity="critical",
            )
        return Verdict("throttle", int(_MINUTE), reason)

    def _note_throttle(
        self, pending: list[dict[str, Any]], visitor: _Visitor, key: str, now: float, what: str, *, source: str
    ) -> None:
        self._throttled_ips[key] = now
        if now - visitor.throttle_logged_at >= _MINUTE:
            visitor.throttle_logged_at = now
            self._event(pending, "throttled", f"Throttled {source}: {what}", ip=key, now=now, alert=False)

    def _site_checks(self, pending: list[dict[str, Any]], now: float, site_rate: float) -> None:
        settings = self.settings
        surging = site_rate >= settings.surge_requests_per_minute
        if surging:
            entering = self._engage_under_attack(now, "traffic surge")
            if now - self._last_surge_alert >= _SITE_ALERT_COOLDOWN_SECONDS:
                self._last_surge_alert = now
                self._event(
                    pending,
                    "surge",
                    f"Traffic surge: about {int(site_rate):,} requests in the last minute across the site"
                    + (self._under_attack_note() if entering else ""),
                    ip=None,
                    now=now,
                    severity="critical",
                )
        if now - self._last_sweep >= _SWEEP_INTERVAL_SECONDS:
            self._sweep(pending, now)

    def _under_attack_note(self) -> str:
        return (
            f". Under-attack mode is on for {_describe_duration(self.settings.under_attack_seconds)}: "
            "anonymous limits are tightened (hosting, VPN and Tor networks most); signed-in admins are unaffected"
        )

    def _sweep(self, pending: list[dict[str, Any]], now: float) -> None:
        self._last_sweep = now
        review = self.settings.review_window_seconds
        for key in [key for key, seen in self._throttled_ips.items() if now - seen > review]:
            self._throttled_ips.pop(key, None)
        stale = [key for key, visitor in self._visitors.items() if now - visitor.last_seen > review]
        for key in stale:
            self._visitors.pop(key, None)
        for key in [key for key, counter in self._networks.items() if counter.estimate(now) <= 0]:
            self._networks.pop(key, None)
        for key in [key for key, block in self._blocks.items() if block.until <= now]:
            self._remove_block(key)
        for key in [key for key, (_count, last) in self._offences.items() if now - last > _OFFENCE_MEMORY_SECONDS]:
            self._offences.pop(key, None)
        spread = len(self._throttled_ips)
        widespread = spread >= self.settings.surge_throttled_ips
        if widespread:
            entering = self._engage_under_attack(now, "many clients hitting rate limits")
            if now - self._last_spread_alert >= _SITE_ALERT_COOLDOWN_SECONDS:
                self._last_spread_alert = now
                self._event(
                    pending,
                    "distributed",
                    f"Possible distributed attack: {spread} different clients hit rate limits in the last "
                    f"{_describe_duration(review)}" + (self._under_attack_note() if entering else ""),
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

    def _admin_subject(self, ip: str, account: str) -> tuple[str, str, float]:
        """(counter key, how alerts name it, limit factor) for a signed-in admin."""

        return admin_key(account), f"admin account {account} (from {ip})", self.settings.admin_limit_factor

    def check(
        self,
        ip: str,
        *,
        method: str = "GET",
        path: str = "/",
        raw_path: str | None = None,
        query: str = "",
        account: str | None = None,
    ) -> Verdict:
        """Account for one incoming request and say what to do with it.

        ``account`` is the signed-in admin making the request, if any. Admins
        are counted per account, so an IP block someone else earned on a shared
        network does not lock them out, against limits ``admin_limit_factor``
        times larger. They are never exempt: past those limits the account is
        throttled and blocked like anyone else.
        """

        now = self._clock()
        pending: list[dict[str, Any]] = []
        with self._lock:
            site_rate = self._site_requests.add(now)
            self._site_checks(pending, now, site_rate)
            if account:
                key, source, factor = self._admin_subject(ip, account)
                block = self._active_block(key, now)
                visitor = None if block is not None else self._visitor(key, now)
            else:
                key, source = client_key(ip), client_key(ip)
                block = self._find_block(ip, now)
                visitor = None
                factor = 1.0
                if block is None and not self._never_limit(ip):
                    visitor = self._visitor(key, now)
                    factor = self._anonymous_factor(visitor, ip, now)
            if block is not None:
                block.hits += 1
                verdict = Verdict("block", max(int(block.until - now), 1), block.reason)
            elif visitor is None:
                verdict = _ALLOW
            else:
                verdict = self._judge(
                    pending,
                    visitor,
                    key,
                    ip,
                    now,
                    method=method,
                    path=path,
                    raw_path=raw_path,
                    query=query,
                    factor=factor,
                    source=source,
                    admin=bool(account),
                )
        self._dispatch(pending)
        return verdict

    def _judge(
        self,
        pending: list[dict[str, Any]],
        visitor: _Visitor,
        key: str,
        ip: str,
        now: float,
        *,
        method: str,
        path: str,
        raw_path: str | None,
        query: str,
        factor: float,
        source: str,
        admin: bool,
    ) -> Verdict:
        settings = self.settings
        asked = raw_path or path
        injection = looks_like_injection(asked, query) or (raw_path is not None and looks_like_injection(path))
        if injection or is_probe_path(asked) or (raw_path and is_probe_path(path)):
            count = visitor.probes.add(now)
            # Under attack only shrinks request budgets; three exploit probes are
            # already few. Admins get the same headroom as everywhere else.
            if count >= settings.probes * (factor if admin else 1.0):
                last = printable(asked + (f"?{query}" if query else ""))
                what = "sending injection payloads" if injection else "probing for exploit paths"
                return self._offend(pending, key, now, f"{what} (last: {last})", source=source)
            return Verdict("probe")

        if path.startswith(self._asset_prefixes):
            load = visitor.assets.add(now) / (settings.assets_per_minute * factor)
            what = "static file requests"
        else:
            load = visitor.requests.add(now) / (settings.requests_per_minute * factor)
            what = "requests"
            if method.upper() in _WRITE_METHODS:
                write_load = visitor.writes.add(now) / (settings.writes_per_minute * factor)
                if write_load > load:
                    load, what = write_load, "form submissions / API writes"
        if load >= settings.hard_limit_factor:
            return self._offend(
                pending, key, now, f"request flood ({what} kept coming after being told to slow down)", source=source
            )

        # Neighbouring addresses share a budget so rotating through a block of
        # them does not start the count over. Admins are judged as themselves.
        network = None if admin else network_key(ip)
        network_load = 0.0
        if network is not None and not path.startswith(self._asset_prefixes):
            budget = settings.requests_per_minute * settings.network_factor * factor
            network_load = self._network_counter(network).add(now) / budget
            if network_load >= settings.hard_limit_factor:
                return self._offend(
                    pending,
                    network,
                    now,
                    f"request flood from many addresses in one network (last: {source})",
                    source=f"network {network}",
                )
        if load > 1.0:
            self._note_throttle(pending, visitor, key, now, f"too many {what} per minute", source=source)
            return Verdict("throttle", int(_MINUTE), "rate limit")
        if network_load > 1.0:
            self._note_throttle(
                pending, visitor, key, now, f"its network {network} is sending too many requests", source=source
            )
            return Verdict("throttle", int(_MINUTE), "network rate limit")
        return _ALLOW

    def note_response(
        self, ip: str, status_code: int, *, had_credentials: bool = False, account: str | None = None
    ) -> None:
        """Count answers that betray scanning or password guessing."""

        if status_code != 404 and not (had_credentials and status_code in (401, 403)):
            return
        now = self._clock()
        pending: list[dict[str, Any]] = []
        settings = self.settings
        with self._lock:
            if account:
                key, source, factor = self._admin_subject(ip, account)
                if self._active_block(key, now) is not None:
                    return
            else:
                if self._never_limit(ip) or self._find_block(ip, now) is not None:
                    return
                key = source = client_key(ip)
                factor = 1.0
            visitor = self._visitor(key, now)
            window = _describe_duration(settings.review_window_seconds)
            if status_code == 404:
                count = visitor.misses.add(now)
                if count >= settings.not_found * factor:
                    self._offend(
                        pending, key, now, f"scanning ({int(count)} not-found responses in {window})", source=source
                    )
            else:
                count = visitor.failures.add(now)
                if count >= settings.credential_failures * factor:
                    self._offend(
                        pending, key, now, f"repeated failed logins ({int(count)} in {window})", source=source
                    )
        self._dispatch(pending)

    # --------------------------------------------------------- concurrency

    def acquire(self, ip: str, *, account: str | None = None) -> Verdict:
        """Reserve a slot for a request about to be handled; pair with :meth:`release`.

        One client may only have so many requests in progress, so a pile of
        deliberately slow requests cannot tie the server up the way a flood
        would. Past ``max_pending`` site-wide, anonymous requests are shed so
        admins can still reach the site to deal with whatever is going on.
        """

        now = self._clock()
        pending: list[dict[str, Any]] = []
        settings = self.settings
        verdict = _ALLOW
        with self._lock:
            if account:
                key, source, factor = self._admin_subject(ip, account)
                limited = True
            else:
                key = source = client_key(ip)
                factor = 1.0
                limited = not self._never_limit(ip)
            in_progress = self._pending.get(key, 0)
            if limited and not account and self._pending_total >= settings.max_pending:
                if now - self._last_overload_alert >= _SITE_ALERT_COOLDOWN_SECONDS:
                    self._last_overload_alert = now
                    entering = self._engage_under_attack(now, "server overloaded")
                    self._event(
                        pending,
                        "overload",
                        f"Server overloaded: {self._pending_total:,} requests in progress; anonymous requests "
                        "are being turned away so admins can still work"
                        + (self._under_attack_note() if entering else ""),
                        ip=None,
                        now=now,
                        severity="critical",
                    )
                verdict = Verdict("overload", 5, "server busy")
            elif limited and in_progress >= settings.max_pending_per_client * factor:
                visitor = self._visitor(key, now)
                self._note_throttle(pending, visitor, key, now, "too many requests at once", source=source)
                verdict = Verdict("throttle", 5, "too many requests at once")
            else:
                self._pending[key] = in_progress + 1
                self._pending_total += 1
        self._dispatch(pending)
        return verdict

    def release(self, ip: str, *, account: str | None = None) -> None:
        key = admin_key(account) if account else client_key(ip)
        with self._lock:
            count = self._pending.get(key, 0)
            if count <= 0:
                return
            if count == 1:
                self._pending.pop(key, None)
            else:
                self._pending[key] = count - 1
            self._pending_total = max(self._pending_total - 1, 0)

    # ------------------------------------------------------- director tools

    def block_ip(self, ip: str, *, seconds: float, reason: str, actor: str | None = None) -> Block:
        """Block an address, or a whole network given as CIDR (``203.0.113.0/24``)."""

        raw = str(ip or "").strip()
        if "/" in raw:
            try:
                network = ipaddress.ip_network(raw, strict=False)
            except ValueError:
                raise ValueError("Enter a valid IPv4 or IPv6 address or network.") from None
            # A /16 is already 65,536 addresses: wider would take out whole providers.
            if network.prefixlen < (16 if network.version == 4 else 32):
                raise ValueError("That network is too wide to block; use at most a /16 (IPv4) or /32 (IPv6).")
            if any(network.overlaps(internal) for internal in _INTERNAL_NETWORKS if internal.version == network.version):
                raise ValueError("Internal addresses belong to our own proxies and cannot be blocked.")
            key = str(network) if network.num_addresses > 1 else str(network.network_address)
        else:
            address = parse_ip(raw)
            if address is None:
                raise ValueError("Enter a valid IPv4 or IPv6 address or network.")
            if is_internal_address(address):
                raise ValueError("Internal addresses belong to our own proxies and cannot be blocked.")
            key = str(address)
        now = self._clock()
        pending: list[dict[str, Any]] = []
        reason = " ".join(str(reason or "").split())[:200] or "Blocked by a director"
        with self._lock:
            block = self._block_locked(
                pending, key, now, reason, seconds=max(float(seconds), 60.0), manual=True, actor=actor
            )
        self._dispatch(pending)
        return block

    def unblock_ip(self, ip: str, *, actor: str | None = None) -> bool:
        """Lift a block on an address, a network or an admin account (``admin:<id>``)."""

        raw = str(ip or "").strip()
        key = raw
        if not raw.startswith("admin:"):
            address = parse_ip(raw)
            if address is not None:
                key = str(address)
            else:
                network = _block_network(raw)
                if network is not None:
                    key = str(network)
        now = self._clock()
        pending: list[dict[str, Any]] = []
        with self._lock:
            removed = self._remove_block(key)
            self._offences.pop(key, None)
            self._visitors.pop(key, None)
            self._networks.pop(key, None)
            if removed is not None:
                self._event(
                    pending,
                    "unblocked",
                    f"{actor or 'A director'} lifted the block on {removed.label}",
                    ip=key,
                    now=now,
                    severity="info",
                )
        self._dispatch(pending)
        return removed is not None

    def set_under_attack(self, seconds: float, *, actor: str | None = None) -> None:
        """Switch under-attack mode on by hand (or extend it) for ``seconds``."""

        now = self._clock()
        pending: list[dict[str, Any]] = []
        seconds = max(float(seconds), 60.0)
        with self._lock:
            self._under_attack_until = max(self._under_attack_until, now + seconds)
            self._under_attack_reason = f"raised by {actor or 'a director'}"
            self._dirty = True
            self._event(
                pending,
                "under-attack",
                f"{actor or 'A director'} switched on under-attack mode for {_describe_duration(seconds)}",
                ip=None,
                now=now,
                severity="warning",
            )
        self._dispatch(pending)

    def clear_under_attack(self, *, actor: str | None = None) -> bool:
        now = self._clock()
        pending: list[dict[str, Any]] = []
        with self._lock:
            was_on = self.under_attack(now)
            self._under_attack_until = 0.0
            self._under_attack_reason = ""
            if was_on:
                self._dirty = True
                self._event(
                    pending,
                    "under-attack",
                    f"{actor or 'A director'} switched off under-attack mode",
                    ip=None,
                    now=now,
                    severity="info",
                )
        self._dispatch(pending)
        return was_on

    def report(
        self, kind: str, summary: str, *, ip: str | None = None, severity: str = "warning", alert: bool = True
    ) -> None:
        """Record an incident spotted elsewhere in the app (and, unless ``alert`` is off, alert on it)."""

        now = self._clock()
        pending: list[dict[str, Any]] = []
        with self._lock:
            self._event(pending, kind, summary, ip=ip, now=now, severity=severity, alert=alert)
        self._dispatch(pending)

    def active_blocks(self) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            blocks = [block for block in self._blocks.values() if block.until > now]
        blocks.sort(key=lambda block: block.created, reverse=True)
        rows = []
        for block in blocks:
            row = block.to_dict()
            row["kind"] = block.kind
            row["label"] = block.label
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
        settings = self.settings
        with self._lock:
            under_attack = self.under_attack(now)
            return {
                "enabled": settings.enabled,
                "auto_block": settings.auto_block,
                "requests_last_minute": int(self._site_requests.estimate(now)),
                "tracked_ips": len(self._visitors),
                "active_blocks": sum(1 for block in self._blocks.values() if block.until > now),
                "throttled_ips": sum(1 for seen in self._throttled_ips.values() if now - seen <= review),
                "requests_per_minute": settings.requests_per_minute,
                "writes_per_minute": settings.writes_per_minute,
                "admin_limit_factor": settings.admin_limit_factor,
                "admin_requests_per_minute": int(settings.requests_per_minute * settings.admin_limit_factor),
                "admin_writes_per_minute": int(settings.writes_per_minute * settings.admin_limit_factor),
                "in_progress": self._pending_total,
                "max_pending": settings.max_pending,
                "under_attack": under_attack,
                "under_attack_reason": self._under_attack_reason if under_attack else "",
                "under_attack_remaining": (
                    _describe_duration(self._under_attack_until - now) if under_attack else ""
                ),
                "under_attack_percent": int(round(settings.under_attack_factor * 100)),
                "hosting_percent": int(round(settings.hosting_factor * 100)),
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


# Session key holding the digest of the browser a session was first used from.
_SESSION_BROWSER_KEY = "_shield_browser"
_VERSION_RE = re.compile(r"[\d._]+")
# Query parameters that carry a credential (EventSource and websockets cannot send headers).
_CREDENTIAL_PARAMS = frozenset({b"token", b"access_token", b"api_key", b"apikey"})


def browser_fingerprint(user_agent: str) -> str:
    """Digest of the browser behind a session, ignoring version numbers so updates keep it."""

    normalized = " ".join(_VERSION_RE.sub("", (user_agent or "").lower()).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _carries_credentials(scope: Mapping[str, Any]) -> bool:
    if _header(scope, b"authorization"):
        return True
    for part in (scope.get("query_string") or b"").split(b"&"):
        if part.split(b"=", 1)[0].lower() in _CREDENTIAL_PARAMS:
            return True
    return False


class ShieldMiddleware:
    """ASGI middleware putting :class:`SecurityShield` in front of every request.

    It also caps request body sizes, refuses state-changing requests that a
    browser reports as coming from another site (CSRF) whatever the session
    cookie's SameSite setting, and ties each signed-in session to the browser
    it was first used from, so a session cookie copied elsewhere stops working.

    ``admin_identity`` receives the ASGI scope (with the session already
    decoded) and returns the account id of a signed-in admin, or ``None``.
    Admins are counted per account against larger limits rather than exempted;
    see :meth:`SecurityShield.check`.
    """

    def __init__(
        self,
        app: Callable,
        *,
        shield: SecurityShield,
        admin_identity: Callable[[Mapping[str, Any]], str | None] | None = None,
        exempt_paths: Iterable[str] = ("/health",),
        trusted_origins: Iterable[str] = (),
        bind_sessions: bool = True,
    ) -> None:
        self.app = app
        self.shield = shield
        self._admin_identity = admin_identity
        self._exempt_paths = frozenset(exempt_paths)
        self._trusted_origins = frozenset(origin.rstrip("/").lower() for origin in trusted_origins if origin)
        self._bind_sessions = bind_sessions

    def _identify(self, scope: Mapping[str, Any]) -> str | None:
        if self._admin_identity is None:
            return None
        try:
            account = self._admin_identity(scope)
        except Exception:
            logger.exception("Admin identity check failed; treating the request as anonymous")
            return None
        account = str(account or "").strip()[:64]
        return account or None

    @staticmethod
    def _bind_session(scope: Mapping[str, Any]) -> None:
        """Tie a signed-in session that has no browser yet to the one sending this request."""

        session = scope.get("session")
        if isinstance(session, dict) and session.get("user") and _SESSION_BROWSER_KEY not in session:
            session[_SESSION_BROWSER_KEY] = browser_fingerprint(_header(scope, b"user-agent"))

    def _guard_session(self, scope: Mapping[str, Any], ip: str) -> None:
        session = scope.get("session")
        if not isinstance(session, dict) or not session.get("user"):
            return
        fingerprint = browser_fingerprint(_header(scope, b"user-agent"))
        stored = session.get(_SESSION_BROWSER_KEY)
        if not isinstance(stored, str):
            # Sessions from before binding existed are tied to the browser using them now.
            session[_SESSION_BROWSER_KEY] = fingerprint
            return
        if hmac.compare_digest(stored, fingerprint):
            return
        account = self._identify(scope)
        user = session.get("user")
        name = ""
        if isinstance(user, Mapping):
            name = str(user.get("global_name") or user.get("username") or user.get("id") or "")
        who = printable(name or "a member", 60)
        if account:
            who = f"admin {who} ({printable(account, 30)})"
        # Clearing in place: the session middleware outside sees it and drops the cookie.
        session.clear()
        self.shield.report(
            "session-mismatch",
            f"Signed out {who}: their session cookie was sent from a different browser than the one "
            f"it was issued to, from {ip}. This is what a stolen session cookie looks like.",
            ip=ip,
            severity="critical" if account else "warning",
            alert=bool(account),
        )

    async def _refuse(self, scope, send, verdict: Verdict, *, is_http: bool, account: str | None) -> None:
        if not is_http:
            await send({"type": "websocket.close", "code": 1008})
        elif verdict.action == "block":
            if account:
                message = (
                    "Unusual activity from your account tripped our automatic defences. "
                    f"Try again in {_describe_duration(verdict.retry_after)}, or ask a director to lift the "
                    "block from the Security Overview."
                )
            else:
                message = (
                    "Unusual activity from your network tripped our automatic defences. "
                    f"Try again in {_describe_duration(verdict.retry_after)}."
                )
            await _send_shield_response(
                scope, send, 403, "Access temporarily blocked", message, retry_after=verdict.retry_after
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
        elif verdict.action == "overload":
            await _send_shield_response(
                scope,
                send,
                503,
                "Server busy",
                "The site is under heavy load right now. Try again in a few seconds.",
                retry_after=verdict.retry_after or 5,
            )
        else:
            await _send_shield_response(scope, send, 404, "Not Found", "Not Found")

    async def _websocket(self, scope, receive, send, *, ip: str | None, account: str | None) -> None:
        if ip is None or not _carries_credentials(scope):
            await self.app(scope, receive, send)
            return
        settled = False

        async def watching_send(message):
            nonlocal settled
            kind = message.get("type")
            if not settled and kind in ("websocket.accept", "websocket.close", "websocket.http.response.start"):
                settled = True
                # A handshake turned away before it was accepted is a websocket's 401/403.
                if kind != "websocket.accept":
                    status_code = int(message.get("status") or 403)
                    self.shield.note_response(ip, status_code, had_credentials=True, account=account)
                    self.shield.schedule_flush()
            await send(message)

        await self.app(scope, receive, watching_send)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        shield = self.shield
        path = scope.get("path") or "/"
        is_http = scope["type"] == "http"
        method = str(scope.get("method") or "GET").upper() if is_http else "GET"
        ip: str | None = None
        account: str | None = None

        if shield.settings.enabled and path not in self._exempt_paths:
            await shield.ensure_loaded_async()
            ip = shield.resolver.from_scope(scope)
            if is_http and self._bind_sessions:
                self._guard_session(scope, ip)
            account = self._identify(scope)
            verdict = shield.check(
                ip,
                method=method,
                path=path,
                raw_path=scope.get("spectre.public_path"),
                query=(scope.get("query_string") or b"").decode("latin-1"),
                account=account,
            )
            shield.schedule_flush()
            if verdict.action != "allow":
                await self._refuse(scope, send, verdict, is_http=is_http, account=account)
                return

        if not is_http:
            await self._websocket(scope, receive, send, ip=ip, account=account)
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

        held = False
        if ip is not None:
            verdict = shield.acquire(ip, account=account)
            if verdict.action != "allow":
                await self._refuse(scope, send, verdict, is_http=True, account=account)
                return
            held = True

        def release() -> None:
            nonlocal held
            if held:
                held = False
                shield.release(ip, account=account)

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
                # Event streams stay open for hours; only the wait for an answer counts as in progress.
                release()
                if ip is not None and self._bind_sessions:
                    # The sign-in response itself binds the new session, before
                    # the session middleware outside writes the cookie.
                    self._bind_session(scope)
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if status_seen:
                raise
            await _send_shield_response(scope, send, 413, "Request too large", "The request body is too large.")
            return
        finally:
            release()
            if ip is not None and status_seen:
                shield.note_response(
                    ip, status_seen[0], had_credentials=_carries_credentials(scope), account=account
                )
                shield.schedule_flush()


# ------------------------------------------------------ script injection (CSP)

_CSP_NONCE: contextvars.ContextVar[str] = contextvars.ContextVar("spectre_csp_nonce", default="")


def new_csp_nonce() -> str:
    """Make a fresh nonce the current one; call once per response, before rendering it.

    The Content-Security-Policy only lets inline scripts carrying this nonce
    run. It is unguessable and changes on every response, so a script an
    attacker manages to inject into a page has no way to carry it.
    """

    nonce = secrets.token_urlsafe(18)
    _CSP_NONCE.set(nonce)
    return nonce


def csp_nonce() -> str:
    """This response's nonce, for ``<script nonce="{{ csp_nonce() }}">`` (empty outside a request)."""

    return _CSP_NONCE.get()
