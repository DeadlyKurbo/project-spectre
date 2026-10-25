import importlib
import socket
import time


def _http_get(port: int) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        return conn.recv(1024)


def test_keepalive_skips_application_port(monkeypatch):
    app_socket = socket.socket()
    app_socket.bind(("0.0.0.0", 0))
    app_port = app_socket.getsockname()[1]
    app_socket.close()

    monkeypatch.setenv("PORT", str(app_port))
    monkeypatch.delenv("KEEPALIVE_PORT", raising=False)

    keepalive = importlib.reload(importlib.import_module("keepalive"))
    keepalive_port = keepalive._pick_keepalive_port()

    keepalive.start_keepalive()
    time.sleep(0.05)

    probe = socket.socket()
    probe.bind(("0.0.0.0", app_port))
    probe.close()

    assert b"OK" in _http_get(keepalive_port)


def test_keepalive_prefers_dedicated_port(monkeypatch):
    app_socket = socket.socket()
    app_socket.bind(("0.0.0.0", 0))
    app_port = app_socket.getsockname()[1]
    app_socket.close()

    keepalive_socket = socket.socket()
    keepalive_socket.bind(("0.0.0.0", 0))
    keepalive_port = keepalive_socket.getsockname()[1]
    keepalive_socket.close()

    monkeypatch.setenv("PORT", str(app_port))
    monkeypatch.setenv("KEEPALIVE_PORT", str(keepalive_port))

    keepalive = importlib.reload(importlib.import_module("keepalive"))
    keepalive.start_keepalive()
    time.sleep(0.05)

    probe = socket.socket()
    probe.bind(("0.0.0.0", app_port))
    probe.close()

    assert b"OK" in _http_get(keepalive_port)
