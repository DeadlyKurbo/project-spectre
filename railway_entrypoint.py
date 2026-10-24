"""Production entrypoint for Railway deployments.

Runs the FastAPI dashboard as the primary web process and starts the Discord bot
runtime as an optional side process when a bot token is configured.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Final

from spectre.restart_policy import (
    compute_next_restart,
    get_process_restart_schedule,
    write_restart_state,
)

UVICORN_TARGET: Final[str] = os.getenv("UVICORN_APP", "config_app:app")
UVICORN_HOST: Final[str] = os.getenv("UVICORN_HOST", "0.0.0.0")
UVICORN_PORT: Final[str] = os.getenv("PORT", os.getenv("UVICORN_PORT", "8000"))
BOT_ENABLED: Final[bool] = os.getenv("RUN_DISCORD_BOT", "auto").lower() in {"1", "true", "yes", "on", "auto"}
BOT_TOKEN: Final[str | None] = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
# Gives the web logs the same tagged one-line format as the bot.
WEB_LOG_CONFIG: Final[str] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spectre", "web_logging.json")
# One line per HTTP request, mostly health checks and vulnerability scanners
# probing for /setup.php and friends. Off unless explicitly asked for.
WEB_ACCESS_LOG: Final[bool] = os.getenv("WEB_ACCESS_LOG", "").lower() in {"1", "true", "yes", "on"}


def _should_run_bot() -> bool:
    """Return whether the Discord bot should be launched."""

    mode = os.getenv("RUN_DISCORD_BOT", "auto").lower()
    if mode in {"0", "false", "no", "off"}:
        return False
    if mode == "auto":
        return bool(BOT_TOKEN)
    return BOT_ENABLED


def _spawn_bot() -> subprocess.Popen[str] | None:
    """Start the Discord bot process if enabled."""

    if not _should_run_bot():
        print("[railway] Discord bot disabled (set RUN_DISCORD_BOT=true to force enable).", flush=True)
        return None

    if not BOT_TOKEN:
        print("[railway] Discord bot skipped: DISCORD_TOKEN is not configured.", flush=True)
        return None

    print("[railway] Starting Discord bot process.", flush=True)
    return subprocess.Popen([sys.executable, "main.py"], text=True)


def _terminate_process(process: subprocess.Popen[str] | None, *, timeout: float = 20.0) -> None:
    """Terminate a child process gracefully, then force kill if needed."""

    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    """Run uvicorn as the primary process and manage sidecar bot lifecycle."""

    started_at = datetime.now(timezone.utc)
    process_restart_schedule = get_process_restart_schedule()
    next_process_restart = compute_next_restart(started_at, process_restart_schedule)
    write_restart_state(started_at=started_at, next_restart_at=next_process_restart)
    if next_process_restart is None:
        print("[railway] Scheduled process restarts are disabled.", flush=True)
    else:
        print(
            "[railway] Process restart scheduled for "
            f"{next_process_restart:%Y-%m-%d %H:%M} UTC (every "
            f"{process_restart_schedule.interval_days:g} days).",
            flush=True,
        )

    bot_process = _spawn_bot()
    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        UVICORN_TARGET,
        "--host",
        UVICORN_HOST,
        "--port",
        UVICORN_PORT,
        "--log-config",
        WEB_LOG_CONFIG,
    ]
    if not WEB_ACCESS_LOG:
        uvicorn_cmd.append("--no-access-log")

    print(f"[railway] Starting web service on port {UVICORN_PORT}.", flush=True)
    web_process = subprocess.Popen(uvicorn_cmd, text=True)

    def _handle_signal(signum: int, _frame) -> None:
        print(f"[railway] Received signal {signum}; shutting down child processes.", flush=True)
        _terminate_process(web_process)
        _terminate_process(bot_process)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while True:
        if next_process_restart is not None and datetime.now(timezone.utc) >= next_process_restart:
            print("[railway] Scheduled process restart reached; stopping child processes.", flush=True)
            _terminate_process(web_process)
            _terminate_process(bot_process)
            return 0

        web_code = web_process.poll()
        if web_code is not None:
            _terminate_process(bot_process)
            print(f"[railway] Web service exited with code {web_code}.", flush=True)
            return web_code

        if bot_process is not None:
            bot_code = bot_process.poll()
            if bot_code is not None:
                print(
                    f"[railway] Discord bot exited with code {bot_code}; web service continues.",
                    flush=True,
                )
                bot_process = None

        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
