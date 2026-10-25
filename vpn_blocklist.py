"""Free VPN, data-centre and Tor exit lists, used to keep banned ZETA guests from hopping IPs.

The lists come from X4BNet/lists_vpn (VPN providers and hosting networks, as
CIDR ranges) and the Tor Project's bulk exit list. ``refresh`` downloads them
and caches the result in storage, so a restart works before the next download;
``classify`` answers in O(log n) from merged, sorted ranges.

When no list has loaded yet ``classify`` returns ``None`` for every address:
the check fails open rather than locking everyone out.
"""

from __future__ import annotations

import bisect
import ipaddress
import logging
import threading
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger(__name__)

SOURCES: dict[str, list[str]] = {
    "vpn": [
        "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/vpn/ipv4.txt",
        "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/vpn/ipv6.txt",
    ],
    "datacenter": [
        "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/datacenter/ipv4.txt",
        "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/datacenter/ipv6.txt",
    ],
    "tor": ["https://check.torproject.org/torbulkexitlist"],
}
CACHE_KEY = "zeta/blocklists.json"
REFRESH_SECONDS = 24 * 3600
_DOWNLOAD_TIMEOUT = 30.0


class _Ranges:
    """Merged ``[start, end]`` integer ranges for one IP version."""

    def __init__(self, networks: Iterable[tuple[int, int]]) -> None:
        merged: list[list[int]] = []
        for start, end in sorted(networks):
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        self.starts = [start for start, _end in merged]
        self.ends = [end for _start, end in merged]

    def __contains__(self, value: int) -> bool:
        index = bisect.bisect_right(self.starts, value) - 1
        return index >= 0 and value <= self.ends[index]

    def __len__(self) -> int:
        return len(self.starts)


class Blocklist:
    def __init__(self, lists: dict[str, Iterable[str]]) -> None:
        self.ranges: dict[str, dict[int, _Ranges]] = {}
        for name, lines in lists.items():
            by_version: dict[int, list[tuple[int, int]]] = {4: [], 6: []}
            for line in lines:
                entry = line.split("#", 1)[0].strip()
                if not entry:
                    continue
                try:
                    network = ipaddress.ip_network(entry, strict=False)
                except ValueError:
                    continue
                by_version[network.version].append(
                    (int(network.network_address), int(network.broadcast_address))
                )
            self.ranges[name] = {version: _Ranges(nets) for version, nets in by_version.items()}

    def classify(self, ip: str | None) -> str | None:
        """The list ``ip`` is on (``tor``, ``vpn`` or ``datacenter``), else ``None``."""

        try:
            address = ipaddress.ip_address(str(ip or "").strip())
        except ValueError:
            return None
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            return None
        value = int(address)
        for name in ("tor", "vpn", "datacenter"):
            ranges = self.ranges.get(name, {}).get(address.version)
            if ranges is not None and value in ranges:
                return name
        return None

    def __len__(self) -> int:
        return sum(len(r) for by_version in self.ranges.values() for r in by_version.values())


_current = Blocklist({})
_lock = threading.Lock()


def current() -> Blocklist:
    return _current


def install(lists: dict[str, Iterable[str]]) -> Blocklist:
    """Replace the active lists (also used by tests)."""

    global _current
    blocklist = Blocklist(lists)
    with _lock:
        _current = blocklist
    return blocklist


def classify(ip: str | None) -> str | None:
    return _current.classify(ip)


def load_cached(backend) -> datetime | None:
    """Install the lists saved by the last refresh; return when they were fetched."""

    try:
        payload = backend.read_json(CACHE_KEY)
    except FileNotFoundError:
        return None
    lists = (payload or {}).get("lists") if isinstance(payload, dict) else None
    if not isinstance(lists, dict) or not lists:
        return None
    install({str(name): [str(line) for line in lines or []] for name, lines in lists.items()})
    try:
        return datetime.fromisoformat(str(payload.get("fetched_at")))
    except ValueError:
        return None


async def refresh(backend, client) -> bool:
    """Download every list, install them and cache them. Keeps the old lists on any failure."""

    lists: dict[str, list[str]] = {}
    for name, urls in SOURCES.items():
        lines: list[str] = []
        for url in urls:
            try:
                response = await client.get(url, timeout=_DOWNLOAD_TIMEOUT)
                response.raise_for_status()
            except Exception as exc:
                logger.warning("Could not download the %s blocklist from %s: %s", name, url, exc)
                return False
            lines.extend(line.strip() for line in response.text.splitlines() if line.strip())
        lists[name] = lines
    blocklist = install(lists)
    try:
        backend.write_json(
            CACHE_KEY, {"fetched_at": datetime.now(timezone.utc).isoformat(), "lists": lists}
        )
    except Exception:  # pragma: no cover - the lists are installed either way
        logger.warning("Could not cache the VPN blocklists", exc_info=True)
    logger.info("Loaded %d VPN, data-centre and Tor ranges", len(blocklist))
    return True


__all__ = ["Blocklist", "CACHE_KEY", "SOURCES", "classify", "current", "install", "load_cached", "refresh"]
