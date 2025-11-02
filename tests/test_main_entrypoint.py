"""Tests for the main module entrypoint helpers."""

from __future__ import annotations

import importlib

import main


def _reload_main() -> None:
    importlib.reload(main)


def test_main_starts_keepalive_and_runtime(monkeypatch):
    _reload_main()

    calls: list[str] = []

    def fake_keepalive() -> None:
        calls.append("keepalive")

    def fake_run() -> None:
        calls.append("run")

    monkeypatch.setattr(main, "_start_keepalive", fake_keepalive)
    monkeypatch.setattr(main, "run", fake_run)

    main.main()

    assert calls == ["keepalive", "run"]


def test_main_logs_keepalive_failure(monkeypatch, caplog):
    _reload_main()

    def boom() -> None:
        raise RuntimeError("boom")

    run_called: list[bool] = []

    monkeypatch.setattr(main, "_start_keepalive", boom)
    monkeypatch.setattr(main, "run", lambda: run_called.append(True))

    with caplog.at_level("INFO", logger="spectre"):
        main.main()

    assert run_called == [True]
    assert "Keepalive server failed to start" in caplog.text
