"""Log lines from the bot and web processes share one readable format."""

from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path

from spectre.logging_config import ConsoleFormatter, QuietFilter


def _record(name: str, msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, None, None)


def test_console_formatter_tags_the_process():
    line = ConsoleFormatter("bot").format(_record("spectre", "Boot sequence initiated"))

    assert line.endswith("INFO    [bot] spectre: Boot sequence initiated")


def test_uvicorn_lifecycle_messages_are_not_labelled_as_errors():
    record = _record("uvicorn.error", "Application startup complete.")
    line = ConsoleFormatter("web").format(record)

    assert "[web] uvicorn: Application startup complete." in line
    assert record.name == "uvicorn.error"


def test_quiet_filter_drops_pynacl_notice_only():
    quiet = QuietFilter()

    assert not quiet.filter(
        _record("nextcord.client", "PyNaCl is not installed, voice will NOT be supported", logging.WARNING)
    )
    assert quiet.filter(_record("nextcord.gateway", "Shard ID None heartbeat blocked", logging.WARNING))


def test_web_log_config_resolves_the_shared_formatter():
    path = Path(__file__).resolve().parents[1] / "spectre" / "web_logging.json"
    config = json.loads(path.read_text())
    spec = dict(config["formatters"]["console"])

    factory = logging.config.BaseConfigurator({}).resolve(spec.pop("()"))
    formatter = factory(**spec)

    assert "[web] config_app: hello" in formatter.format(_record("config_app", "hello"))
    assert config["root"]["level"] == "WARNING"
