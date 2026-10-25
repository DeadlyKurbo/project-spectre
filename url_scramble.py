"""Opaque public URLs for the website.

With ``URL_SCRAMBLE_SECRET`` set, every path segment the site itself defines
(route names, static folders and file names) is published as a keyed hash of
itself, so ``/director/files`` is served as something like
``/q4m2x7ka9c1t/b7fz3k0wd2pe``. The readable paths answer 404, which leaves
search-engine dorks and scanners probing for ``/admin``, ``/director`` or
``/api/...`` with nothing to find. Tokens depend only on the secret, so URLs
survive redeploys; changing the secret moves every URL at once.

The middleware works in both directions so the rest of the app keeps using
the real paths: incoming scrambled paths are translated back before routing,
and links in HTML, CSS, JavaScript, JSON and redirect headers are scrambled on
the way out.

Print the public address of a page with ``python url_scramble.py /director``.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import os
import re
import sys
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

SECRET_ENV = "URL_SCRAMBLE_SECRET"
TOKEN_LENGTH = 12

# Paths that keep their readable form: the landing page needs no segment, the
# OAuth callback is registered with Discord and the health check with Railway.
DEFAULT_PUBLIC_PATHS = frozenset({"/health", "/auth/callback", "/callback", "/robots.txt"})

_SEGMENT_CHARS = r"[\w.~%\-]"
# Responses buffered past this size are sent untouched rather than held in memory.
_MAX_REWRITE_BYTES = 8 * 1024 * 1024
_REWRITE_TYPES = (
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/json",
    "application/manifest+json",
    "image/svg+xml",
)
_TEXTAREA_RE = re.compile(r"(<textarea\b.*?</textarea\s*>)", re.IGNORECASE | re.DOTALL)
# Requests for readable paths are routed here; no route matches it.
_UNKNOWN_PATH = "/.scrambled-not-found"


def configured_secret() -> str | None:
    value = (os.getenv(SECRET_ENV) or "").strip()
    return value or None


def segment_token(secret: str, segment: str) -> str:
    """Return the public stand-in for one real path segment."""

    digest = hmac.new(secret.encode("utf-8"), segment.encode("utf-8"), hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii")[:TOKEN_LENGTH].lower()


def scramble_all_segments(path: str, secret: str | None = None) -> str:
    """Scramble every segment of a path made only of literal route segments.

    For callers without access to the app's route table, such as the Discord
    bot building a link to ``/spectre/archive``. Returns ``path`` unchanged
    when scrambling is off.
    """

    secret = secret if secret is not None else configured_secret()
    if not secret or not path.startswith("/") or path in DEFAULT_PUBLIC_PATHS:
        return path
    return "/".join(segment_token(secret, part) if part else part for part in path.split("/"))


def scramble_url(url: str, secret: str | None = None) -> str:
    """Scramble the path of an absolute or relative URL, keeping query and host."""

    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=scramble_all_segments(parts.path, secret)))


def _iter_routes(routes: Iterable[Any], prefix: str = ""):
    for route in routes:
        # Recent FastAPI versions keep an included router as a single entry
        # wrapping the original one; its routes already carry the router's own
        # prefix, plus whatever include_router() added.
        included = getattr(route, "original_router", None)
        if included is not None:
            extra = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _iter_routes(included.routes, prefix + extra)
            continue
        path = getattr(route, "path", None)
        if isinstance(path, str):
            yield prefix + path, route


def collect_route_segments(routes: Iterable[Any]) -> tuple[set[str], set[str]]:
    """Return ``(segments, top_level)`` for every literal path segment the app serves.

    Static mounts contribute the names of their folders and files too.
    """

    segments: set[str] = set()
    top_level: set[str] = set()
    for path, route in _iter_routes(routes):
        if not path.startswith("/"):
            continue
        parts = [part for part in path.split("/") if part]
        for index, part in enumerate(parts):
            if "{" in part:
                continue
            segments.add(part)
            if index == 0:
                top_level.add(part)
        directory = getattr(getattr(route, "app", None), "directory", None)
        if directory and os.path.isdir(directory):
            for _current, dirnames, filenames in os.walk(directory):
                segments.update(dirnames)
                segments.update(filenames)
    return segments, top_level


class PathScrambler:
    """Translate between real paths and their scrambled public form."""

    def __init__(
        self,
        secret: str,
        segments: Iterable[str],
        top_level: Iterable[str],
        *,
        public_paths: Iterable[str] = DEFAULT_PUBLIC_PATHS,
    ) -> None:
        self.top_level = frozenset(part for part in top_level if part)
        words = (set(segments) | self.top_level) - {""}
        self._forward = {word: segment_token(secret, word) for word in words}
        self._reverse = {token: word for word, token in self._forward.items() if token not in words}
        self.public_paths = frozenset(public_paths)
        self.etag_suffix = "-u" + segment_token(secret, "\x00etag")[:8]

        top = "|".join(re.escape(word) for word in sorted(self.top_level, key=len, reverse=True))
        path = rf"/(?:{top})(?!{_SEGMENT_CHARS})(?:/{_SEGMENT_CHARS}+)*/?"
        host = r"(?P<host>[A-Za-z0-9.\-]+(?::\d+)?)"
        # A path literal starts after a quote, bracket, '=', whitespace and the
        # like, never mid-word, so "/admin" inside "https://other.site/admin"
        # or a relative "x/admin" is left alone. Same-site absolute URLs are
        # matched with their host and checked in the replacement.
        self._text_re = re.compile(
            rf"(?:(?P<abs>(?:https?:)?//{host})|(?<![^\s\"'`(=,>{{}}\[;]))(?P<path>{path})"
            if top
            else r"(?!x)x"
        )
        # JSON values are data as much as links, so only strings that are a
        # URL from start to end are rewritten there.
        self._json_re = re.compile(
            rf"\"(?P<abs>(?:https?:)?//{host})?(?P<path>{path})(?P<tail>[?#][^\"\\]*)?\""
            if top
            else r"(?!x)x"
        )

    @property
    def enabled(self) -> bool:
        return bool(self.top_level)

    def token(self, segment: str) -> str | None:
        return self._forward.get(segment)

    def scramble_path(self, path: str) -> str:
        """Scramble a real absolute path (without query string)."""

        if not path.startswith("/") or path in self.public_paths:
            return path
        parts = path.split("/")
        if parts[1] not in self.top_level:
            return path
        return "/".join(self._forward.get(part, part) for part in parts)

    def unscramble_path(self, path: str) -> str | None:
        """Translate an incoming path; ``None`` means it must not be served."""

        parts = path.split("/")
        if len(parts) < 2:
            return path
        first = parts[1]
        if first in self._reverse:
            return "/".join(self._reverse.get(part, part) for part in parts)
        if path in self.public_paths or first not in self.top_level:
            return path
        return None

    def scramble_link(self, value: str, own_hosts: Iterable[str] = ()) -> str:
        """Scramble a URL as it appears in a header, keeping foreign hosts untouched."""

        parts = urlsplit(value)
        if parts.scheme and parts.scheme.lower() not in {"http", "https"}:
            return value
        if parts.netloc and parts.netloc.lower() not in {host.lower() for host in own_hosts}:
            return value
        return urlunsplit(
            parts._replace(path=self.scramble_path(parts.path), query=self._scramble_query(parts.query))
        )

    def _scramble_query(self, query: str) -> str:
        # Only "?next=/director"-style parameters carry paths.
        if "/" not in query and "%2f" not in query.lower():
            return query
        pairs = parse_qsl(query, keep_blank_values=True)
        changed = False
        rewritten = []
        for key, value in pairs:
            if value.startswith("/"):
                path, sep, rest = value.partition("?")
                new_value = self.scramble_path(path) + sep + rest
                changed = changed or new_value != value
                value = new_value
            rewritten.append((key, value))
        return urlencode(rewritten, quote_via=quote) if changed else query

    def rewrite_text(self, text: str, own_hosts: Iterable[str] = ()) -> str:
        """Scramble same-site path literals in HTML, CSS or JavaScript."""

        hosts = {host.lower() for host in own_hosts}

        def _replace(match: re.Match[str]) -> str:
            absolute = match.group("abs")
            if absolute and match.group("host").lower() not in hosts:
                return match.group(0)
            return (absolute or "") + self.scramble_path(match.group("path"))

        return self._text_re.sub(_replace, text)

    def rewrite_html(self, text: str, own_hosts: Iterable[str] = ()) -> str:
        """Like :meth:`rewrite_text`, leaving editable ``<textarea>`` content alone."""

        pieces = _TEXTAREA_RE.split(text)
        return "".join(
            piece if index % 2 else self.rewrite_text(piece, own_hosts) for index, piece in enumerate(pieces)
        )

    def rewrite_json(self, text: str, own_hosts: Iterable[str] = ()) -> str:
        """Scramble JSON strings that are a same-site URL in their entirety."""

        hosts = {host.lower() for host in own_hosts}

        def _replace(match: re.Match[str]) -> str:
            absolute = match.group("abs")
            if absolute and match.group("host").lower() not in hosts:
                return match.group(0)
            tail = match.group("tail") or ""
            return '"' + (absolute or "") + self.scramble_path(match.group("path")) + self.rewrite_text(tail, hosts) + '"'

        return self._json_re.sub(_replace, text)


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _own_hosts(scope: dict[str, Any], extra: Iterable[str]) -> set[str]:
    hosts = {host.lower() for host in extra if host}
    for key, value in scope.get("headers") or []:
        if key in (b"host", b"x-forwarded-host"):
            hosts.update(part.strip().lower() for part in value.decode("latin-1").split(",") if part.strip())
    return hosts


class ScrambleMiddleware:
    """ASGI middleware applying a :class:`PathScrambler` to requests and responses.

    ``scrambler_factory`` is called on the first request, once every route is
    registered, and may return ``None`` to leave the app untouched.
    """

    def __init__(
        self,
        app: Callable,
        *,
        scrambler_factory: Callable[[], PathScrambler | None],
        own_hosts: Iterable[str] = (),
        json_passthrough_prefixes: Iterable[str] = (),
    ) -> None:
        self.app = app
        self._factory = scrambler_factory
        self._scrambler: PathScrambler | None = None
        self._built = False
        self._extra_hosts = tuple(own_hosts)
        self._json_passthrough = tuple(json_passthrough_prefixes)

    @property
    def scrambler(self) -> PathScrambler | None:
        if not self._built:
            scrambler = self._factory()
            self._scrambler = scrambler if scrambler is not None and scrambler.enabled else None
            self._built = True
        return self._scrambler

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket") or self.scrambler is None:
            await self.app(scope, receive, send)
            return
        scrambler = self.scrambler

        path = scope.get("path") or "/"
        real_path = scrambler.unscramble_path(path)
        if real_path is None:
            # Let the app answer as it does for any path it does not know, so a
            # readable path cannot be told apart from one that never existed.
            real_path = _UNKNOWN_PATH
        if real_path != path:
            # The security shield still checks what the client actually asked for.
            scope = dict(
                scope, path=real_path, raw_path=quote(real_path).encode("ascii"), **{"spectre.public_path": path}
            )
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        etag_suffix = scrambler.etag_suffix.encode("ascii")
        headers = scope.get("headers") or []
        # Rewritten responses carry a marked ETag so a new secret never matches
        # a copy cached under the old one; unmark it for the app's own check.
        sent_marked_etag = any(key == b"if-none-match" and etag_suffix in value for key, value in headers)
        if sent_marked_etag:
            scope = dict(
                scope,
                headers=[
                    (key, value.replace(etag_suffix, b"") if key == b"if-none-match" else value)
                    for key, value in headers
                ],
            )

        extensions = scope.get("extensions") or {}
        if "http.response.pathsend" in extensions:
            # Files must arrive as body chunks so their links can be rewritten.
            scope = dict(scope, extensions={k: v for k, v in extensions.items() if k != "http.response.pathsend"})

        own_hosts = _own_hosts(scope, self._extra_hosts)
        is_head = scope.get("method") == "HEAD"
        json_passthrough = real_path.startswith(self._json_passthrough) if self._json_passthrough else False
        state: dict[str, Any] = {"start": None, "buffer": [], "size": 0, "rewrite": False}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers") or [])
                content_type = (_header(response_headers, b"content-type") or b"").decode("latin-1").lower()
                encoding = (_header(response_headers, b"content-encoding") or b"identity").decode("latin-1").lower()
                length = _header(response_headers, b"content-length")
                rewrite = (
                    message["status"] not in (206, 304)
                    and content_type.startswith(_REWRITE_TYPES)
                    and encoding in ("identity", "gzip")
                    and not (json_passthrough and "json" in content_type)
                    and (length is None or int(length) <= _MAX_REWRITE_BYTES)
                )
                new_headers = []
                for key, value in response_headers:
                    lower = key.lower()
                    if lower == b"location":
                        value = scrambler.scramble_link(value.decode("latin-1"), own_hosts).encode("latin-1")
                    elif (
                        lower == b"etag"
                        and (rewrite or (message["status"] == 304 and sent_marked_etag))
                        and value.endswith(b'"')
                    ):
                        value = value[:-1] + etag_suffix + b'"'
                    elif lower == b"content-length" and rewrite and is_head:
                        continue
                    new_headers.append((key, value))
                message = dict(message, headers=new_headers)
                if not rewrite or is_head:
                    await send(message)
                    return
                state.update(start=message, rewrite=True, content_type=content_type, encoding=encoding)
                return

            if message["type"] != "http.response.body" or not state["rewrite"]:
                await send(message)
                return

            state["buffer"].append(message.get("body", b""))
            state["size"] += len(message.get("body", b""))
            if state["size"] > _MAX_REWRITE_BYTES:
                # Too large to hold: send what we have untouched and stream the rest.
                state["rewrite"] = False
                await send(state["start"])
                await send({"type": "http.response.body", "body": b"".join(state["buffer"]), "more_body": True})
                state["buffer"] = []
                if not message.get("more_body", False):
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            if message.get("more_body", False):
                return

            body = self._rewrite_body(b"".join(state["buffer"]), state["content_type"], state["encoding"], own_hosts)
            start = state["start"]
            start_headers = [(key, value) for key, value in start["headers"] if key.lower() != b"content-length"]
            start_headers.append((b"content-length", str(len(body)).encode("ascii")))
            await send(dict(start, headers=start_headers))
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive, send_wrapper)

    def _rewrite_body(self, body: bytes, content_type: str, encoding: str, own_hosts: set[str]) -> bytes:
        scrambler = self._scrambler
        assert scrambler is not None
        raw = gzip.decompress(body) if encoding == "gzip" else body
        charset_match = re.search(r"charset=([\w\-]+)", content_type)
        charset = charset_match.group(1) if charset_match else "utf-8"
        try:
            text = raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return body
        if "json" in content_type:
            rewritten = scrambler.rewrite_json(text, own_hosts)
        elif content_type.startswith("text/html"):
            rewritten = scrambler.rewrite_html(text, own_hosts)
        else:
            rewritten = scrambler.rewrite_text(text, own_hosts)
        if rewritten == text:
            return body
        encoded = rewritten.encode(charset)
        return gzip.compress(encoded, compresslevel=5) if encoding == "gzip" else encoded


def main(argv: list[str]) -> int:
    secret = configured_secret()
    if not secret:
        print(f"{SECRET_ENV} is not set, so URLs are not scrambled.", file=sys.stderr)
        return 1
    for path in argv or ["/dashboard", "/admin", "/director", "/owner"]:
        print(f"{path} -> {scramble_url(path, secret)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
