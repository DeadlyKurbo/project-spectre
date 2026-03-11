from __future__ import annotations

import asyncio
import importlib

import main


def _reload_main() -> None:
    importlib.reload(main)


def test_log_action_uses_configured_handler() -> None:
    _reload_main()

    captured: list[tuple[str, bool]] = []

    async def fake_handler(message: str, *, broadcast: bool = True, **kwargs) -> None:
        captured.append((message, broadcast))

    main.set_action_log_handler(fake_handler)
    asyncio.run(main.log_action("audit message", broadcast=True))

    assert captured == [("audit message", True)]


def test_log_action_falls_back_to_logger_when_handler_missing(caplog) -> None:
    _reload_main()

    main.set_action_log_handler(None)

    with caplog.at_level("INFO", logger="spectre"):
        asyncio.run(main.log_action("fallback message", broadcast=True))

    assert "fallback message" in caplog.text
