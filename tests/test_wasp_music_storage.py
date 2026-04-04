import importlib
import io
import sys
from urllib.parse import urlencode

from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def test_list_uploaded_wasp_tracks_reads_persistent_storage(monkeypatch):
    mod = _load_app(monkeypatch)

    monkeypatch.setattr(
        mod,
        "list_dir",
        lambda prefix, limit=500: (
            [],
            [
                ("alpha-20250102-030405.mp3", 1234),
                ("notes.txt", 25),
                ("beta-20240101-000000.mp3", 4567),
            ],
        ),
    )

    tracks = mod._list_uploaded_wasp_tracks()

    assert [t["filename"] for t in tracks] == [
        "alpha-20250102-030405.mp3",
        "beta-20240101-000000.mp3",
    ]
    assert tracks[0]["url"] == "/media/wasp/alpha-20250102-030405.mp3"
    assert tracks[0]["size"] == "1234"
    assert tracks[0]["updated_at"] == "2025-01-02T03:04:05+00:00"


def test_upload_music_saves_to_persistent_storage(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    async def fake_require_director(_request):
        return {"id": "7", "username": "Director"}, None

    saved: dict[str, object] = {}

    def fake_save_text(path, content, content_type="text/plain; charset=utf-8"):
        saved["path"] = path
        saved["content_type"] = content_type
        saved["payload"] = content.read()

    monkeypatch.setattr(mod, "_require_director", fake_require_director)
    monkeypatch.setattr(mod, "save_text", fake_save_text)

    resp = client.post(
        "/director/website-management",
        data={"action": "upload_music"},
        files={"music_file": ("intro.mp3", io.BytesIO(b"abc123"), "audio/mpeg")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert saved["path"].startswith("assets/wasp_music/intro-")
    assert saved["path"].endswith(".mp3")
    assert saved["content_type"] == "audio/mpeg"
    assert saved["payload"] == b"abc123"


def test_list_uploaded_wasp_tracks_applies_saved_order(monkeypatch):
    mod = _load_app(monkeypatch)

    monkeypatch.setattr(
        mod,
        "list_dir",
        lambda prefix, limit=500: ([], [("bravo.mp3", 10), ("alpha.mp3", 20)]),
    )
    monkeypatch.setattr(
        mod,
        "read_json",
        lambda path: {"order": ["alpha.mp3", "bravo.mp3"]},
    )

    tracks = mod._list_uploaded_wasp_tracks(newest_first=False)

    assert [t["filename"] for t in tracks] == ["alpha.mp3", "bravo.mp3"]


def test_reorder_music_persists_custom_order(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    async def fake_require_director(_request):
        return {"id": "7", "username": "Director"}, None

    saved = {}

    def fake_save_order(order):
        saved["order"] = list(order)

    monkeypatch.setattr(mod, "_require_director", fake_require_director)
    monkeypatch.setattr(
        mod,
        "_list_uploaded_wasp_tracks",
        lambda newest_first=True: [
            {"filename": "alpha.mp3"},
            {"filename": "bravo.mp3"},
        ],
    )
    monkeypatch.setattr(mod, "_save_wasp_music_order", fake_save_order)

    body = urlencode(
        [
            ("action", "reorder_music"),
            ("track_order", "bravo.mp3"),
            ("track_order", "alpha.mp3"),
        ]
    )
    resp = client.post(
        "/director/website-management",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert saved["order"] == ["bravo.mp3", "alpha.mp3"]


def test_reorder_music_legacy_position_fields_still_work(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    async def fake_require_director(_request):
        return {"id": "7", "username": "Director"}, None

    saved = {}

    def fake_save_order(order):
        saved["order"] = list(order)

    monkeypatch.setattr(mod, "_require_director", fake_require_director)
    monkeypatch.setattr(
        mod,
        "_list_uploaded_wasp_tracks",
        lambda newest_first=True: [
            {"filename": "alpha.mp3"},
            {"filename": "bravo.mp3"},
        ],
    )
    monkeypatch.setattr(mod, "_save_wasp_music_order", fake_save_order)

    resp = client.post(
        "/director/website-management",
        data={
            "action": "reorder_music",
            "position_alpha.mp3": "2",
            "position_bravo.mp3": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert saved["order"] == ["bravo.mp3", "alpha.mp3"]
