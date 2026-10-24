import base64
import importlib
import json
import re
import sys

import itsdangerous
from fastapi.testclient import TestClient

from wasp_map_state import WaspMapConflictError, WaspMapOpError, default_wasp_map_state


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    monkeypatch.delenv("PUBLIC_WASP_MAP_READS", raising=False)
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    monkeypatch.setattr(mod, "_list_uploaded_wasp_tracks", lambda newest_first=False: [])
    return mod


def _session_cookie(mod, data):
    signer = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET))
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _sign_in(client, mod, monkeypatch, *, admin):
    cookie = _session_cookie(mod, {"user": {"username": "Kurbo", "global_name": "Kurbo", "id": "84"}})
    client.cookies.set(mod.SESSION_COOKIE_NAME, cookie)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: admin)


def _anonymous(mod, monkeypatch):
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)


def _stub_state(mod, monkeypatch, etag="etag-a"):
    state = default_wasp_map_state()
    monkeypatch.setattr(mod, "load_wasp_map_state", lambda with_etag=False: (state, etag) if with_etag else state)
    return state


def test_state_is_readable_by_any_signed_in_operator(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=False)
    state = _stub_state(mod, monkeypatch)

    response = client.get("/api/wasp-map/state")

    assert response.status_code == 200
    assert response.headers["etag"] == '"etag-a"'
    assert response.json() == state


def test_state_returns_not_modified_for_matching_etag(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=False)
    _stub_state(mod, monkeypatch, etag="same")

    response = client.get("/api/wasp-map/state", headers={"If-None-Match": '"same"'})

    assert response.status_code == 304
    assert response.headers["etag"] == '"same"'


def test_state_requires_sign_in(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _anonymous(mod, monkeypatch)
    _stub_state(mod, monkeypatch)

    assert client.get("/api/wasp-map/state").status_code == 401


def test_public_reads_flag_opens_state_to_everyone(monkeypatch):
    mod = _load_app(monkeypatch)
    monkeypatch.setenv("PUBLIC_WASP_MAP_READS", "1")
    client = TestClient(mod.app)
    _anonymous(mod, monkeypatch)
    _stub_state(mod, monkeypatch)

    assert client.get("/api/wasp-map/state").status_code == 200


def test_ops_require_admin(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=False)
    monkeypatch.setattr(mod, "update_wasp_map_state", lambda ops, actor="": (_ for _ in ()).throw(AssertionError("must not save")))

    response = client.post("/api/wasp-map/ops", json={"ops": [{"op": "meta", "patch": {"operation": "X"}}]})

    assert response.status_code == 403


def test_ops_apply_as_admin_and_record_actor(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=True)
    capture = {}
    saved = default_wasp_map_state()

    def fake_update(ops, actor=""):
        capture.update(ops=ops, actor=actor)
        return saved, "etag-b"

    monkeypatch.setattr(mod, "update_wasp_map_state", fake_update)
    ops = [{"op": "upsert", "collection": "units", "item": {"name": "Alpha", "lat": 1, "lng": 2}}]

    response = client.post("/api/wasp-map/ops", json={"ops": ops})

    assert response.status_code == 200
    assert response.headers["etag"] == '"etag-b"'
    assert response.json() == saved
    assert capture == {"ops": ops, "actor": "Kurbo"}


def test_bad_ops_return_400_and_conflicts_return_409(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=True)

    def bad(ops, actor=""):
        raise WaspMapOpError("Unknown operation: 'x'")

    monkeypatch.setattr(mod, "update_wasp_map_state", bad)
    response = client.post("/api/wasp-map/ops", json={"ops": [{"op": "x"}]})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown operation: 'x'"

    def busy(ops, actor=""):
        raise WaspMapConflictError("try again")

    monkeypatch.setattr(mod, "update_wasp_map_state", busy)
    assert client.post("/api/wasp-map/ops", json={"ops": [{"op": "meta", "patch": {}}]}).status_code == 409


def test_retired_endpoints_are_gone(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=True)

    assert client.put("/api/wasp-map/state", json={}).status_code == 405
    assert client.post("/api/wasp-map/simulation/start", json={}).status_code == 404
    assert client.get("/api/tme/catalog-cities").status_code == 404
    assert client.get("/wasp-galaxy").status_code == 404


def _script_sources(html):
    return re.findall(r'<script[^>]+src="([^"]+)"', html)


def test_map_page_loads_only_self_hosted_scripts(monkeypatch):
    """The site CSP only allows same-origin scripts, so the map must not use a CDN."""
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=True)

    for path in ("/wasp-map", "/mission-debrief-sz"):
        response = client.get(path)
        assert response.status_code == 200
        sources = _script_sources(response.text)
        assert any(src.startswith("/static/vendor/leaflet/leaflet.js") for src in sources)
        assert any(src.startswith("/static/js/wasp_map.js") for src in sources)
        assert all(src.startswith("/") for src in sources), sources
        assert "wm-toolbar" in response.text
        assert "wm-gate" not in response.text


def test_map_page_shows_sign_in_gate_and_hides_tools_for_visitors(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _anonymous(mod, monkeypatch)

    response = client.get("/wasp-map")

    assert response.status_code == 200
    assert 'href="/login?next=/wasp-map"' in response.text
    assert "wm-toolbar" not in response.text


def test_map_page_for_signed_in_viewer_has_no_tools(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _sign_in(client, mod, monkeypatch, admin=False)

    response = client.get("/wasp-map")

    assert response.status_code == 200
    assert "wm-toolbar" not in response.text
    assert "wm-gate" not in response.text
    assert '"canView": true' in response.text
    assert '"canEdit": false' in response.text
