import importlib
import socket

def test_start_keepalive_port_in_use(monkeypatch):
    sock = socket.socket()
    sock.bind(("0.0.0.0", 0))
    port = sock.getsockname()[1]
    monkeypatch.setenv("PORT", str(port))
    keepalive = importlib.reload(importlib.import_module("keepalive"))
    # Should not raise even though port is already bound
    keepalive.start_keepalive()
    sock.close()
