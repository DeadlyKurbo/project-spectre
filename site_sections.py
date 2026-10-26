"""The parts of the website admins can take offline one at a time.

Each section owns the URL prefixes of its pages and of the APIs behind them,
so switching it off closes all of it at once. The landing page, sign-in, the
admin and director consoles, static files and the W.A.S.P. player belong to
no section and stay reachable; the site-wide lockdown still covers everything.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSection:
    key: str
    label: str
    description: str
    prefixes: tuple[str, ...]


SITE_SECTIONS: tuple[SiteSection, ...] = (
    SiteSection("features", "Features", "The systems overview page.", ("/features",)),
    SiteSection("about", "About", "The about page.", ("/about",)),
    SiteSection(
        "dashboard",
        "Bot dashboard",
        "Server picker, server panels and guild configuration.",
        ("/dashboard", "/server", "/panel", "/configs", "/discord", "/links"),
    ),
    SiteSection(
        "spectre_archive",
        "SPECTRE archive",
        "The internet archive and the personnel board.",
        ("/spectre/archive", "/api/spectre/archive", "/dossiers"),
    ),
    SiteSection("wasp", "W.A.S.P. hub", "The W.A.S.P. landing page.", ("/wasp",)),
    SiteSection("wasp_archive", "W.A.S.P. archive", "The W.A.S.P. archive and its search.", ("/wasp/archive", "/api/wasp/archive")),
    SiteSection(
        "wasp_map",
        "W.A.S.P. map",
        "The interactive map and mission debrief.",
        ("/wasp-map", "/api/wasp-map", "/mission-debrief-sz"),
    ),
    SiteSection("alice", "A.L.I.C.E.", "The A.L.I.C.E. terminal and its commands.", ("/alice", "/api/alice")),
    SiteSection(
        "zeta",
        "Project ZETA",
        "The operator chatroom, DMs and chat bans.",
        ("/zeta", "/api/zeta", "/alice/chat", "/api/alice/chat"),
    ),
    SiteSection(
        "contact",
        "Contact & support chat",
        "The admin team page and support chat.",
        ("/admin-team", "/api/support-chat"),
    ),
    SiteSection("pyro_war", "Pyro War", "The Pyro War theatre map.", ("/operations/pyro-war",)),
    SiteSection("helldivers", "Helldivers", "The Helldivers page and war summary.", ("/helldivers", "/api/hd2")),
    SiteSection("fleet", "Fleet manager", "The fleet roster.", ("/fleet",)),
    SiteSection("fdd_specs", "FDD tech specs", "Ship tech specs and their images.", ("/fdd",)),
)

SECTIONS_BY_KEY = {section.key: section for section in SITE_SECTIONS}

# Longest prefix first, so /alice/chat belongs to ZETA rather than A.L.I.C.E.
_PREFIXES = sorted(
    ((prefix, section) for section in SITE_SECTIONS for prefix in section.prefixes),
    key=lambda item: len(item[0]),
    reverse=True,
)


def section_for_path(path: str) -> SiteSection | None:
    """Return the section serving ``path``, matching whole path segments only."""

    for prefix, section in _PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return section
    return None
