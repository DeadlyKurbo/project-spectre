"""Minimal threaded HTTP server for platform keepalive checks."""

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    """Simple request handler that responds to health checks."""

    def do_GET(self) -> None:  # pragma: no cover - trivial server
        if self.path in {"/", "/health", "/ping"}:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        """Suppress default logging to keep output clean."""
        return


def _pick_keepalive_port() -> int:
    """Choose a port for the keepalive server that will not clash with the app."""

    app_port_env = os.getenv("PORT")
    keepalive_env = os.getenv("KEEPALIVE_PORT")

    app_port = int(app_port_env) if app_port_env else None
    if keepalive_env:
        keepalive_port = int(keepalive_env)
        if keepalive_port == app_port:
            logger = logging.getLogger("spectre")
            keepalive_port = _offset_port(app_port)
            logger.warning(
                "KEEPALIVE_PORT matches application PORT %s; using %s instead",
                app_port,
                keepalive_port,
            )
        return keepalive_port

    if app_port:
        return _offset_port(app_port)

    return 8081


def _offset_port(app_port: int | None) -> int:
    """Pick an adjacent port, staying in range and avoiding 0."""

    if not app_port:
        return 8081

    if app_port >= 65535:
        return 65534

    return max(app_port + 1, 1)


def start_keepalive() -> None:
    """Start the background HTTP server."""
    port = _pick_keepalive_port()
    try:
        server = HTTPServer(("0.0.0.0", port), Handler)
    except OSError as exc:  # pragma: no cover - defensive guard
        logging.getLogger("spectre").warning(
            "Keepalive server failed to start on port %s: %s", port, exc
        )
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

