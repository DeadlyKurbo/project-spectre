from __future__ import annotations

import gzip
import importlib
import json
import re
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

import url_scramble

SECRET = "test-scramble-secret"


def _scrambler(**kwargs) -> url_scramble.PathScrambler:
    return url_scramble.PathScrambler(
        SECRET,
        {"director", "files", "content", "api", "moderation", "static", "js", "app.js", "health"},
        {"director", "api", "static", "health"},
        **kwargs,
    )


def test_paths_round_trip_and_readable_paths_are_refused():
    s = _scrambler()
    public = s.scramble_path("/director/files/content")

    assert re.fullmatch(r"(/[a-z2-7]{12}){3}", public)
    assert s.unscramble_path(public) == "/director/files/content"
    assert s.unscramble_path("/director/files/content") is None
    assert s.unscramble_path("/director/") is None
    # Paths the app does not define are left for it to 404 as usual.
    assert s.unscramble_path("/wp-login.php") == "/wp-login.php"
    assert s.unscramble_path("/") == "/"


def test_public_paths_stay_readable():
    s = _scrambler()
    assert s.scramble_path("/health") == "/health"
    assert s.unscramble_path("/health") == "/health"


def test_dynamic_segments_pass_through_unchanged():
    s = _scrambler()
    prefix = s.scramble_path("/api/moderation")
    # JavaScript appends ids (and sometimes literal words) to a scrambled prefix.
    assert s.unscramble_path(f"{prefix}/42/files") == "/api/moderation/42/files"


def test_bot_links_match_the_web_app():
    assert url_scramble.scramble_all_segments("/director/files", SECRET) == _scrambler().scramble_path("/director/files")
    assert url_scramble.scramble_url("https://site.test/director?x=1", SECRET).endswith(
        _scrambler().scramble_path("/director") + "?x=1"
    )
    assert url_scramble.scramble_all_segments("/director", "") == "/director"


def test_text_rewriting_only_touches_same_site_paths():
    s = _scrambler()
    director = s.scramble_path("/director")
    api = s.scramble_path("/api")
    source = (
        '<a href="/director">x</a> fetch(`/api/moderation/${id}`) '
        "url('/static/js/app.js') "
        '"https://discord.com/api/oauth2" "https://site.test/director" "https://other.test/director" '
        "and/director /directory"
    )

    out = s.rewrite_html(source, {"site.test"})

    assert f'href="{director}"' in out
    assert f"fetch(`{s.scramble_path('/api/moderation/')}${{id}}`)" in out
    assert f"url('{s.scramble_path('/static/js/app.js')}')" in out
    assert '"https://discord.com/api/oauth2"' in out
    assert f'"https://site.test{director}"' in out
    assert '"https://other.test/director"' in out
    assert "and/director /directory" in out
    assert api not in out.replace(s.scramble_path("/api/moderation/"), "")


def test_textarea_content_is_left_alone():
    s = _scrambler()
    out = s.rewrite_html('<a href="/director"></a><textarea name="note">see "/director"</textarea>')
    assert '<textarea name="note">see "/director"</textarea>' in out
    assert 'href="/director"' not in out


def test_json_rewrites_only_whole_url_strings():
    s = _scrambler()
    out = s.rewrite_json('{"url": "/director/files?next=/director", "note": "open \\"/director\\" later"}')
    assert f'"url": "{s.scramble_path("/director/files")}?next={s.scramble_path("/director")}"' in out
    assert '"note": "open \\"/director\\" later"' in out


def test_redirect_headers_scramble_paths_and_next_parameters():
    s = _scrambler()
    location = s.scramble_link("/?tos=required&next=%2Fdirector%2Ffiles", {"site.test"})
    assert parse_qs(urlsplit(location).query)["next"] == [s.scramble_path("/director/files")]
    assert s.scramble_link("https://discord.com/api/oauth2/authorize?x=/director", {"site.test"}).endswith("x=/director")


