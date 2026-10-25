"""Every page shares the SPECTRE green theme except W.A.S.P."""

import importlib
import sys
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
THEME_LINK = '/static/spectre_theme.css'
OWN_THEME = {"wasp_landing.html", "wasp_map.html"}


def _page_templates():
    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name.startswith("_"):
            continue
        yield path


@pytest.mark.parametrize("path", list(_page_templates()), ids=lambda p: p.name)
def test_pages_use_shared_theme_except_wasp(path):
    linked = THEME_LINK in path.read_text(encoding="utf-8")
    if path.name in OWN_THEME:
        assert not linked, f"{path.name} keeps its own theme and must not load spectre_theme.css"
    else:
        assert linked, f"{path.name} must load spectre_theme.css"


def test_site_accent_is_spectre_green(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    assert mod.ACCENT == "#8ea784"
