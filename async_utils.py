import asyncio
import concurrent.futures
import logging
import os
from functools import wraps, partial
from typing import Any, Callable, TypeVar, Coroutine

T = TypeVar("T")


def _max_workers() -> int:
    """Determine the threadpool size from ``ASYNC_UTILS_MAX_WORKERS``.

    Falls back to ``4`` when the variable is missing or malformed and clamps
    values below ``1`` to the default.  A small default keeps memory usage
    predictable on constrained hosts.
    """

    raw = os.getenv("ASYNC_UTILS_MAX_WORKERS")
    try:
        value = int(raw) if raw is not None else 4
        if value < 1:
            raise ValueError
    except ValueError:
        value = 4
    return value


executor = concurrent.futures.ThreadPoolExecutor(max_workers=_max_workers())


def safe_handler(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T | None]]:
    """Decorate an async handler to log exceptions instead of crashing."""

    logger = logging.getLogger("spectre")

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> T | None:
        try:
            return await fn(*args, **kwargs)
        except Exception:  # pragma: no cover - defensive logging
            # Log full traceback so crashes during startup or event handling
            # are visible in the container logs instead of silently failing.
            logger.exception("Handler crash")
            return None

    return wrapper


async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Execute ``func`` in a thread to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(func, *args, **kwargs))


async def event_loop_watchdog(
    loop: asyncio.AbstractEventLoop,
    interval: float = 5.0,
    threshold: float = 5.0,
    logger: logging.Logger | None = None,
) -> None:
    """Periodically log if the event loop is delayed beyond ``threshold`` seconds.

    Args:
        loop: The event loop to monitor.
        interval: How often to check the loop, in seconds.
        threshold: The delay, in seconds, considered a warning.
        logger: Optional logger to use for messages. Defaults to ``logging.getLogger("spectre")``.
    """
    if logger is None:
        logger = logging.getLogger("spectre")

    next_check = loop.time() + interval
    while True:
        await asyncio.sleep(max(next_check - loop.time(), 0))
        delay = loop.time() - next_check
        if delay > threshold:
            logger.error(
                "Event loop is %.1fs behind schedule. Possible blocking call.", delay
            )
        next_check += interval