@pytest.fixture
def small_app(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text('fetch("/api/moderation/cases");', encoding="utf-8")
    app = FastAPI()

    @app.get("/director/files")
    async def files():
        return HTMLResponse('<a href="/director/files/content">open</a>')

    @app.get("/director/files/content")
    async def content():
        return JSONResponse({"next": "/director/files"})

    @app.get("/director")
    async def director():
        return RedirectResponse("/director/files")

    @app.get("/api/moderation/cases")
    async def cases():
        return {"ok": True}

    @app.get("/api/moderation")
    async def compressed():
        body = gzip.compress(json.dumps({"next": "/director/files"}).encode("utf-8"))
        return Response(body, media_type="application/json", headers={"Content-Encoding": "gzip"})

    app.mount("/static", StaticFiles(directory=tmp_path), name="static")

    def factory():
        segments, top_level = url_scramble.collect_route_segments(app.routes)
        return url_scramble.PathScrambler(SECRET, segments, top_level)

    app.add_middleware(url_scramble.ScrambleMiddleware, scrambler_factory=factory)
    client = TestClient(app)
    client.get("/")
    return client, factory()


def test_middleware_translates_requests_and_responses(small_app):
    client, s = small_app

    assert client.get("/director/files").status_code == 404
    assert client.get("/static/js/app.js").status_code == 404

    page = client.get(s.scramble_path("/director/files"))
    assert page.status_code == 200
    assert page.text == f'<a href="{s.scramble_path("/director/files/content")}">open</a>'
    assert int(page.headers["content-length"]) == len(page.content)

    redirect = client.get(s.scramble_path("/director"), follow_redirects=False)
    assert redirect.headers["location"] == s.scramble_path("/director/files")

    assert client.get(s.scramble_path("/director/files/content")).json() == {"next": s.scramble_path("/director/files")}
    assert client.get(s.scramble_path("/api/moderation/cases")).json() == {"ok": True}
    assert client.get(s.scramble_path("/api/moderation")).json() == {"next": s.scramble_path("/director/files")}


def test_rewritten_static_files_keep_working_with_browser_caches(small_app):
    client, s = small_app
    url = s.scramble_path("/static/js/app.js")

    first = client.get(url)
    assert first.text == f'fetch("{s.scramble_path("/api/moderation/cases")}");'
    assert first.headers["etag"].endswith(f'{s.etag_suffix}"')

    cached = client.get(url, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304

    # A copy cached before the secret changed must be fetched again.
    stale = client.get(url, headers={"If-None-Match": first.headers["etag"].replace(s.etag_suffix, "-uold")})
    assert stale.status_code == 200


@pytest.fixture
def site(monkeypatch):
    """The real app, reloaded with scrambling on and restored afterwards."""

    monkeypatch.setenv(url_scramble.SECRET_ENV, SECRET)
    original = sys.modules.pop("config_app", None)
    try:
        mod = importlib.import_module("config_app")
        client = TestClient(mod.app, base_url="https://testserver")
        client.get("/")
        yield mod, client, mod._build_url_scrambler()
    finally:
        if original is not None:
            sys.modules["config_app"] = original
        else:
            sys.modules.pop("config_app", None)


def test_site_hides_readable_paths(site):
    _mod, client, s = site
    for path in ("/director", "/admin", "/api/activity", "/static/spectre.css", "/login", "/openapi.json", "/docs"):
        assert client.get(path, follow_redirects=False).status_code == 404, path

    # A scanner cannot tell a hidden page from one that does not exist.
    hidden, missing = client.get("/director"), client.get("/no-such-page")
    assert hidden.content == missing.content
    assert sorted(hidden.headers.keys()) == sorted(missing.headers.keys())

    login = client.get(s.scramble_path("/login"), follow_redirects=False)
    assert login.status_code == 307
    assert urlsplit(login.headers["location"]).netloc == "discord.com"
    assert client.get("/health").json() == {"ok": True}


def test_site_pages_link_only_to_scrambled_paths(site, monkeypatch):
    mod, client, s = site

    async def no_user(_request):
        return None, []

    monkeypatch.setattr(mod, "_load_user_context", no_user)
    body = client.get("/").text
    top = "|".join(sorted(map(re.escape, s.top_level), key=len, reverse=True))
    assert re.findall(rf"[\"'`(=]/(?:{top})(?![\w.~%\-])", body) == []

    links = set(re.findall(r'(?:href|src)="(/[^"#]+)"', body))
    assert links
    for link in links:
        assert client.get(link, follow_redirects=False).status_code != 404, link


def test_site_keeps_search_engines_to_the_landing_page(site):
    _mod, client, s = site
    assert "X-Robots-Tag" not in client.get("/").headers
    assert client.get(s.scramble_path("/features"), follow_redirects=False).headers["X-Robots-Tag"].startswith("noindex")
    assert client.get("/robots.txt").text == "User-agent: *\nAllow: /$\nDisallow: /\n"


def test_api_docs_are_for_admins_only(site, monkeypatch):
    mod, client, s = site
    assert client.get(s.scramble_path("/openapi.json")).status_code == 403
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda _request: True)
    schema = client.get(s.scramble_path("/openapi.json")).json()
    assert s.scramble_path("/api/moderation/cases") in schema["paths"]
    assert "/api/moderation/cases" not in schema["paths"]


def test_without_a_secret_nothing_changes(monkeypatch):
    monkeypatch.delenv(url_scramble.SECRET_ENV, raising=False)
    original = sys.modules.pop("config_app", None)
    try:
        mod = importlib.import_module("config_app")
        client = TestClient(mod.app, base_url="https://testserver")
        assert client.get("/static/spectre.css").status_code == 200
        assert client.get("/health").json() == {"ok": True}
    finally:
        if original is not None:
            sys.modules["config_app"] = original
        else:
            sys.modules.pop("config_app", None)
