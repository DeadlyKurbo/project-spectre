"""Minimal threaded HTTP server for platform keepalive checks."""

from __future__ import annotations

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


def start_keepalive() -> None:
    """Start the background HTTP server."""
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

