"""The W.A.S.P. player is mounted on every page, including the lockdown and sanction screens."""

import importlib
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PLAYER_INCLUDE = re.compile(r'\{%\s*include\s+"_wasp_player\.html"\s*%\}')
PLAYER_STYLESHEET = '<link rel="stylesheet" href="/static/wasp_global_player.css?v='
NOT_SERVED = {"mission_debrief_sz.html"}
TRACK = {"filename": "intro.mp3", "url": "/media/wasp/intro.mp3"}


def _page_templates():
    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name.startswith("_") or "Name clash" in path.name or path.name in NOT_SERVED:
            continue
        yield path


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _locked(mod):
    return lambda: {
        "enabled": True,
        "message": mod.SITE_LOCK_MESSAGE_DEFAULT,
        "actor": None,
        "enabled_at": None,
    }


@pytest.mark.parametrize("path", list(_page_templates()), ids=lambda p: p.name)
def test_every_page_mounts_the_player(path):
    text = path.read_text(encoding="utf-8")
    assert len(PLAYER_INCLUDE.findall(text)) == 1, f"{path.name} must include _wasp_player.html once"
    head = text.split("</head>", 1)[0]
    assert PLAYER_STYLESHEET in head, f"{path.name} must link wasp_global_player.css in <head>"
    # The include is the one place that loads and mounts the player.
    assert "wasp_audio.js" not in text and "mountGlobalWaspPlayer" not in text


def test_player_uses_route_tracks_or_falls_back_to_the_global(monkeypatch):
    mod = _load_app(monkeypatch)
    monkeypatch.setattr(mod, "_list_uploaded_wasp_tracks", lambda newest_first=True: [TRACK])
    player = mod.templates.get_template("_wasp_player.html")

    assert "/media/wasp/intro.mp3" in player.render()
    from_route = player.render(wasp_music_tracks=[{"filename": "route.mp3", "url": "/media/wasp/route.mp3"}])
    assert "/media/wasp/route.mp3" in from_route
    assert "/media/wasp/intro.mp3" not in from_route
    assert "defaultVolume" not in from_route


def test_player_passes_a_page_default_volume(monkeypatch):
    mod = _load_app(monkeypatch)
    page = mod.templates.env.from_string(
        '{% with wasp_player_default_volume = 10 %}{% include "_wasp_player.html" %}{% endwith %}'
    )
    assert "defaultVolume: 10" in page.render(wasp_music_tracks=[TRACK])


def test_maintenance_page_carries_the_player(monkeypatch):
    mod = _load_app(monkeypatch)
    monkeypatch.setattr(mod, "get_site_lock_state", _locked(mod))
    monkeypatch.setattr(mod, "_list_uploaded_wasp_tracks", lambda newest_first=True: [TRACK])
    client = TestClient(mod.app)

    resp = client.get("/")
    assert resp.status_code == 503
    assert "mountGlobalWaspPlayer" in resp.text
    assert "/media/wasp/intro.mp3" in resp.text
    assert "/static/wasp_global_player.css" in resp.text


def test_lockdown_lets_only_the_player_files_through(monkeypatch):
    mod = _load_app(monkeypatch)
    monkeypatch.setattr(mod, "get_site_lock_state", _locked(mod))

    def missing_track(key):
        raise FileNotFoundError(key)

    monkeypatch.setattr(mod, "_wasp_track_stat", missing_track)
    client = TestClient(mod.app)

    for path in ("/static/js/wasp_audio.js", "/static/js/wasp_global_player.js", "/static/wasp_global_player.css"):
        assert client.get(path).status_code == 200, path
    # Reaches the track route (unknown track), not the maintenance screen.
    assert client.get("/media/wasp/intro.mp3").status_code == 404
    for path in ("/static/js/wasp_map.js", "/media/wasp/nested/intro.mp3", "/media/wasp/"):
        assert client.get(path).status_code == 503, path


def test_sanction_page_carries_the_player(monkeypatch):
    mod = _load_app(monkeypatch)
    monkeypatch.setattr(mod, "_list_uploaded_wasp_tracks", lambda newest_first=True: [TRACK])

    resp = mod._build_website_block_response({"sanction": "ban", "reason": "Spam"})
    body = resp.body.decode()
    assert "mountGlobalWaspPlayer" in body
    assert "/media/wasp/intro.mp3" in body


def test_director_console_links_back_to_the_site_and_admin_console():
    text = (TEMPLATES / "director.html").read_text(encoding="utf-8")
    topbar = text.split('<div class="topbar">', 1)[1].split('<div class="layout">', 1)[0]
    assert '<a href="/">Back to site</a>' in topbar
    assert '<a href="/admin">Admin console</a>' in topbar
